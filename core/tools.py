"""
工具系统（Tool System）
=======================
Agent 可调用工具的注册、分组与执行框架。

核心概念：
  - ToolDef:        工具定义（名称、描述、参数 schema、处理函数）
  - TOOL_MAP:       工具名 → ToolDef 的全局索引
  - TOOL_GROUPS:    工具分组（basic / technical / full / knowledge）
  - get_tools_for_group(): 按分组获取可用工具（减少 LLM 选择负担）
  - run_tool():     统一的工具执行入口

工具列表（12个）：
  基础查询：search_stock / get_stock_info / get_stock_history
  分析工具：predict_stock / compare_stocks / calc_indicators
  深度工具：get_financials / get_news / analyze_stock
  知识工具：search_knowledge
  推荐工具：screen_stocks / recommend_stock
  偏好工具：update_preference
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from core.market_data import (
    StockQuote,
    get_batch_quotes,
    get_daily_kline,
    get_realtime_quote,
    kline_to_dataframe,
    search_stock,
)


@dataclass
class ToolDef:
    """工具定义实体。

    Attributes:
        name:        工具名称（LLM function calling 使用）
        description: 工具功能描述（帮助 LLM 决定何时调用）
        parameters:  参数 schema {参数名: {type, description}}
        handler:     实际执行函数，接收 **kwargs → 返回 str
    """
    name: str
    description: str
    parameters: Dict[str, Dict[str, str]]
    handler: Callable[..., str]

    def to_openai_tool(self) -> dict:
        """转换为 OpenAI function calling 协议格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": list(self.parameters.keys()),
                },
            },
        }

    def to_prompt_desc(self) -> str:
        """转为文本描述（供 System Prompt 或调试）。"""
        params = ", ".join(
            f"{k}: {v.get('description', '')}" for k, v in self.parameters.items()
        )
        return f"- {self.name}({params}): {self.description}"


# ═════════════════════════════════════════════════════════════
# 工具实现函数
# ═════════════════════════════════════════════════════════════


def _tool_search_stock(keyword: str) -> str:
    """搜索股票：根据关键词匹配代码或名称。"""
    results = search_stock(keyword)
    if not results:
        return f"未找到与「{keyword}」匹配的股票。"
    lines = []
    for r in results:
        lines.append(f"{r['code']} — {r['name']}")
    return "找到以下股票：\n" + "\n".join(lines)


def _tool_get_stock_info(code: str) -> str:
    """获取股票实时行情。"""
    q = get_realtime_quote(code)
    if q is None:
        return f"未查询到股票 {code} 的实时数据。请确认代码是否正确（如 600519）。"
    d = q.to_dict()
    lines = [f"{k}: {v}" for k, v in d.items()]
    return "\n".join(lines)


def _tool_get_stock_history(code: str, days: str = "90") -> str:
    """获取股票历史日K线走势。

    包含：区间概览（最高/最低/最近收盘、涨跌幅）+ 最近5日OHLCV明细。
    """
    try:
        n_days = int(days)
    except ValueError:
        n_days = 90
    n_days = min(n_days, 365)  # 上限 365 天

    q = get_realtime_quote(code)
    name = q.name if q else code
    bars = get_daily_kline(code, days=n_days)
    if not bars:
        return f"未获取到 {name}({code}) 的历史K线数据。"

    df = kline_to_dataframe(bars)
    recent5 = df.tail(5)
    summary_parts = [f"{name}({code}) 近{n_days}日历史数据概览：\n"]
    summary_parts.append(f"区间: {str(df['date'].iloc[0])[:10]} ~ {str(df['date'].iloc[-1])[:10]}")
    summary_parts.append(f"数据行数: {len(df)}")

    close = df["close"]
    summary_parts.append(f"区间最高收盘: {close.max():.2f}")
    summary_parts.append(f"区间最低收盘: {close.min():.2f}")
    summary_parts.append(f"最近收盘: {close.iloc[-1]:.2f}")
    if len(close) >= 20:
        summary_parts.append(f"近5日涨跌幅: {(close.iloc[-1] / close.iloc[-5] - 1) * 100:+.2f}%")
        summary_parts.append(f"近20日涨跌幅: {(close.iloc[-1] / close.iloc[-20] - 1) * 100:+.2f}%")

    summary_parts.append("\n最近5日明细：")
    for _, row in recent5.iterrows():
        d = str(row["date"])[:10]
        summary_parts.append(
            f"  {d} O:{row['open']:.2f} H:{row['high']:.2f} "
            f"L:{row['low']:.2f} C:{row['close']:.2f} V:{row['volume']}"
        )
    return "\n".join(summary_parts)


