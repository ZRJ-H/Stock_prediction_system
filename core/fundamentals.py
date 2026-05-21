"""Financial report data fetcher. AKShare first, graceful degradation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.market_data import get_realtime_quote


@dataclass
class FinancialReport:
    code: str
    name: str
    indicators: Dict[str, str] = field(default_factory=dict)
    source: str = ""

    def format(self) -> str:
        if not self.indicators:
            return f"{self.name}({self.code}) 财报数据暂不可用。\n请确保网络可访问且 AKShare 正常（设置 USE_AKSHARE=1）。"

        lines = [f"{self.name}({self.code}) 核心财务指标：\n"]
        lines.append(f"数据来源：{self.source}")
        label_map = {
            "revenue": "营业总收入",
            "net_profit": "净利润",
            "roe": "ROE（净资产收益率）",
            "gross_margin": "毛利率",
            "debt_ratio": "资产负债率",
            "eps": "每股收益",
            "bvps": "每股净资产",
        }
        for key, label in label_map.items():
            if key in self.indicators:
                lines.append(f"  {label}: {self.indicators[key]}")
        lines.append("\n⚠️ 财报数据有一定滞后性，请以最新季报/年报为准。")
        return "\n".join(lines)


def fetch_financials(code: str) -> FinancialReport:
    q = get_realtime_quote(code)
    name = q.name if q else code

    import os

    if os.environ.get("USE_AKSHARE", "").lower() not in ("1", "true", "yes"):
        return FinancialReport(
            code=code,
            name=name,
            indicators={},
            source="未启用 AKShare（设置 USE_AKSHARE=1 开启）",
        )

    try:
        import akshare as ak

        # Try to get financial abstract from THS (同花顺)
        try:
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        except Exception:
            df = None

        if df is None or df.empty:
            return FinancialReport(
                code=code, name=name,
                indicators={"提示": "该股票暂无同花顺财报摘要数据"},
                source="AKShare/同花顺",
            )

        latest = df.iloc[0]
        indicators: Dict[str, str] = {}

        def _get(col_name: str) -> Optional[str]:
            for c in df.columns:
                if col_name in c:
                    val = latest[c]
                    if val and str(val) != "nan":
                        return str(val)
            return None

        for key, col_hint in [
            ("revenue", "营业总收入"),
            ("net_profit", "净利润"),
            ("roe", "净资产收益率"),
            ("gross_margin", "毛利率"),
            ("debt_ratio", "资产负债率"),
            ("eps", "每股收益"),
            ("bvps", "每股净资产"),
        ]:
            val = _get(col_hint)
            if val:
                indicators[key] = val

        return FinancialReport(code=code, name=name, indicators=indicators, source="AKShare/同花顺")

    except Exception as e:
        return FinancialReport(
            code=code, name=name,
            indicators={"错误": f"数据获取异常：{e}"},
            source="AKShare",
        )
