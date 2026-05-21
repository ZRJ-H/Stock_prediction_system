from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from core.llm_service import LLMExplainer
from core.tools import TOOL_MAP, ToolDef, get_tools_prompt, run_tool

MAX_ITERATIONS = 6

SYSTEM_PROMPT = """你是一个专业的股票分析助手，可以帮用户查询A股行情、分析走势、预测涨跌。

工作方式：
1. 理解用户意图
2. 调用合适的工具获取数据
3. 基于数据给出分析结论

规则：
- 如果用户提到股票名称而非代码，先用 search_stock 查找代码
- 查询行情用 get_stock_info，看历史走势用 get_stock_history
- 预测涨跌用 predict_stock，多股对比用 compare_stocks
- **每次只调用一个工具**，获得结果后再决定下一步
- 获得足够数据后，汇总给出清晰结论
- 始终提醒"数据仅供参考，不构成投资建议"
- 回复使用中文，简洁专业

输出格式：
- 需要调用工具时，输出 JSON：{"tool": "工具名", "args": {"参数名": "参数值"}}
- 不需要工具时，直接输出文本回复"""


class StockAgent:
    def __init__(self) -> None:
        self.llm = LLMExplainer()

    def run(self, query: str) -> str:
        if self.llm.api_key:
            return self._run_llm(query)
        return self._run_rule(query)

    def _run_llm(self, query: str) -> str:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        tools_openai = [t.to_openai_tool() for t in _active_tools()]
        history: List[str] = []

        for i in range(MAX_ITERATIONS):
            resp = self.llm.chat(messages, tools=tools_openai if tools_openai else None)
            if resp is None:
                return self._run_rule(query)

            if resp.get("tool_calls"):
                tc = resp["tool_calls"][0]
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                result = run_tool(tool_name, tool_args)
                history.append(f"[调用 {tool_name}: {result}]")
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args, ensure_ascii=False),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": f"call_{i}",
                    "content": result,
                })
                continue

            content = resp.get("content", "")
            if content.strip():
                return content

            # Empty response — try once more with explicit instruction
            if i == 0:
                messages.append({
                    "role": "user",
                    "content": "请调用合适的工具获取数据，然后给出分析结论。",
                })
                continue
            break

        # Last fallback: call rule-based
        return self._run_rule(query)

    def _run_rule(self, query: str) -> str:
        """Rule-based fallback when LLM is unavailable."""
        code = _extract_code(query)
        keyword = _extract_keyword(query)

        intent = _classify_intent(query)

        if intent == "search":
            if not keyword:
                return "请提供要搜索的股票名称或代码关键词。"
            from core.tools import _tool_search_stock
            return _tool_search_stock(keyword)

        if intent == "compare":
            codes = re.findall(r"\d{6}", query)
            if len(codes) < 2:
                return "对比分析需要至少2只股票代码（6位数字），请提供具体的股票代码。"
            from core.tools import _tool_compare_stocks
            return _tool_compare_stocks(",".join(codes))

        if intent == "history":
            if not code and keyword:
                code = _resolve_code(keyword)
            if not code:
                return "请提供要查看的6位股票代码，如 600519。"
            from core.tools import _tool_get_stock_history
            days = "90"
            days_match = re.search(r"(\d+)\s*天", query)
            if days_match:
                days = days_match.group(1)
            return _tool_get_stock_history(code, days)

        if intent in ("predict", "forecast"):
            if not code and keyword:
                code = _resolve_code(keyword)
            if not code:
                return "请提供要预测的6位股票代码，如 000001。"
            from core.tools import _tool_predict_stock
            return _tool_predict_stock(code)

        # Default: show stock info
        if not code and keyword:
            code = _resolve_code(keyword)
        if code:
            from core.tools import _tool_get_stock_info
            info = _tool_get_stock_info(code)
            if keyword:
                return info
            from core.tools import _tool_get_stock_history
            history = _tool_get_stock_history(code, "30")
            return info + "\n\n" + history

        if keyword:
            from core.tools import _tool_search_stock
            return _tool_search_stock(keyword)

        return (
            "我可以帮您：\n"
            '1. 搜索股票 — 如「搜索平安银行」\n'
            '2. 查看行情 — 如「查询 600519 的行情」\n'
            '3. 查看走势 — 如「000001 近60天走势」\n'
            '4. 预测涨跌 — 如「预测 600519 涨跌」\n'
            '5. 多股对比 — 如「对比 600519 和 000001」\n'
            "请告诉我您需要什么？"
        )


def _extract_code(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{6})\b", text)
    return m.group(1) if m else None


_STRIP_FILLER = re.compile(
    r"^(搜索|搜|查找|找|查询|查|看|看看|帮我|请|的|"
    r"预测|分析|评估|对比|比较|告诉|显示|展示)+|"
    r"(的|了|吗|呢|吧|啊|呀|啦|"
    r"行情|走势|涨跌|价格|股价|信息|数据|情况|"
    r"怎样|如何|怎么样|多少钱|明天|未来|近期|历史|k线|涨了|跌了)+$"
)


def _extract_keyword(text: str) -> Optional[str]:
    cleaned = re.sub(r"\d{6}", "", text).strip()
    # Repeatedly strip prefix/suffix filler words
    for _ in range(5):
        prev = cleaned
        cleaned = _STRIP_FILLER.sub("", cleaned).strip()
        if cleaned == prev or not cleaned:
            break
    if not cleaned:
        return None
    if cleaned in ("行情", "走势", "涨跌", "价格", "股价", "信息", "数据", "情况"):
        return None
    m = re.search(r"[一-鿿]{2,}(?:银行|保险|证券|科技|股份|集团|电器|汽车|能源|医药|电子|通信|地产|食品|化工|电力|锂电|白酒|半导体)?", cleaned)
    if m:
        return m.group(0)
    m = re.search(r"[一-鿿]{2,}", cleaned)
    return m.group(0) if m else None


def _resolve_code(keyword: str) -> Optional[str]:
    from core.market_data import search_stock
    results = search_stock(keyword, limit=3)
    if len(results) == 1:
        return results[0]["code"]
    return None


def _classify_intent(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ["搜索", "搜索", "找", "查找", "叫什么", "代码"]):
        return "search"
    if any(w in q for w in ["对比", "比较", "vs", "和"]):
        return "compare"
    if any(w in q for w in ["历史", "走势", "k线", "过去", "近期"]):
        return "history"
    if any(w in q for w in ["预测", "涨跌", "明天", "未来", "forecast"]):
        return "predict"
    if any(w in q for w in ["行情", "价格", "多少钱", "涨了", "跌了"]):
        return "info"
    return "default"


def _active_tools() -> List[ToolDef]:
    return list(TOOL_MAP.values())