def _get_model_service():
    """懒加载模型服务实例（避免 import 时的循环依赖）。"""
    from core.model_service import StockCNNService
    from pathlib import Path

    BASE = Path(__file__).resolve().parent.parent
    svc = StockCNNService(model_dir=BASE / "models")
    if svc.has_trained_model():
        svc.load()
    return svc


def _tool_predict_stock(code: str) -> str:
    """基于 CNN 模型预测股票涨跌方向。

    Fallback：模型未训练时使用简易均线交叉判断（MA5 vs MA20）。
    """
    q = get_realtime_quote(code)
    name = q.name if q else code

    bars = get_daily_kline(code, days=120)
    if len(bars) < 60:
        return f"{name}({code}) 历史数据不足（需要至少 60 个交易日），无法预测。当前仅获取到 {len(bars)} 条。"

    df = kline_to_dataframe(bars)

    # 重命名列以匹配模型服务的预期格式
    df_model = df.rename(columns={"date": "timestamp"})
    df_model["label"] = 0      # 预测时不需要标签，填占位值
    df_model["vol"] = df_model["volume"]

    try:
        svc = _get_model_service()
        result = svc.predict(df_model)
    except Exception:
        # Fallback：简易均线交叉判断
        close = df["close"]
        latest = close.iloc[-1]
        ma5 = close.iloc[-5:].mean()
        ma20 = close.iloc[-20:].mean() if len(close) >= 20 else close.mean()
        trend = "涨" if ma5 > ma20 else "跌"
        return (
            f"{name}({code}) 趋势分析（简易版，模型暂不可用）：\n"
            f"最近收盘: {latest:.2f}\n"
            f"5日均价: {ma5:.2f}\n"
            f"20日均价: {ma20:.2f}\n"
            f"趋势判断: {trend}（均线交叉信号）\n"
            f"注意：此为简易指标，不构成投资建议。"
        )

    return (
        f"{name}({code}) CNN 模型预测结果：\n"
        f"预测方向: {result['label']}\n"
        f"置信度: {result['confidence']:.2%}\n"
        f"上涨概率: {result['prob_up']:.2%}\n"
        f"下跌概率: {result['prob_down']:.2%}\n"
        f"最近收盘价: {result['latest_close']:.2f}\n"
        f"近5期平均涨跌幅: {result['avg_return_5']:.4f}%\n"
        f"近20期平均涨跌幅: {result['avg_return_20']:.4f}%\n"
        f"\n⚠️ 以上结果仅基于历史序列模式，不构成投资建议。"
    )


