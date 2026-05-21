from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from core.llm_service import LLMExplainer
from core.tools import TOOL_GROUPS, TOOL_MAP, ToolDef, get_tools_for_group, run_tool

MAX_ITERATIONS = 8

_BASE_SYSTEM_PROMPT = """你是一个专业的股票分析助手，可以帮用户查询A股行情、分析走势、预测涨跌、解读技术指标、检索投资知识。

工作方式：
1. 理解用户意图
2. 调用合适的工具获取数据或知识
3. 基于数据给出分析结论

规则：
- 如果用户提到股票名称而非代码，先用 search_stock 查找代码
- 查询行情用 get_stock_info，看历史走势用 get_stock_history
- 预测涨跌用 predict_stock，多股对比用 compare_stocks
- 技术指标分析用 calc_indicators
- 基本面/财报查询用 get_financials
- 新闻舆情查询用 get_news
- 投资理论/策略/方法论问题用 search_knowledge 检索知识库
- 综合性分析请求（同时要求多个维度）用 analyze_stock 一步完成
- **每次只调用一个工具**，获得结果后再决定下一步
- 获得足够数据后，汇总给出清晰结论
- 始终提醒"数据仅供参考，不构成投资建议"
- 回复使用中文，简洁专业
- 如果用户提到关注某只股票，使用 update_preference 记录"""


def _build_system_prompt(session_id: str = "") -> str:
    prompt = _BASE_SYSTEM_PROMPT
    if session_id:
        from core.memory import load_preferences
        prefs = load_preferences(session_id)
        hint = prefs.to_prompt_hint()
        if hint:
            prompt += f"\n\n{hint}"
    return prompt


class StockAgent:
    def __init__(self) -> None:
        self.llm = LLMExplainer()

    def run(self, query: str, session_id: str = "") -> str:
        if self.llm.api_key:
            return self._run_llm(query, session_id)
        return self._run_rule(query, session_id)

    def _select_tool_group(self, query: str) -> str:
        """Select tool group based on query intent to reduce LLM selection burden."""
        q = query.lower()
        # Knowledge / theory questions
        if any(w in q for w in ["什么是", "什么叫", "如何", "怎么", "止损", "仓位", "金叉",
                                  "死叉", "macd", "rsi", "kdj", "boll", "投资策略",
                                  "基本面", "价值投资", "技术分析"]):
            return "full"
        # Technical analysis
        if any(w in q for w in ["指标", "金叉", "死叉", "macd", "rsi", "kdj", "boll",
                                  "布林", "均线", "形态", "成交量", "量能"]):
            return "technical"
        # Comprehensive
        if any(w in q for w in ["综合", "全面", "详细", "财报", "新闻", "分析报告"]):
            return "full"
        # Default: basic + technical (most common)
        return "technical"

    def _run_llm(self, query: str, session_id: str = "") -> str:
        system_prompt = _build_system_prompt(session_id)
        tool_group = self._select_tool_group(query)
        active_tools = get_tools_for_group(tool_group)

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Inject session history if available
        if session_id:
            from core.memory import get_history
            history_msgs = get_history(session_id)
            if history_msgs:
                messages.extend(history_msgs)

        messages.append({"role": "user", "content": query})
        tools_openai = [t.to_openai_tool() for t in active_tools]

        for i in range(MAX_ITERATIONS):
            resp = self.llm.chat(messages, tools=tools_openai)
            if resp is None:
                return self._run_rule(query, session_id)

            if resp.get("tool_calls"):
                tc = resp["tool_calls"][0]
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                result = run_tool(tool_name, tool_args)
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
                # Save to session memory
                if session_id:
                    from core.memory import add_message
                    add_message(session_id, "user", query)
                    add_message(session_id, "assistant", content)
                return content

            if i == 0:
                messages.append({
                    "role": "user",
                    "content": "请调用合适的工具获取数据，然后给出分析结论。",
                })
                continue
            break

        return self._run_rule(query, session_id)

    def _run_rule(self, query: str, session_id: str = "") -> str:
        """Rule-based fallback when LLM is unavailable."""
        code = _extract_code(query)
        keyword = _extract_keyword(query)
        intent = _classify_intent(query)

        # Save to session
        if session_id:
            from core.memory import add_message
            add_message(session_id, "user", query)

        reply = _dispatch(query, code, keyword, intent)

        if session_id and reply:
            from core.memory import add_message
            add_message(session_id, "assistant", reply)
        return reply


