"""
最小回归测试：意图识别 / 关键词提取 / 偏好隔离 / session 安全 / API 端点 / RAG 降级
"""

import json
import tempfile
from pathlib import Path

import pytest

from core.agent import _classify_intent, _extract_code, _extract_keyword, _resolve_code
from core.memory import (
    MEMORY_DIR,
    UserPreferences,
    load_preferences,
    save_preferences,
    update_preference,
    validate_session_id,
)


# ═════════════════════════════════════════════════════════════
# 意图识别
# ═════════════════════════════════════════════════════════════

@pytest.mark.parametrize("query,expected", [
    ("搜索平安银行", "search"),
    ("对比 600519 和 000001", "compare"),
    ("什么是金叉死叉", "knowledge"),
    ("分析 000001 的技术指标", "indicators"),
    ("预测 600519 涨跌", "predict"),
    ("推荐一只短线股", "recommend"),
    ("关注 600519", "preference"),
    ("综合分析贵州茅台", "analyze"),
    ("茅台最近有什么新闻", "news"),
    ("000001 近60天走势", "history"),
    ("评估 600519 的风险", "risk"),
    ("查询 600519 的行情", "info"),
    ("今天天气怎么样", "knowledge"),  # "怎么" 命中知识意图关键词
    ("随便看看", "default"),           # 完全无匹配 → 兜底
])
def test_intent_classification(query, expected):
    assert _classify_intent(query) == expected, f"query={query!r}"


# ═════════════════════════════════════════════════════════════
# 代码提取
# ═════════════════════════════════════════════════════════════

def test_extract_code():
    assert _extract_code("查询 600519 的行情") == "600519"
    assert _extract_code("000001 近30天走势") == "000001"
    assert _extract_code("分析贵州茅台") is None
    assert _extract_code("推荐一只股票") is None


# ═════════════════════════════════════════════════════════════
# 关键词提取
# ═════════════════════════════════════════════════════════════

def test_extract_keyword():
    assert _extract_keyword("搜索平安银行") == "平安银行"
    assert _extract_keyword("分析贵州茅台的技术指标") == "贵州茅台"
    # "行情"是描述性停用词，_extract_keyword 过滤后返回 None
    assert _extract_keyword("查询 600519 的行情") is None
    # 无股名时返回剩余中文文本（过滤能力有限，规则模式已知限制）
    result = _extract_keyword("推荐一只股票")
    assert result and "推荐" in result


# ═════════════════════════════════════════════════════════════
# 代码解析
# ═════════════════════════════════════════════════════════════

def test_resolve_code():
    assert _resolve_code("平安银行") == "000001"
    assert _resolve_code("贵州茅台") == "600519"
    # 模糊匹配结果 >1 时不返回
    assert _resolve_code("银行") is None


# ═════════════════════════════════════════════════════════════
# 偏好按 session_id 隔离
# ═════════════════════════════════════════════════════════════

def test_preferences_isolated_by_session(monkeypatch):
    """验证不同 session_id 偏好互不污染。"""
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr("core.memory.MEMORY_DIR", tmp)

    sid_a = "test-session-a-001"
    sid_b = "test-session-b-002"

    # A 关注平安银行
    update_preference(sid_a, "watchlist", "000001")
    # B 关注茅台
    update_preference(sid_b, "watchlist", "600519")

    prefs_a = load_preferences(sid_a)
    prefs_b = load_preferences(sid_b)

    assert prefs_a.watchlist == ["000001"], f"A 应为 [000001]，实际 {prefs_a.watchlist}"
    assert prefs_b.watchlist == ["600519"], f"B 应为 [600519]，实际 {prefs_b.watchlist}"
    assert prefs_a.session_id == sid_a
    assert prefs_b.session_id == sid_b

    # 清理
    for f in tmp.glob("*.json"):
        f.unlink()
    tmp.rmdir()


def test_preferences_invalid_key():
    result = update_preference("test-xxx", "bad_key", "value")
    assert "不支持" in result


