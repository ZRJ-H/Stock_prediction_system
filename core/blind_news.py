"""Historical-news support for the blind-test game."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.llm_service import LLMExplainer


class BlindNewsService:
    """Load an offline news snapshot and create a leakage-safe LLM prediction."""

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
        normalized = value.strip().replace("T", " ").replace("Z", "")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    def _load(self) -> list[dict[str, Any]]:
        if self._items is not None:
            return self._items
        items: list[dict[str, Any]] = []
        if self.snapshot_path.exists():
            for line in self.snapshot_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
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
        """Return only news published before 09:30 on the target trading day."""
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
        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
        candidate = fenced.group(1) if fenced else text
        if not candidate.startswith("{"):
            match = re.search(r"\{.*\}", candidate, re.S)
            candidate = match.group(0) if match else ""
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    def predict(self, target_date: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {
                "status": "abstained",
                "message": f"目标日前{self.lookback_days}天没有合规的离线新闻。",
            }
        if not self.llm.api_key:
            return {
                "status": "abstained",
                "message": "大模型未配置，新闻 AI 本轮弃权。",
            }

        news_text = "\n".join(
            f"- [{item['published_at']}] {item['title']}（{item['source']}）"
            + (f"\n  摘要：{item['summary']}" if item["summary"] else "")
            for item in items
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是历史盲测中的新闻分析员。只能使用用户提供且早于目标日开盘的资讯，"
                    "不得调用外部知识，不得假设目标日结果。输出严格 JSON，不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"股票：贵州茅台(600519)\n目标交易日：{target_date}\n"
                    f"可用资讯：\n{news_text}\n\n"
                    '请输出 {"label":"涨或跌","confidence":0到1,'
                    '"reasons":["最多三条简短理由"],"risk":"一句风险说明"}。'
                ),
            },
        ]
        response = self.llm.chat(messages, temperature=0.2)
        parsed = self._extract_json((response or {}).get("content", ""))
        if not parsed or parsed.get("label") not in {"涨", "跌"}:
            return {"status": "abstained", "message": "新闻 AI 返回格式异常，本轮弃权。"}
        try:
            confidence = min(1.0, max(0.0, float(parsed.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        reasons = [
            str(reason).strip()[:100]
            for reason in parsed.get("reasons", [])
            if str(reason).strip()
        ][:3]
        return {
            "status": "ready",
            "label": parsed["label"],
            "confidence": confidence,
            "reasons": reasons,
            "risk": str(parsed.get("risk", "")).strip()[:150],
        }
