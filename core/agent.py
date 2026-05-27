"""
股票分析对话 Agent（Stock Agent）
==================================
系统的核心调度层，负责理解用户意图并协调工具执行。

双模式运行：
  1. LLM 模式（OPENAI_API_KEY 已配置）：
     使用大模型做意图理解 + function calling，支持多轮工具调用（最多8轮）
  2. 规则模式（离线/降级）：
     基于关键词匹配做意图分类 + 直接调度工具，无 LLM 依赖

核心流程：
  run(query, session_id) → 判断在线/离线 → 路由到对应模式 → 返回回复文本

意图分类（13种）：
  search / compare / history / predict / indicators / financials
  / news / knowledge / recommend / risk / preference / analyze / default

工具分组策略：
  根据查询关键词动态选择工具子集，减少 LLM function calling 的选择空间
  - basic:     搜索 + 行情 + K线
  - technical: basic + 指标 + 预测
  - full:      全部工具
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from core.llm_service import LLMExplainer
from core.tools import get_tools_for_group, run_tool

# LLM 模式最大工具调用轮次（防止无限循环）
MAX_ITERATIONS = 8

# 基础 System Prompt（注入给 LLM 的行为指令）
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
    """构建完整的 System Prompt（基础指令 + 用户偏好提示）。

    Args:
        session_id: 会话 ID，用于加载该用户的偏好设置

    Returns:
        完整的 System Prompt 字符串
    """
    prompt = _BASE_SYSTEM_PROMPT
    if session_id:
        from core.memory import load_preferences
        prefs = load_preferences(session_id)
        hint = prefs.to_prompt_hint()
        if hint:
            prompt += f"\n\n{hint}"
    return prompt


class StockAgent:
    """股票分析对话 Agent。

    使用示例：
        agent = StockAgent()
        reply = agent.run("分析贵州茅台", session_id="abc123")
    """

    def __init__(self) -> None:
        self.llm = LLMExplainer()

    def run(self, query: str, session_id: str = "") -> str:
        """主入口：处理用户查询并返回回复。

        路由策略：有 API key → LLM 模式，无 key → 规则模式。
        """
        if self.llm.api_key:
            return self._run_llm(query, session_id)
        return self._run_rule(query, session_id)

    def _select_tool_group(self, query: str) -> str:
        """根据查询内容智能选择工具分组。

        分组选择逻辑：
          - 含知识/理论/策略相关词 → full（可能需要检索知识库）
          - 含技术指标相关词       → technical
          - 含综合/深度分析相关词  → full
          - 含风险/仓位相关词      → full
          - 默认                   → technical

        目的：减少每个 LLM 请求携带的 function 定义数量，降低 token 消耗
              同时提高工具选择的准确率（选项少 → 选错概率低）
        """
        q = query.lower()
        # 知识/理论类问题 → 全部工具
        if any(w in q for w in ["什么是", "什么叫", "如何", "怎么", "止损", "仓位", "金叉",
                                  "死叉", "macd", "rsi", "kdj", "boll", "投资策略",
                                  "基本面", "价值投资", "技术分析"]):
            return "full"
        # 技术分析类 → 技术工具
        if any(w in q for w in ["指标", "金叉", "死叉", "macd", "rsi", "kdj", "boll",
                                  "布林", "均线", "形态", "成交量", "量能"]):
            return "technical"
        # 综合/深度分析类 → 全部工具
        if any(w in q for w in ["综合", "全面", "详细", "财报", "新闻", "分析报告",
                                  "风险", "仓位", "回撤", "波动"]):
            return "full"
        # 默认 → 技术工具（覆盖最常见查询场景）
        return "technical"

    def _run_llm(self, query: str, session_id: str = "") -> str:
        """LLM 模式：使用大模型理解意图 + function calling 调用工具。

        流程：
          1. 构建 System Prompt（含用户偏好）
          2. 选择工具分组，转换为 OpenAI tool 格式
          3. 注入会话历史（如有）
          4. 多轮迭代：
             a. 调用 LLM → 得到 text 或 tool_call
             b. 如果是 tool_call → 执行工具 → 将结果追加到消息中 → 继续
             c. 如果是 text → 返回最终回复
          5. 超时或异常 → 降级到规则模式
        """
        # 注入当前 session，确保 tools.py 中偏好操作使用正确的 session_id
        if session_id:
            from core.tools import set_current_session
            set_current_session(session_id)

        system_prompt = _build_system_prompt(session_id)
        tool_group = self._select_tool_group(query)
        active_tools = get_tools_for_group(tool_group)

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # 注入会话历史（最近 10 轮对话）
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
                # API 调用失败 → 降级到规则模式
                return self._run_rule(query, session_id)

            # 情况 A：LLM 请求调用工具
            if resp.get("tool_calls"):
                tc = resp["tool_calls"][0]
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                # 执行工具并获取结果
                result = run_tool(tool_name, tool_args)
                # 将 assistant 的 tool_call 消息 + tool 结果追加到对话
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
                continue  # 继续下一轮

            # 情况 B：LLM 返回最终文本回复
            content = resp.get("content", "")
            if content.strip():
                # 保存到会话记忆
                if session_id:
                    from core.memory import add_message
                    add_message(session_id, "user", query)
                    add_message(session_id, "assistant", content)
                return content

            # 情况 C：首轮无内容也没调工具 → 引导 LLM 更明确
            if i == 0:
                messages.append({
                    "role": "user",
                    "content": "请调用合适的工具获取数据，然后给出分析结论。",
                })
                continue
            break

        # 所有轮次都未得到有效回复 → 降级
        return self._run_rule(query, session_id)

    def _run_rule(self, query: str, session_id: str = "") -> str:
        """规则模式：基于关键词的意图分类 + 直接工具调度。

        当 LLM 不可用（无 API key 或 API 调用失败）时使用此模式。
        流程：
          1. 提取 6 位代码和关键词
          2. 分类意图（11 种）
          3. 按意图分发到对应工具
          4. 保存到会话记忆
        """
        code = _extract_code(query)
        keyword = _extract_keyword(query)
        intent = _classify_intent(query)

        # 注入当前 session，确保偏好/记忆写入正确的用户文件
        if session_id:
            from core.memory import add_message
            add_message(session_id, "user", query)
            from core.tools import set_current_session
            set_current_session(session_id)

        reply = _dispatch(query, code, keyword, intent, session_id)

        # 保存助手回复到会话
        if session_id and reply:
            from core.memory import add_message
            add_message(session_id, "assistant", reply)
        return reply


# ═════════════════════════════════════════════════════════════
# 意图分发器：根据意图类型路由到对应的工具处理函数
# ═════════════════════════════════════════════════════════════

def _dispatch(query: str, code: Optional[str], keyword: Optional[str],
              intent: str, session_id: str = "") -> str:
    """根据意图类型执行对应的工具并返回结果。

    意图 → 工具映射：
      search      → search_stock（股票搜索）
      compare     → compare_stocks（多股对比）
      history     → get_stock_history（历史K线）
      predict     → predict_stock（涨跌预测）
      indicators  → calc_indicators（技术指标）
      financials  → get_financials（财报）
      news        → get_news（新闻）
      knowledge   → search_knowledge（知识检索）
      recommend   → recommend_stock（选股推荐）
      preference  → update_preference（偏好设置）
      analyze     → analyze_stock（综合分析）
      default     → get_stock_info + get_stock_history（默认行情+K线）
    """

    # ── 搜索股票 ──
    if intent == "search":
        if not keyword:
            return "请提供要搜索的股票名称或代码关键词。"
        from core.tools import _tool_search_stock
        return _tool_search_stock(keyword)

    # ── 多股对比 ──
    if intent == "compare":
        codes = re.findall(r"\d{6}", query)
        if len(codes) < 2:
            return "对比分析需要至少2只股票代码，请提供具体的股票代码。"
        from core.tools import _tool_compare_stocks
        return _tool_compare_stocks(",".join(codes))

    # ── 历史走势 ──
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

    # ── 涨跌预测 ──
    if intent in ("predict", "forecast"):
        if not code and keyword:
            code = _resolve_code(keyword)
        if not code:
            return "请提供要预测的6位股票代码，如 000001。"
        from core.tools import _tool_predict_stock
        return _tool_predict_stock(code)

    # ── 技术指标（迭代3：升级为 Skill 报告）──
    if intent == "indicators":
        if not code and keyword:
            code = _resolve_code(keyword)
        if not code:
            return "请提供要分析技术指标的6位股票代码，如 600519。"
        from core.skills.technical import TechnicalSkill
        return TechnicalSkill().execute(code).format()

    # ── 财报（迭代3：升级为 Skill 报告）──
    if intent == "financials":
        if not code and keyword:
            code = _resolve_code(keyword)
        if not code:
            return "请提供要查询财报的6位股票代码，如 600519。"
        from core.skills.fundamental import FundamentalSkill
        return FundamentalSkill().execute(code).format()

    # ── 风险评估（迭代3新增）──
    if intent == "risk":
        if not code and keyword:
            code = _resolve_code(keyword)
        if not code:
            return "请提供要评估风险的6位股票代码，如 600519。"
        from core.skills.risk import RiskSkill
        return RiskSkill().execute(code).format()

    # ── 新闻舆情（迭代3：升级为 Skill 报告）──
    if intent == "news":
        if not code and keyword:
            code = _resolve_code(keyword)
            if not code:
                kw2 = _extract_keyword(keyword)
                if kw2 and kw2 != keyword:
                    code = _resolve_code(kw2)
        if code:
            from core.skills.news import NewsSkill
            return NewsSkill().execute(code).format()
        if keyword:
            from core.skills.news import NewsSkill
            return NewsSkill().execute("", keyword=keyword).format()
        return "请提供要查询新闻的股票代码或名称，如「茅台有什么新闻」。"

    # ── 知识检索 ──
    if intent == "knowledge":
        # 清洗查询文本：去代码、去填充词 → 得到纯搜索意图
        clean_query = re.sub(r"\d{6}", "", query).strip()
        clean_query = _STRIP_FILLER.sub("", clean_query).strip()
        if not clean_query:
            clean_query = query
        from core.tools import _tool_search_knowledge
        return _tool_search_knowledge(clean_query)

    # ── 选股推荐（迭代3：使用 ScreeningSkill）──
    if intent == "recommend":
        from core.skills.screening import ScreeningSkill
        style = "综合评分"
        style_map = {
            "短线": "超卖反弹", "短期": "超卖反弹", "快": "超卖反弹",
            "趋势": "趋势强势", "动量": "趋势强势", "强势": "趋势强势",
            "价值": "低估值", "便宜": "低估值", "低估": "低估值",
            "被低估": "低估值", "低估值": "低估值",
            "稳健": "高股息", "稳定": "高股息", "保守": "高股息",
        }
        for k, v in style_map.items():
            if k in query:
                style = v
                break
        return ScreeningSkill().execute(strategy=style).format()

    # ── 偏好设置 ──
    if intent == "preference":
        from core.memory import update_preference
        if not code and keyword:
            code = _resolve_code(keyword)
        if code:
            sid = session_id or "default"
            return update_preference(sid, "watchlist", code)
        return "请提供要关注的股票代码或名称，如「关注 600519」。"

    # ── 综合分析（迭代3：升级为 ComprehensiveSkill）──
    if intent == "analyze":
        if not code and keyword:
            code = _resolve_code(keyword)
        if not code:
            return "请提供要综合分析的6位股票代码，如 600519。"
        from core.skills.comprehensive import ComprehensiveSkill
        return ComprehensiveSkill().execute(code).format()

    # ── 默认：显示行情 + 短期走势 ──
    if not code and keyword:
        code = _resolve_code(keyword)
    if code:
        from core.tools import _tool_get_stock_info
        info = _tool_get_stock_info(code)
        # 如果用户只关心行情 → 不追加走势
        if keyword and keyword in ("行情", "价格", "信息"):
            return info
        from core.tools import _tool_get_stock_history
        history = _tool_get_stock_history(code, "30")
        return info + "\n\n" + history

    # ── 只有关键词无代码 → 搜索匹配 ──
    if keyword:
        from core.tools import _tool_search_stock
        return _tool_search_stock(keyword)

    # ── 什么都匹配不到 → 显示帮助 ──
    return (
        "【迭代3 Skill 系统】\n\n"
        "--- 基础查询 ---\n"
        '1. 搜索股票 — 「搜索平安银行」\n'
        '2. 实时行情 — 「查询 600519 的行情」\n'
        '3. 历史走势 — 「000001 近60天走势」\n'
        '4. 涨跌预测 — 「预测 600519 涨跌」\n'
        '5. 多股对比 — 「对比 600519 和 000001」\n\n'
        "--- Skill 技能（迭代3新增）---\n"
        '6. 技术分析报告 — 「技术分析贵州茅台」(评分+操作建议)\n'
        '7. 基本面分析 — 「基本面分析 000001」(估值评级)\n'
        '8. 风险评估 — 「评估 600519 的风险」(波动率/回撤/仓位)\n'
        '9. 新闻舆情 — 「茅台最近有什么新闻」(情感分析)\n'
        '10. 综合分析 — 「综合分析贵州茅台」(四维度报告)\n'
        '11. 选股推荐 — 「推荐一只短线股」\n\n'
        "--- 其他 ---\n"
        '12. 投资知识 — 「什么是金叉死叉」\n'
        '13. 关注股票 — 「关注 600519」\n\n'
        "请告诉我您需要什么？"
    )


# ═════════════════════════════════════════════════════════════
# 文本解析辅助函数
# ═════════════════════════════════════════════════════════════

def _extract_code(text: str) -> Optional[str]:
    """从文本中提取 6 位数字股票代码（正则匹配）。"""
    m = re.search(r"\b(\d{6})\b", text)
    return m.group(1) if m else None


# 填充词/停用词正则：用于从查询中剥离无关词，提取核心关键词
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
    """从查询文本中提取中文关键词（股票名称或概念）。

    处理流程：
      1. 去掉 6 位数字代码
      2. 递归剥离填充词（最多 5 轮）
      3. 匹配中文名（优先含行业后缀的完整名 → 至少 2 个汉字）

    Returns:
        提取到的关键词，无法提取时返回 None
    """
    cleaned = re.sub(r"\d{6}", "", text).strip()
    for _ in range(5):
        prev = cleaned
        cleaned = _STRIP_FILLER.sub("", cleaned).strip()
        if cleaned == prev or not cleaned:
            break
    if not cleaned:
        return None
    # 过滤纯描述性词（这些词不能作为股票名称）
    if cleaned in ("行情", "走势", "涨跌", "价格", "股价", "信息", "数据", "情况", "指标"):
        return None
    # 优先匹配含行业后缀的完整名称（如 "平安银行"）
    m = re.search(
        r"[一-鿿]{2,}(?:银行|保险|证券|科技|股份|集团|电器|汽车|能源|医药|电子|通信|地产|食品|化工|电力|锂电|白酒|半导体)?",
        cleaned
    )
    if m:
        return m.group(0)
    # 回落：至少 2 个连续汉字
    m = re.search(r"[一-鿿]{2,}", cleaned)
    return m.group(0) if m else None


def _resolve_code(keyword: str) -> Optional[str]:
    """将中文关键词解析为 6 位股票代码。

    仅在搜索结果唯一时返回（避免歧义）。
    """
    from core.market_data import search_stock
    results = search_stock(keyword, limit=3)
    if len(results) == 1:
        return results[0]["code"]
    return None


def _classify_intent(query: str) -> str:
    """基于关键词将用户查询分类为 11 种意图之一。

    优先级设计原则：
      - 具体词 > 通用词（如"金叉"优先于"分析"）
      - 意图按匹配顺序判定（越具体的意图放越前面）
      - 兜底：default → 显示行情+帮助
    """
    q = query.lower()
    # 搜索意图：找股票
    if any(w in q for w in ["搜索", "搜", "找", "查找", "叫什么", "代码"]):
        return "search"
    # 对比意图
    if any(w in q for w in ["对比", "比较", "vs"]):
        return "compare"
    # 知识意图：理论/策略/方法论
    if any(w in q for w in ["什么是", "什么叫", "如何", "怎么", "止损", "策略", "原则",
                              "仓位管理", "风险管理", "价值投资", "投资知识", "理论"]):
        return "knowledge"
    # 技术指标意图
    if any(w in q for w in ["指标", "macd", "rsi", "kdj", "boll", "布林", "金叉",
                              "死叉", "均线", "形态", "技术分析", "技术面", "技术指标"]):
        return "indicators"
    # 基本面/财报意图
    if any(w in q for w in ["财报", "财务", "基本面", "营收", "净利润", "roe", "估值"]):
        return "financials"
    # 新闻意图
    if any(w in q for w in ["新闻", "公告", "消息", "舆情", "资讯", "有什么新闻",
                              "最新消息", "相关新闻"]):
        return "news"
    # 风险意图（迭代3新增）
    if any(w in q for w in ["风险", "回撤", "波动", "仓位", "止损", "止损位",
                              "安全吗", "稳不稳", "风险大", "最大亏损"]):
        return "risk"
    # 综合分析意图
    if any(w in q for w in ["综合", "全面", "详细", "分析报告", "综合看看"]):
        return "analyze"
    # 选股推荐意图
    if any(w in q for w in ["推荐", "荐股", "选股", "选一只", "推荐一只", "有什么好的",
                              "买什么", "哪只", "哪支", "挑选", "筛选", "低估", "便宜",
                              "值得买", "可以买", "潜力", "机会", "被低估"]):
        return "recommend"
    # 偏好设置意图
    if any(w in q for w in ["关注", "添加关注", "加入自选", "收藏"]):
        return "preference"
    # 历史走势意图
    if any(w in q for w in ["历史", "走势", "k线", "过去", "近期"]):
        return "history"
    # 预测意图
    if any(w in q for w in ["预测", "涨跌", "明天", "未来", "forecast"]):
        return "predict"
    # 行情查询意图
    if any(w in q for w in ["行情", "价格", "多少钱", "涨了", "跌了"]):
        return "info"
    # 兜底
    return "default"