def _dispatch(query: str, code: Optional[str], keyword: Optional[str], intent: str) -> str:
    if intent == "search":
        if not keyword:
            return "请提供要搜索的股票名称或代码关键词。"
        from core.tools import _tool_search_stock
        return _tool_search_stock(keyword)

    if intent == "compare":
        codes = re.findall(r"\d{6}", query)
        if len(codes) < 2:
            return "对比分析需要至少2只股票代码，请提供具体的股票代码。"
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

    if intent == "indicators":
        if not code and keyword:
            code = _resolve_code(keyword)
        if not code:
            return "请提供要分析技术指标的6位股票代码，如 600519。"
        from core.tools import _tool_calc_indicators
        return _tool_calc_indicators(code)

    if intent == "financials":
        if not code and keyword:
            code = _resolve_code(keyword)
        if not code:
            return "请提供要查询财报的6位股票代码，如 600519。"
        from core.tools import _tool_get_financials
        return _tool_get_financials(code)

    if intent == "news":
        if not code and keyword:
            code = _resolve_code(keyword)
            if not code:
                kw2 = _extract_keyword(keyword)
                if kw2 and kw2 != keyword:
                    code = _resolve_code(kw2)
        if code:
            from core.tools import _tool_get_news
            return _tool_get_news(code)
        # Keyword-only search (no valid stock code resolved)
        if keyword:
            from core.tools import _tool_get_news
            return _tool_get_news("", keyword=keyword)
        return "请提供要查询新闻的股票代码或名称，如「茅台有什么新闻」。"

    if intent == "knowledge":
        clean_query = re.sub(r"\d{6}", "", query).strip()
        clean_query = _STRIP_FILLER.sub("", clean_query).strip()
        if not clean_query:
            clean_query = query
        from core.tools import _tool_search_knowledge
        return _tool_search_knowledge(clean_query)

    if intent == "recommend":
        from core.tools import _tool_recommend_stock
        style = "综合评分"
        style_map = {
            "短线": "短线", "短期": "短线", "快": "短线",
            "趋势": "趋势", "动量": "趋势", "强势": "趋势",
            "价值": "价值", "便宜": "价值", "低估": "价值", "被低估": "价值", "低估值": "价值",
            "稳健": "稳健", "稳定": "稳健", "保守": "稳健", "高股息": "稳健",
        }
        for k, v in style_map.items():
            if k in query:
                style = v
                break
        return _tool_recommend_stock(style)

    if intent == "preference":
        from core.memory import update_preference
        if not code and keyword:
            code = _resolve_code(keyword)
        if code:
            return update_preference("default", "watchlist", code)
        return "请提供要关注的股票代码或名称，如「关注 600519」。"

    if intent == "analyze":
        if not code and keyword:
            code = _resolve_code(keyword)
        if not code:
            return "请提供要综合分析的6位股票代码，如 600519。"
        from core.tools import _tool_analyze_stock
        return _tool_analyze_stock(code)

    # Default: show stock info
    if not code and keyword:
        code = _resolve_code(keyword)
    if code:
        from core.tools import _tool_get_stock_info
        info = _tool_get_stock_info(code)
        if keyword and keyword in ("行情", "价格", "信息"):
            return info
        from core.tools import _tool_get_stock_history
        history = _tool_get_stock_history(code, "30")
        return info + "\n\n" + history

    if keyword:
        from core.tools import _tool_search_stock
        return _tool_search_stock(keyword)

    return (
        "【迭代2 新能力】\n\n"
        "--- 基础查询 ---\n"
        '1. 搜索股票 — 「搜索平安银行」\n'
        '2. 实时行情 — 「查询 600519 的行情」\n'
        '3. 历史走势 — 「000001 近60天走势」\n'
        '4. 涨跌预测 — 「预测 600519 涨跌」\n'
        '5. 多股对比 — 「对比 600519 和 000001」\n\n'
        "--- 迭代2 新增 ---\n"
        '6. 技术指标 — 「分析 000001 的技术指标」\n'
        '7. 投资知识 — 「什么是金叉死叉」「如何止损」\n'
        '8. 综合分析 — 「综合分析贵州茅台」\n'
        '9. 新闻舆情 — 「茅台最近有什么新闻」\n'
        '10. 选股推荐 — 「推荐一只股票」「有什么低估的」\n'
        '11. 关注股票 — 「关注 600519」\n\n'
        "请告诉我您需要什么？"
    )


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _extract_code(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{6})\b", text)
    return m.group(1) if m else None


