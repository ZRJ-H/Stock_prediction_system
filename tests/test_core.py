"""
最小回归测试：意图识别 / 关键词提取 / 偏好按 session_id 隔离
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
