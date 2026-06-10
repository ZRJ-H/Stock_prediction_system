"""Leakage-safe intelligence summaries for the historical blind-test game."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from core.llm_service import LLMExplainer


class BlindNewsService:
    """Load offline news and summarize only information available before a target date."""

    FORBIDDEN_OUTPUT = (
        "看涨", "看跌", "预计上涨", "预计下跌", "大概率上涨", "大概率下跌",
        "建议买入", "建议卖出", "做多", "做空", "目标价", "操作建议",
    )

    def __init__(
        self,
        snapshot_path: str | Path,
        llm: LLMExplainer | None = None,
        lookback_days: int = 14,
        max_items: int = 8,
    ) -> None:
        self.snapshot_path = Path(snapshot_path)
        self.llm = llm or LLMExplainer()
        self.lookback_days = lookback_days
        self.max_items = max_items
        self._items: list[dict[str, Any]] | None = None

    @staticmethod
    def _parse_time(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.strip().replace("T", " ").replace("Z", ""))
        except ValueError:
            return None

    def _load(self) -> list[dict[str, Any]]:
        if self._items is not None:
            return self._items
        items: list[dict[str, Any]] = []
        if self.snapshot_path.exists():
            for line in self.snapshot_path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                published_at = self._parse_time(str(item.get("published_at", "")))
                title = str(item.get("title", "")).strip()
                if published_at is None or not title:
                    continue
                item["published_at"] = published_at.strftime("%Y-%m-%d %H:%M:%S")
                items.append(item)
        self._items = sorted(items, key=lambda item: item["published_at"])
        return self._items

    def coverage(self) -> dict[str, Any]:
        items = self._load()
        return {
            "available": bool(items),
            "count": len(items),
            "start": items[0]["published_at"] if items else None,
            "end": items[-1]["published_at"] if items else None,
            "lookback_days": self.lookback_days,
        }

    def before_target(self, target_date: str) -> list[dict[str, Any]]:
        cutoff = datetime.fromisoformat(f"{target_date} 09:30:00")
        start = cutoff - timedelta(days=self.lookback_days)
        selected = []
        for item in self._load():
            published_at = self._parse_time(item["published_at"])
            if published_at is None or not (start <= published_at < cutoff):
                continue
            selected.append({
                "published_at": item["published_at"],
                "title": str(item.get("title", "")),
                "summary": str(item.get("summary", ""))[:300],
                "source": str(item.get("source", "未知来源")),
                "url": str(item.get("url", "")),
            })
        return selected[-self.max_items:]

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text.strip(), re.S)
        candidate = fenced.group(1) if fenced else text.strip()
        if not candidate.startswith("{"):
            match = re.search(r"\{.*\}", candidate, re.S)
            candidate = match.group(0) if match else ""
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _market_metrics(history: pd.DataFrame) -> dict[str, float]:
        close = pd.to_numeric(history["close"], errors="coerce").dropna()
        returns = close.pct_change().dropna()
        peak = close.cummax()
        drawdown = (close / peak - 1).min()
        return {
            "return_5": float(close.iloc[-1] / close.iloc[-6] - 1),
            "return_20": float(close.iloc[-1] / close.iloc[-21] - 1),
            "ma5": float(close.tail(5).mean()),
            "ma20": float(close.tail(20).mean()),
            "volatility_20": float(returns.tail(20).std(ddof=0) * math.sqrt(20)),
            "max_drawdown_60": float(drawdown),
        }

    def _local_intelligence(
        self, history: pd.DataFrame, news_items: list[dict[str, Any]], reason: str = ""
    ) -> dict[str, Any]:
        metrics = self._market_metrics(history)
        relation = "短期均线高于中期均线" if metrics["ma5"] >= metrics["ma20"] else "短期均线低于中期均线"
        uncertainties = [
            f"近20日波动幅度约 {metrics['volatility_20'] * 100:.1f}%，历史波动不能代表目标日结果。",
            f"60日内最大回撤约 {abs(metrics['max_drawdown_60']) * 100:.1f}%。",
        ]
        if not news_items:
            uncertainties.append(f"目标日前{self.lookback_days}天没有合规离线资讯，信息覆盖有限。")
        if reason:
            uncertainties.append(reason)
        return {
            "status": "ready",
            "schema_version": 2,
            "generated_by": "local",
            "market_summary": (
                f"近5日收益 {metrics['return_5'] * 100:.1f}%，"
                f"近20日收益 {metrics['return_20'] * 100:.1f}%；{relation}。"
            ),
            "observations": [
                f"近20日波动幅度约 {metrics['volatility_20'] * 100:.1f}%。",
                f"60日内最大回撤约 {abs(metrics['max_drawdown_60']) * 100:.1f}%。",
            ],
            "event_digest": [
                f"{item['published_at']}：{item['title']}（{item['source']}）"
                for item in news_items
            ][:3],
            "uncertainties": uncertainties,
            "news_items": news_items,
        }

    def _valid_intelligence(self, value: dict[str, Any]) -> bool:
        required = {"market_summary", "observations", "event_digest", "uncertainties"}
        if not required.issubset(value):
            return False
        if any(key in value for key in ("label", "confidence", "probability", "advice")):
            return False
        text = json.dumps(value, ensure_ascii=False)
        return not any(word in text for word in self.FORBIDDEN_OUTPUT)

    def generate(
        self,
        target_date: str,
        history: pd.DataFrame,
        news_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate an intelligence brief without a direction, probability, or advice."""
        if not self.llm.api_key:
            return self._local_intelligence(history, news_items, "大模型未配置，已使用本地行情摘要。")

        metrics = self._market_metrics(history)
        news_text = "\n".join(
            f"- [{item['published_at']}] {item['title']}（{item['source']}）"
            + (f"\n  摘要：{item['summary']}" if item["summary"] else "")
            for item in news_items
        ) or "无合规离线资讯"
        messages = [
            {
                "role": "system",
                "content": (
                    "你是历史盲测中的情报整理员，只能整理用户提供的信息。"
                    "禁止给出涨跌方向、概率、目标价、买卖或操作建议。"
                    "输出严格 JSON，不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"股票：贵州茅台(600519)\n目标交易日：{target_date}\n"
                    "以下数据全部早于目标日开盘：\n"
                    f"近5日收益：{metrics['return_5']:.6f}\n"
                    f"近20日收益：{metrics['return_20']:.6f}\n"
                    f"MA5：{metrics['ma5']:.4f}\nMA20：{metrics['ma20']:.4f}\n"
                    f"近20日波动：{metrics['volatility_20']:.6f}\n"
                    f"60日最大回撤：{metrics['max_drawdown_60']:.6f}\n"
                    f"资讯：\n{news_text}\n\n"
                    '输出 {"market_summary":"客观行情描述",'
                    '"observations":["最多3条值得注意的行情特征"],'
                    '"event_digest":["最多3条资讯事件摘要，不评价利好利空"],'
                    '"uncertainties":["最多3条限制"]}。'
                ),
            },
        ]
        response = self.llm.chat(messages, temperature=0.2)
        parsed = self._extract_json((response or {}).get("content", ""))
        if not parsed or not self._valid_intelligence(parsed):
            return self._local_intelligence(history, news_items, "大模型输出不符合盲测规则，已安全降级。")
        return {
            "status": "ready",
            "schema_version": 2,
            "generated_by": "llm",
            "market_summary": str(parsed["market_summary"])[:300],
            "observations": [str(v)[:120] for v in parsed["observations"][:3]],
            "event_digest": [str(v)[:160] for v in parsed["event_digest"][:3]],
            "uncertainties": [str(v)[:120] for v in parsed["uncertainties"][:3]],
            "news_items": news_items,
        }
