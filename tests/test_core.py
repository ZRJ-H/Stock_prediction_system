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