def _tool_compare_stocks(codes: str) -> str:
    """多只股票实时行情对比（最多 5 只）。"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        return "请提供要对比的股票代码，用逗号分隔。"
    if len(code_list) > 5:
        return "最多支持5只股票对比。"

    quotes = get_batch_quotes(code_list)
    if not quotes:
        return "未能获取任何股票数据。"

    lines = ["股票对比：\n"]
    lines.append(f"{'名称':<10} {'代码':<8} {'最新价':>8} {'涨跌幅':>8} {'市盈率':>8}")
    lines.append("-" * 50)
    for q in quotes:
        pe_str = f"{q.pe:.1f}" if q.pe > 0 else "亏损"
        lines.append(
            f"{q.name:<10} {q.code:<8} {q.price:>8.2f} {q.change_pct:>+7.2f}% {pe_str:>8}"
        )
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════
# 迭代 2 新增工具
# ═════════════════════════════════════════════════════════════


def _tool_calc_indicators(code: str, days: str = "90") -> str:
    """计算股票技术指标（MA/MACD/RSI/BOLL/KDJ/量比/K线形态）。"""
    from core.indicators import calc_all_indicators
    try:
        n_days = int(days)
    except ValueError:
        n_days = 90
    bundle = calc_all_indicators(code, days=n_days)
    return bundle.format()


def _tool_get_financials(code: str) -> str:
    """获取股票核心财务指标（AKShare/同花顺）。"""
    from core.fundamentals import fetch_financials
    report = fetch_financials(code)
    return report.format()


def _tool_get_news(code: str, keyword: str = "") -> str:
    """获取股票近期新闻舆情。"""
    from core.news import fetch_news
    bundle = fetch_news(code, keyword=keyword)
    return bundle.format()


def _tool_search_knowledge(query: str) -> str:
    """从 RAG 知识库检索投资相关知识。"""
    from core.rag_service import RAGService
    rag = RAGService()
    rag.initialize()
    return rag.search_formatted(query)


def _tool_analyze_stock(code: str) -> str:
    """综合分析一只股票（实时行情 + 技术指标 + 模型预测，三合一）。"""
    info = _tool_get_stock_info(code)
    indicators = _tool_calc_indicators(code, days="90")
    predict = _tool_predict_stock(code)
    return (
        f"==== 综合分析报告 ====\n\n"
        f"--- 实时行情 ---\n{info}\n\n"
        f"--- 技术指标 ---\n{indicators}\n\n"
        f"--- 模型预测 ---\n{predict}\n\n"
        f"⚠️ 综合分析仅供参考，不构成投资建议。"
    )


def _tool_screen_stocks(strategy: str = "综合评分") -> str:
    """按策略筛选股票（选股引擎）。"""
    from core.screener import screen_stocks
    return screen_stocks(strategy=strategy)


def _tool_recommend_stock(style: str = "综合评分") -> str:
    """根据投资风格推荐股票。"""
    from core.screener import recommend_stock
    return recommend_stock(style=style)


def _tool_update_preference(key: str, value: str) -> str:
    """更新用户偏好设置（关注列表/分析风格/风险偏好）。"""
    from core.memory import update_preference
    return update_preference("default", key, value)


# ═════════════════════════════════════════════════════════════
# 工具注册表
# ═════════════════════════════════════════════════════════════

ALL_TOOLS: List[ToolDef] = [
    # ── 基础查询 ──
    ToolDef(
        name="search_stock",
        description="根据关键词搜索股票代码和名称。当用户提到股票名称但不确定代码时使用。",
        parameters={"keyword": {"type": "string", "description": "股票名称或代码关键词"}},
        handler=_tool_search_stock,
    ),
    ToolDef(
        name="get_stock_info",
        description="获取股票实时行情数据：最新价、涨跌幅、成交量、市盈率、市净率、总市值等。需要6位数字股票代码。",
        parameters={"code": {"type": "string", "description": "6位数字股票代码，如600519"}},
        handler=_tool_get_stock_info,
    ),
    ToolDef(
        name="get_stock_history",
        description="获取股票历史日K线数据，含开高低收成交量。用于了解近期走势。",
        parameters={
            "code": {"type": "string", "description": "6位数字股票代码，如600519"},
            "days": {"type": "string", "description": "获取天数，默认90，最大365"},
        },
        handler=_tool_get_stock_history,
    ),
    # ── 分析工具 ──
    ToolDef(
        name="predict_stock",
        description="基于CNN模型预测股票下一时段涨跌方向。需要足够历史数据（60个交易日以上）。",
        parameters={"code": {"type": "string", "description": "6位数字股票代码，如600519"}},
        handler=_tool_predict_stock,
    ),
    ToolDef(
        name="compare_stocks",
        description="对比多只股票的实时行情（最多5只）。",
        parameters={"codes": {"type": "string", "description": "股票代码列表，逗号分隔，如600519,000001"}},
        handler=_tool_compare_stocks,
    ),
    ToolDef(
        name="calc_indicators",
        description="计算股票技术指标：MA均线系统、MACD（金叉/死叉）、RSI、BOLL布林带、KDJ、成交量比。用于技术面分析。",
        parameters={
            "code": {"type": "string", "description": "6位数字股票代码"},
            "days": {"type": "string", "description": "计算天数，默认90"},
        },
        handler=_tool_calc_indicators,
    ),
    # ── 深度分析 ──
    ToolDef(
        name="get_financials",
        description="获取股票核心财务指标：营业总收入、净利润、ROE、毛利率、资产负债率、每股收益等。用于基本面分析。",
        parameters={"code": {"type": "string", "description": "6位数字股票代码"}},
        handler=_tool_get_financials,
    ),
    ToolDef(
        name="get_news",
        description="获取股票近期相关新闻和公告。",
        parameters={
            "code": {"type": "string", "description": "6位数字股票代码"},
            "keyword": {"type": "string", "description": "可选：新闻关键词过滤"},
        },
        handler=_tool_get_news,
    ),
    ToolDef(
        name="search_knowledge",
        description="从投资知识库中检索专业的投资策略、分析方法、风险控制等相关知识。当用户询问理论性问题（如什么是XX指标、如何止损）时使用。",
        parameters={"query": {"type": "string", "description": "知识检索查询语句"}},
        handler=_tool_search_knowledge,
    ),
    ToolDef(
        name="analyze_stock",
        description="对一只股票进行综合分析，包括实时行情、技术指标、模型预测，一次调用产出完整报告。",
        parameters={"code": {"type": "string", "description": "6位数字股票代码"}},
        handler=_tool_analyze_stock,
    ),
    # ── 推荐工具 ──
    ToolDef(
        name="screen_stocks",
        description="按策略筛选股票并排名。支持策略：超卖反弹、趋势强势、低估值、高股息、综合评分。返回Top5候选及推荐理由。",
        parameters={"strategy": {"type": "string", "description": "策略名称：超卖反弹/趋势强势/低估值/高股息/综合评分，默认综合评分"}},
        handler=_tool_screen_stocks,
    ),
    ToolDef(
        name="recommend_stock",
        description="根据投资风格推荐股票。风格：短线/趋势/价值/稳健。当用户要求推荐、荐股、选股时使用。",
        parameters={"style": {"type": "string", "description": "投资风格：短线/趋势/价值/稳健，默认综合"}},
        handler=_tool_recommend_stock,
    ),
    # ── 偏好工具 ──
    ToolDef(
        name="update_preference",
        description="更新用户偏好设置，如关注股票列表、分析风格偏好、风险承受能力。",
        parameters={
            "key": {"type": "string", "description": "偏好项：watchlist, preferred_style, risk_tolerance"},
            "value": {"type": "string", "description": "偏好值"},
        },
        handler=_tool_update_preference,
    ),
]

# 工具名 → ToolDef 的快速索引
TOOL_MAP: Dict[str, ToolDef] = {t.name: t for t in ALL_TOOLS}

# ═════════════════════════════════════════════════════════════
# 工具分组（减少 LLM 的 function calling 选择负担）
# ═════════════════════════════════════════════════════════════

# 基础工具：搜索 + 行情 + K线
_BASIC_TOOLS = {"search_stock", "get_stock_info", "get_stock_history"}
# 技术工具：基础 + 指标 + 预测
_TECHNICAL_TOOLS = _BASIC_TOOLS | {"calc_indicators", "predict_stock"}
# 全量工具：技术 + 财务 + 新闻 + 对比 + 综合分析 + 选股
_FULL_TOOLS = _TECHNICAL_TOOLS | {"get_financials", "get_news", "compare_stocks", "analyze_stock", "screen_stocks", "recommend_stock"}
# 知识工具：检索 + 偏好
_KNOWLEDGE_TOOLS = {"search_knowledge", "update_preference"}

TOOL_GROUPS: Dict[str, set] = {
    "basic": _BASIC_TOOLS,
    "technical": _TECHNICAL_TOOLS,
    "full": _FULL_TOOLS | _KNOWLEDGE_TOOLS,
    "knowledge": _KNOWLEDGE_TOOLS,
}


def get_tools_for_group(group: str) -> List[ToolDef]:
    """按分组名获取可用的工具定义列表。"""
    names = TOOL_GROUPS.get(group, _FULL_TOOLS | _KNOWLEDGE_TOOLS)
    return [TOOL_MAP[n] for n in names if n in TOOL_MAP]


def run_tool(name: str, args: Dict[str, Any]) -> str:
    """统一的工具执行入口。

    Args:
        name: 工具名称
        args: 参数字典（已从 LLM function calling 响应中解析）

    Returns:
        工具执行结果字符串（出错时返回错误描述）
    """
    tool = TOOL_MAP.get(name)
    if tool is None:
        return f"未知工具: {name}"
    try:
        return tool.handler(**args)
    except Exception as e:
        return f"工具 {name} 执行出错: {e}"


def get_tools_prompt() -> str:
    """生成所有工具的文本描述（用于 System Prompt 或调试）。"""
    lines = ["可用工具："]
    for t in ALL_TOOLS:
        lines.append(t.to_prompt_desc())
    return "\n".join(lines)
