"""
基本面数据获取模块（Fundamentals Fetcher）
==========================================
通过 AKShare（同花顺数据源）获取 A 股核心财务指标。

使用前提：
  - 需设置环境变量 USE_AKSHARE=1 并安装 akshare 包
  - 未启用时返回空报告（提示用户开启）

获取指标：
  - 营业总收入 / 净利润
  - ROE（净资产收益率）/ 毛利率
  - 资产负债率 / 每股收益（EPS）/ 每股净资产（BVPS）

设计原则：
  - AKShare 网络不稳定 → 默认不调用，由用户主动启用
  - 获取失败不抛异常 → 返回带错误信息的 FinancialReport
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.market_data import get_realtime_quote


@dataclass
class FinancialReport:
    """财报数据报告实体。

    Attributes:
        code:       6 位股票代码
        name:       股票名称
        indicators: 指标字典（key: 指标英文名 → value: 格式化值）
        source:     数据来源描述
    """
    code: str
    name: str
    indicators: Dict[str, str] = field(default_factory=dict)
    source: str = ""

    def format(self) -> str:
        """将财报指标格式化为可读文本。"""
        if not self.indicators:
            return (
                f"{self.name}({self.code}) 财报数据暂不可用。\n"
                "请确保网络可访问且 AKShare 正常（设置 USE_AKSHARE=1）。"
            )

        lines = [f"{self.name}({self.code}) 核心财务指标：\n"]
        lines.append(f"数据来源：{self.source}")

        # 中文标签映射
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
    """获取指定股票的财务摘要数据。

    流程：
      1. 获取实时行情（拿到股票名称）
      2. 检查 USE_AKSHARE 环境变量
      3. 通过 AKShare 调用同花顺财务摘要接口
      4. 解析并提取核心指标

    Args:
        code: 6 位股票代码

    Returns:
        FinancialReport（获取失败时 indicators 为空且有原因说明）
    """
    q = get_realtime_quote(code)
    name = q.name if q else code

    import os

    # 未启用 AKShare → 快速返回空报告
    if os.environ.get("USE_AKSHARE", "").lower() not in ("1", "true", "yes"):
        return FinancialReport(
            code=code,
            name=name,
            indicators={},
            source="未启用 AKShare（设置 USE_AKSHARE=1 开启）",
        )

    try:
        import akshare as ak

        # 同花顺财务摘要（按报告期）
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

        latest = df.iloc[0]  # 最新一期报告
        indicators: Dict[str, str] = {}

        # 模糊匹配列名（不同版本 AKShare 列名可能有差异）
        def _get(col_name: str) -> Optional[str]:
            for c in df.columns:
                if col_name in c:
                    val = latest[c]
                    if val and str(val) != "nan":
                        return str(val)
            return None

        # 按 hint 关键词从 DataFrame 列中提取指标
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