def test_preferences_invalid_code():
    result = update_preference("test-xxx", "watchlist", "abc")
    assert "无效的股票代码" in result


# ═════════════════════════════════════════════════════════════
# session_id 安全校验
# ═════════════════════════════════════════════════════════════

def test_validate_session_id_valid():
    """合法 session_id 通过校验。"""
    assert validate_session_id("abc123") == "abc123"
    assert validate_session_id("test-session-001") == "test-session-001"
    assert validate_session_id("user_abc") == "user_abc"
    assert validate_session_id("A" * 80) == "A" * 80


@pytest.mark.parametrize("sid", [
    "",           # 空字符串
    "../etc",     # 路径穿越
    "a/b",        # 含斜杠
    "a\\b",       # 含反斜杠
    "a.b",        # 含点号
    "a b",        # 含空格
    "a\tb",       # 含制表符
    "a" * 81,     # 超长
    "<script>",   # XSS 尝试
    "a;rm -rf /", # 命令注入
])
def test_validate_session_id_rejects_invalid(sid):
    """非法 session_id 必须被拒绝。"""
    with pytest.raises(ValueError):
        validate_session_id(sid)


def test_save_preferences_rejects_path_traversal(monkeypatch):
    """路径穿越 session_id 在保存偏好时被拒绝。"""
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr("core.memory.MEMORY_DIR", tmp)
    # 清理
    try:
        prefs = UserPreferences(session_id="../etc", watchlist=["000001"])
        with pytest.raises(ValueError):
            save_preferences(prefs)
    finally:
        for f in tmp.glob("*.json"):
            f.unlink()
        tmp.rmdir()


def test_update_preference_rejects_invalid_session():
    """update_preference 拒绝非法 session_id。"""
    result = update_preference("a" * 81, "watchlist", "000001")
    assert "无效的 session_id" in result


# ═════════════════════════════════════════════════════════════
# Flask API 集成测试
# ═════════════════════════════════════════════════════════════

@pytest.fixture
def client():
    """创建 Flask 测试客户端。"""
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_chat_empty_query(client):
    """空查询返回提示。"""
    resp = client.post("/chat", json={"query": ""})
    assert resp.status_code == 200
    assert "请输入" in resp.get_json()["reply"]