_STRIP_FILLER = re.compile(
    r"^(搜索|搜|查找|找|查询|查|看|看看|帮我|请|的|"
    r"预测|分析|评估|对比|比较|告诉|显示|展示|"
    r"什么是|什么叫|如何|怎么|有没有|有没|有什么|"
    r"关注|添加|最近|近期|最新|刚)+|"
    r"(的|了|吗|呢|吧|啊|呀|啦|"
    r"行情|走势|涨跌|价格|股价|信息|数据|情况|"
    r"怎样|如何|怎么样|多少钱|明天|未来|近期|历史|k线|涨了|跌了|"
    r"有什么新闻|有什么消息|的最新消息|最近新闻|相关新闻|新闻|公告|"
    r"最近有什么新闻|最近有什么消息|最近新闻|的最新消息|最新消息|"
    r"最近|指标|技术|基本面|分析报告|综合看看|综合|看看)+$"
)


def _extract_keyword(text: str) -> Optional[str]:
    cleaned = re.sub(r"\d{6}", "", text).strip()
    for _ in range(5):
        prev = cleaned
        cleaned = _STRIP_FILLER.sub("", cleaned).strip()
        if cleaned == prev or not cleaned:
            break
    if not cleaned:
        return None
    if cleaned in ("行情", "走势", "涨跌", "价格", "股价", "信息", "数据", "情况", "指标"):
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
    if any(w in q for w in ["搜索", "搜", "找", "查找", "叫什么", "代码"]):
        return "search"
    if any(w in q for w in ["对比", "比较", "vs"]):
        return "compare"
    if any(w in q for w in ["什么是", "什么叫", "如何", "怎么", "止损", "策略", "原则",
                              "仓位管理", "风险管理", "价值投资", "投资知识", "理论"]):
        return "knowledge"
    if any(w in q for w in ["指标", "macd", "rsi", "kdj", "boll", "布林", "金叉",
                              "死叉", "均线", "形态", "技术分析", "技术面", "技术指标"]):
        return "indicators"
    if any(w in q for w in ["财报", "财务", "基本面", "营收", "净利润", "roe", "估值"]):
        return "financials"
    if any(w in q for w in ["新闻", "公告", "消息", "舆情", "资讯", "有什么新闻",
                              "最新消息", "相关新闻"]):
        return "news"
    if any(w in q for w in ["综合", "全面", "详细", "分析报告", "综合看看"]):
        return "analyze"
    if any(w in q for w in ["推荐", "荐股", "选股", "选一只", "推荐一只", "有什么好的",
                              "买什么", "哪只", "哪支", "挑选", "筛选", "低估", "便宜",
                              "值得买", "可以买", "潜力", "机会", "被低估"]):
        return "recommend"
    if any(w in q for w in ["关注", "添加关注", "加入自选", "收藏"]):
        return "preference"
    if any(w in q for w in ["历史", "走势", "k线", "过去", "近期"]):
        return "history"
    if any(w in q for w in ["预测", "涨跌", "明天", "未来", "forecast"]):
        return "predict"
    if any(w in q for w in ["行情", "价格", "多少钱", "涨了", "跌了"]):
        return "info"
    return "default"