def test_chat_valid_query(client):
    """正常查询返回回复。"""
    resp = client.post("/chat", json={"query": "搜索平安银行"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "reply" in data
    assert len(data["reply"]) > 0


def test_chat_invalid_session_returns_400(client):
    """/chat 非法 session_id 返回 400。"""
    resp = client.post("/chat", json={
        "query": "搜索平安银行",
        "session_id": "../etc",
    })
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_chat_without_session_still_works(client):
    """/chat 不带 session_id 正常返回 200。"""
    resp = client.post("/chat", json={"query": "搜索平安银行"})
    assert resp.status_code == 200
    assert "reply" in resp.get_json()


def test_memory_get_missing_session(client):
    """GET /memory 缺少 session_id 返回 400。"""
    resp = client.get("/memory")
    assert resp.status_code == 400
    assert "缺少" in resp.get_json()["error"]


def test_memory_get_invalid_session(client):
    """GET /memory 非法 session_id 返回 400。"""
    resp = client.get("/memory?session_id=../etc")
    assert resp.status_code == 400


def test_memory_post_missing_params(client):
    """POST /memory 缺少参数返回 400。"""
    resp = client.post("/memory", json={})
    assert resp.status_code == 400


def test_memory_post_invalid_session(client):
    """POST /memory 非法 session_id 返回 400。"""
    resp = client.post("/memory", json={
        "session_id": "<script>",
        "key": "watchlist",
        "value": "000001",
    })
    assert resp.status_code == 400


def test_health_returns_200(client):
    """/health 快速返回，不触发 RAG 初始化。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "model_loaded" in data
    assert "llm_available" in data
    assert "rag_ready" in data


def test_health_is_lightweight(client):
    """/health 不依赖 RAGService 实例化（轻量级检查）。"""
    import time
    start = time.time()
    resp = client.get("/health")
    elapsed = time.time() - start
    assert resp.status_code == 200
    # 轻量级健康检查应在 100ms 内完成（仅检查文件是否存在）
    assert elapsed < 1.0, f"/health 耗时 {elapsed:.2f}s，可能触发了重型初始化"


# ═════════════════════════════════════════════════════════════
# RAG 降级测试
# ═════════════════════════════════════════════════════════════

def test_rag_search_when_not_initialized():
    """RAG 未初始化时搜索返回明确提示。"""
    from core.rag_service import RAGService
    rag = RAGService()
    assert not rag.is_ready()
    result = rag.search_formatted("什么是金叉")
    assert "未找到" in result


def test_rag_initialize_failure_does_not_raise():
    """RAG 初始化失败不抛异常。"""
    from core.rag_service import RAGService
    rag = RAGService()
    # 即使知识库目录不存在，initialize 也不应抛异常
    result = rag.initialize(force_rebuild=False)
    # 返回 False 表示无法初始化（如知识库目录为空），但不抛异常
    assert isinstance(result, bool)


def test_search_knowledge_reports_unavailable_when_rag_init_fails(monkeypatch):
    """RAG 初始化失败时，_tool_search_knowledge 返回明确不可用提示。"""
    def fake_init_fails(self, force_rebuild=False):
        return False

    monkeypatch.setattr("core.rag_service.RAGService.initialize", fake_init_fails)
    from core.tools import _tool_search_knowledge
    result = _tool_search_knowledge("什么是金叉")
    assert "不可用" in result or "尚未初始化" in result


# ═════════════════════════════════════════════════════════════
# 股票历史K线 API 测试
# ═════════════════════════════════════════════════════════════

def test_stock_history_api_returns_200(client, monkeypatch):
    """GET /api/stock/<code>/history 正常返回 K 线数据。"""
    from core.market_data import KlineBar
    mock_bars = [
        KlineBar(date="2026-01-02", open=100, high=105, low=98, close=102, volume=10000),
        KlineBar(date="2026-01-03", open=102, high=108, low=101, close=107, volume=12000),
    ]
    monkeypatch.setattr("core.market_data.get_daily_kline", lambda code, days=90: mock_bars)

    resp = client.get("/api/stock/600519/history?days=90")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["code"] == "600519"
    assert data["days"] == 90
    assert len(data["items"]) == 2
    assert data["items"][0]["close"] == 102
    assert data["items"][0]["volume"] == 10000


def test_stock_history_api_invalid_code_returns_400(client):
    """非法股票代码返回 400。"""
    # 含字母
    resp = client.get("/api/stock/abc123/history")
    assert resp.status_code == 400
    assert "error" in resp.get_json()

    # 长度不足（5位）
    resp = client.get("/api/stock/12345/history")
    assert resp.status_code == 400

    # 含中文字符
    resp = client.get("/api/stock/60051九/history")
    assert resp.status_code == 400


def test_stock_history_api_no_data_returns_503(client, monkeypatch):
    """K 线数据为空时返回 503。"""
    monkeypatch.setattr("core.market_data.get_daily_kline", lambda code, days=90: [])

    resp = client.get("/api/stock/600519/history")
    assert resp.status_code == 503
    data = resp.get_json()
    assert "error" in data
    assert "不可用" in data["error"]


def test_stock_history_api_respects_days_param(client, monkeypatch):
    """days 参数正确传递给 get_daily_kline。"""
    captured_days = []

    def fake_kline(code, days=90):
        captured_days.append(days)
        from core.market_data import KlineBar
        return [KlineBar(date="2026-01-02", open=100, high=105, low=98, close=102, volume=10000)]

    monkeypatch.setattr("core.market_data.get_daily_kline", fake_kline)

    resp = client.get("/api/stock/000001/history?days=30")
    assert resp.status_code == 200
    assert captured_days[0] == 30


# ═════════════════════════════════════════════════════════════
# E2：综合分析报告结构化测试
# ═════════════════════════════════════════════════════════════

def _make_fake_report(skill_name, title, score, summary, signal=""):
    """构建一个受控的 SkillReport，用于 mock 子模块输出。"""
    from core.skills.base import ReportSection, SkillReport
    return SkillReport(
        skill_name=skill_name,
        title=title,
        sections=[ReportSection(heading="数据", content=f"{title}的模拟数据。", signal=signal)],
        summary=summary,
        score=score,
    )


def test_comprehensive_analysis_contains_fixed_sections(monkeypatch):
    """综合分析输出包含固定章节：结论/技术面/基本面/风险/舆情/操作建议/免责声明。"""
    from core.market_data import StockQuote
    from core.skills.comprehensive import ComprehensiveSkill
    from core.skills import technical, fundamental, risk, news

    # mock 实时行情
    fake_quote = StockQuote(
        code="600519", name="贵州茅台", market="SH",
        price=1800, open=1790, high=1810, low=1785, pre_close=1795,
        change_pct=0.28, change_amount=5.0, volume=30000, amount=54000000,
        turnover=0.15, pe=35.0, pb=12.0, total_mv=22500, time="2026-06-02 15:00"
    )
    monkeypatch.setattr("core.market_data.get_realtime_quote", lambda code: fake_quote)

    # mock 四个子 Skill 的 execute 方法
    monkeypatch.setattr(technical.TechnicalSkill, "execute",
        lambda self, code: _make_fake_report("technical", "技术分析", 70, "技术面偏多。", "bullish"))
    monkeypatch.setattr(fundamental.FundamentalSkill, "execute",
        lambda self, code: _make_fake_report("fundamental", "基本面", 60, "基本面中性。", "neutral"))
    monkeypatch.setattr(risk.RiskSkill, "execute",
        lambda self, code: _make_fake_report("risk", "风险", 55, "风险可控。", "neutral"))
    monkeypatch.setattr(news.NewsSkill, "execute",
        lambda self, code: _make_fake_report("news", "舆情", 65, "舆情偏正面。", "bullish"))

    report = ComprehensiveSkill().execute("600519")
    text = report.format()

    # 验证固定 7 章节存在且顺序正确
    headings = ["【结论】", "【技术面】", "【基本面】", "【风险】", "【舆情】", "【操作建议】", "【免责声明】"]
    positions = {}
    for h in headings:
        idx = text.find(h)
        assert idx >= 0, f"缺少章节：{h}"
        positions[h] = idx

    # 严格顺序：结论 < 技术面 < 基本面 < 风险 < 舆情 < 操作建议 < 免责声明
    for i in range(len(headings) - 1):
        assert positions[headings[i]] < positions[headings[i + 1]], \
            f"章节顺序错误：{headings[i]} 应在 {headings[i+1]} 之前"

    # 综合评分已写入【结论】，不应在【免责声明】之后单独出现
    assert ">> 综合评分" not in text
    # 免责声明作为章节包含完整文案
    assert "不构成投资建议" in text
    # 标题含股票名
    assert "贵州茅台" in text
    assert "600519" in text


def test_comprehensive_analysis_tolerates_module_failure(monkeypatch):
    """子模块失败时综合分析仍返回完整报告，含降级提示。"""
    from core.market_data import StockQuote
    from core.skills.comprehensive import ComprehensiveSkill
    from core.skills import technical, fundamental, risk, news

    fake_quote = StockQuote(
        code="000001", name="平安银行", market="SZ",
        price=12.5, open=12.3, high=12.6, low=12.2, pre_close=12.4,
        change_pct=0.81, change_amount=0.1, volume=500000, amount=6250000,
        turnover=0.5, pe=6.0, pb=0.8, total_mv=2500, time="2026-06-02 15:00"
    )
    monkeypatch.setattr("core.market_data.get_realtime_quote", lambda code: fake_quote)

    # 基本面正常，技术面和风险抛异常
    monkeypatch.setattr(technical.TechnicalSkill, "execute",
        lambda self, code: (_ for _ in ()).throw(RuntimeError("K线数据不可用")))
    monkeypatch.setattr(fundamental.FundamentalSkill, "execute",
        lambda self, code: _make_fake_report("fundamental", "基本面", 60, "基本面正常。", "neutral"))
    monkeypatch.setattr(risk.RiskSkill, "execute",
        lambda self, code: (_ for _ in ()).throw(RuntimeError("波动率计算失败")))
    monkeypatch.setattr(news.NewsSkill, "execute",
        lambda self, code: _make_fake_report("news", "舆情", 50, "舆情中性。", "neutral"))

    report = ComprehensiveSkill().execute("000001")
    text = report.format()

    # 仍包含各章节
    assert "【技术面】" in text
    assert "【基本面】" in text
    assert "【风险】" in text
    assert "【舆情】" in text
    # 失败模块有降级提示
    assert "跳过" in text
    # 免责声明仍在
    assert "不构成投资建议" in text
    # 综合结论中有数据不可用提示
    assert "不可用" in text


def test_comprehensive_analysis_includes_disclaimer(monkeypatch):
    """综合分析输出包含【免责声明】作为独立章节（最后一个章节）。"""
    from core.market_data import StockQuote
    from core.skills.comprehensive import ComprehensiveSkill
    from core.skills import technical, fundamental, risk, news

    fake_quote = StockQuote(
        code="600519", name="贵州茅台", market="SH",
        price=1800, open=1790, high=1810, low=1785, pre_close=1795,
        change_pct=0.28, change_amount=5.0, volume=30000, amount=54000000,
        turnover=0.15, pe=35.0, pb=12.0, total_mv=22500, time="2026-06-02 15:00"
    )
    monkeypatch.setattr("core.market_data.get_realtime_quote", lambda code: fake_quote)

    monkeypatch.setattr(technical.TechnicalSkill, "execute",
        lambda self, code: _make_fake_report("technical", "技术", 50, "中", "neutral"))
    monkeypatch.setattr(fundamental.FundamentalSkill, "execute",
        lambda self, code: _make_fake_report("fundamental", "基本面", 50, "中", "neutral"))
    monkeypatch.setattr(risk.RiskSkill, "execute",
        lambda self, code: _make_fake_report("risk", "风险", 50, "中", "neutral"))
    monkeypatch.setattr(news.NewsSkill, "execute",
        lambda self, code: _make_fake_report("news", "舆情", 50, "中", "neutral"))

    report = ComprehensiveSkill().execute("600519")
    text = report.format()

    # 【免责声明】是独立章节
    assert "【免责声明】" in text
    assert "不构成投资建议" in text
    assert "投资需谨慎" in text
    # 【免责声明】是最后一个章节
    disclaimer_pos = text.rfind("【免责声明】")
    suggestions_pos = text.find("【操作建议】")
    assert suggestions_pos < disclaimer_pos, "【免责声明】应在【操作建议】之后，作为最终章节"


def test_comprehensive_analysis_deterministic_advice_not_present(monkeypatch):
    """操作建议不包含确定性买卖指令。"""
    from core.market_data import StockQuote
    from core.skills.comprehensive import ComprehensiveSkill
    from core.skills import technical, fundamental, risk, news

    fake_quote = StockQuote(
        code="600519", name="贵州茅台", market="SH",
        price=1800, open=1790, high=1810, low=1785, pre_close=1795,
        change_pct=0.28, change_amount=5.0, volume=30000, amount=54000000,
        turnover=0.15, pe=35.0, pb=12.0, total_mv=22500, time="2026-06-02 15:00"
    )
    monkeypatch.setattr("core.market_data.get_realtime_quote", lambda code: fake_quote)

    # 全部偏高
    monkeypatch.setattr(technical.TechnicalSkill, "execute",
        lambda self, code: _make_fake_report("t", "技术", 85, "强", "bullish"))
    monkeypatch.setattr(fundamental.FundamentalSkill, "execute",
        lambda self, code: _make_fake_report("f", "基本面", 80, "好", "bullish"))
    monkeypatch.setattr(risk.RiskSkill, "execute",
        lambda self, code: _make_fake_report("r", "风险", 75, "低", "bullish"))
    monkeypatch.setattr(news.NewsSkill, "execute",
        lambda self, code: _make_fake_report("n", "舆情", 80, "好", "bullish"))

    report = ComprehensiveSkill().execute("600519")
    text = report.format()

    # 禁止确定性买卖指令
    forbidden = ["建议买入", "建议卖出", "建议全仓", "明天一定涨", "明天一定跌"]
    for phrase in forbidden:
        assert phrase not in text, f"综合分析不应包含 '{phrase}'"


# ═════════════════════════════════════════════════════════════
# E3：LLM 智能模式增强测试
# ═════════════════════════════════════════════════════════════

def test_llm_failure_falls_back_to_rule_mode(client, monkeypatch):
    """LLM 返回 None 时自动降级规则模式，仍能正常回复。"""
    from app import agent

    monkeypatch.setattr(agent.llm, "api_key", "fake-key-for-test")
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **kw: None)

    resp = client.post("/chat", json={"query": "搜索平安银行"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "reply" in data
    assert "000001" in data["reply"]  # 规则模式仍能找到平安银行


def test_llm_tool_call_flow(client, monkeypatch):
    """LLM 先返回 tool_call 再返回文本：验证工具调用结果进入最终回复。"""
    from app import agent

    call_count = [0]

    def fake_chat(messages, tools=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "role": "assistant",
                "tool_calls": [{
                    "name": "search_stock",
                    "arguments": {"keyword": "平安银行"},
                }],
            }
        else:
            return {"role": "assistant", "content": "根据搜索结果，平安银行(000001)是一只银行股，建议关注。"}

    monkeypatch.setattr(agent.llm, "api_key", "fake-key-for-test")
    monkeypatch.setattr(agent.llm, "chat", fake_chat)

    resp = client.post("/chat", json={"query": "帮我看看平安银行"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "reply" in data
    assert "000001" in data["reply"]
    assert call_count[0] == 2  # 调用了两轮 LLM


def test_llm_not_entered_without_api_key(client, monkeypatch):
    """无 API key 时不进入 LLM 模式，使用规则引擎。"""
    from app import agent

    monkeypatch.setattr(agent.llm, "api_key", "")
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **kw: None)

    resp = client.post("/chat", json={"query": "搜索贵州茅台"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "reply" in data
    assert "600519" in data["reply"]  # 规则模式正常工作


def test_health_includes_llm_meta_fields(client, monkeypatch):
    """/health 返回 LLM 元信息字段（不真实请求 LLM）。"""
    from app import agent

    monkeypatch.setattr(agent.llm, "api_key", "sk-test-mock")
    monkeypatch.setattr(agent.llm, "base_url", "https://api.deepseek.com/v1")
    monkeypatch.setattr(agent.llm, "model_name", "deepseek-chat")

    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["llm_available"] is True
    assert data["llm_base_url"] == "https://api.deepseek.com/v1"
    assert data["llm_model"] == "deepseek-chat"


def test_health_llm_fields_none_without_api_key(client, monkeypatch):
    """无 API key 时 /health 的 llm_base_url 和 llm_model 返回 None。"""
    from app import agent

    monkeypatch.setattr(agent.llm, "api_key", "")
    monkeypatch.setattr(agent.llm, "base_url", "https://api.openai.com/v1")
    monkeypatch.setattr(agent.llm, "model_name", "gpt-4o-mini")

    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["llm_available"] is False
    assert data["llm_base_url"] is None
    assert data["llm_model"] is None
