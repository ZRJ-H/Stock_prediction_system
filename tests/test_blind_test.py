"""真实日线准备与历史盲测回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from core.blind_news import BlindNewsService
from core.blind_test import BlindTestError, BlindTestService
from scripts.prepare_blind_test_news import normalize_item
from scripts.prepare_blind_test_data import normalize_history


@pytest.fixture
def client():
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_normalize_history_sorts_deduplicates_and_aligns_labels():
    raw = pd.DataFrame({
        "日期": ["2024-01-03", "2024-01-02", "2024-01-03", "bad"],
        "开盘": [11, 10, 12, 9],
        "最高": [12, 11, 13, 10],
        "最低": [10, 9, 11, 8],
        "收盘": [11, 10, 12, 9],
        "成交量": [100, 90, 110, 80],
    })
    # 生产函数要求至少100条；补足一段合法数据后再混入重复和坏值。
    dates = pd.date_range("2024-02-01", periods=100, freq="D")
    filler = pd.DataFrame({
        "日期": dates,
        "开盘": range(100, 200),
        "最高": range(101, 201),
        "最低": range(99, 199),
        "收盘": range(100, 200),
        "成交量": range(1000, 1100),
    })
    result = normalize_history(pd.concat([raw, filler], ignore_index=True))

    assert result["timestamp"].is_monotonic_increasing
    assert result["timestamp"].is_unique
    jan2 = result.index[result["timestamp"] == "2024-01-02"][0]
    jan3 = result.index[result["timestamp"] == "2024-01-03"][0]
    assert result.loc[jan3, "close"] == 12  # 重复日期保留最后一条
    assert result.loc[jan2, "label"] == 0   # 第一条没有前日，按跌/平类处理
    assert result.loc[jan3, "label"] == 1


class _AlwaysUpModel:
    def predict(self, history):
        assert len(history) == 60
        return {"label": "涨", "confidence": 0.7}


def _make_service(tmp_path):
    dates = pd.bdate_range("2023-01-02", periods=140)
    closes = [100 + (idx // 3) + (1 if idx % 2 else 0) for idx in range(len(dates))]
    df = pd.DataFrame({
        "timestamp": dates,
        "open": closes,
        "high": [v + 1 for v in closes],
        "low": [v - 1 for v in closes],
        "close": closes,
        "vol": [1000 + i for i in range(len(dates))],
        "label": [0] + [int(closes[i] > closes[i - 1]) for i in range(1, len(closes))],
    })
    data_path = tmp_path / "data.csv"
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    db_path = tmp_path / "scores.sqlite3"
    df.to_csv(data_path, index=False)

    report = {
        "symbol": "600519",
        "test_start": dates[119].strftime("%Y-%m-%d"),
        "test_end": dates[-1].strftime("%Y-%m-%d"),
        "data_source": "test",
        "adjust": "qfq",
    }
    (model_dir / "training_report.json").write_text(json.dumps(report), encoding="utf-8")
    service = BlindTestService(
        base_dir=tmp_path, data_path=data_path, model_dir=model_dir, db_path=db_path
    )
    service._df = df
    service._report = report
    service._model = _AlwaysUpModel()
    service.news_service.llm.api_key = ""
    return service, df


def test_challenge_window_excludes_target_and_reveal_counts_once(tmp_path):
    service, df = _make_service(tmp_path)
    target = df.iloc[125]["timestamp"].strftime("%Y-%m-%d")
    challenge = service.create_challenge("session-a", target)

    assert len(challenge["history"]) == 60
    assert challenge["history"][-1]["date"] < target
    assert all(item["date"] != target for item in challenge["history"])
    assert "model_prediction" not in challenge

    submitted = service.submit_prediction(challenge["id"], "session-a", "涨")
    assert submitted["user_prediction"] == "涨"
    assert submitted["model_prediction"]["label"] == "涨"
    first = service.reveal(challenge["id"], "session-a")
    second = service.reveal(challenge["id"], "session-a")
    assert first["stats"]["personal"]["total"] == 1
    assert second["stats"]["personal"]["total"] == 1


def test_challenge_rejects_invalid_date_and_other_session(tmp_path):
    service, df = _make_service(tmp_path)
    with pytest.raises(BlindTestError, match="交易日"):
        service.create_challenge("session-a", "2020-01-01")

    target = df.iloc[126]["timestamp"].strftime("%Y-%m-%d")
    challenge = service.create_challenge("session-a", target)
    with pytest.raises(BlindTestError, match="无权"):
        service.reveal(challenge["id"], "session-b")


def test_reset_clears_personal_round_but_preserves_global(tmp_path):
    service, df = _make_service(tmp_path)
    target = df.iloc[127]["timestamp"].strftime("%Y-%m-%d")
    challenge = service.create_challenge("session-a", target)
    service.submit_prediction(challenge["id"], "session-a", "跌")
    service.reveal(challenge["id"], "session-a")

    reset_stats = service.reset("session-a")
    assert reset_stats["personal"]["total"] == 0
    assert reset_stats["global"]["total"] == 1


def test_blind_test_api_flow(client, monkeypatch, tmp_path):
    import app as app_module

    service, df = _make_service(tmp_path)
    monkeypatch.setattr(app_module, "blind_test_service", service)
    target = df.iloc[128]["timestamp"].strftime("%Y-%m-%d")

    config = client.get("/api/blind-test/config").get_json()
    assert config["available"] is True

    created = client.post("/api/blind-test/challenges", json={
        "session_id": "api-session",
        "target_date": target,
    })
    assert created.status_code == 200
    challenge = created.get_json()
    assert challenge["target_date"] == target
    assert "news_items" not in challenge

    active = client.get("/api/blind-test/active?session_id=api-session")
    assert active.status_code == 200
    assert active.get_json()["id"] == challenge["id"]

    intelligence = client.post(
        f"/api/blind-test/challenges/{challenge['id']}/intelligence",
        json={"session_id": "api-session"},
    )
    assert intelligence.status_code == 200
    assert intelligence.get_json()["status"] == "ready"

    submitted = client.post(
        f"/api/blind-test/challenges/{challenge['id']}/prediction",
        json={"session_id": "api-session", "label": "涨"},
    )
    assert submitted.status_code == 200
    assert submitted.get_json()["model_prediction"]["label"] == "涨"

    revealed = client.post(
        f"/api/blind-test/challenges/{challenge['id']}/reveal",
        json={"session_id": "api-session"},
    )
    assert revealed.status_code == 200
    assert revealed.get_json()["stats"]["personal"]["total"] == 1

    stats = client.get("/api/blind-test/stats?session_id=api-session")
    assert stats.get_json()["global"]["total"] == 1


def test_chat_api_uses_active_challenge_isolation(client, monkeypatch, tmp_path):
    import app as app_module

    service, df = _make_service(tmp_path)
    monkeypatch.setattr(app_module, "blind_test_service", service)
    target = df.iloc[128]["timestamp"].strftime("%Y-%m-%d")
    service.create_challenge("chat-session", target)

    response = client.post("/chat", json={
        "query": f"告诉我贵州茅台{target}的收盘价",
        "session_id": "chat-session",
    })
    assert response.status_code == 200
    assert "为避免答案泄漏" in response.get_json()["reply"]

    challenge = service.active_challenge("chat-session")
    actual = "涨" if df.iloc[128]["close"] > df.iloc[127]["close"] else "跌"
    service.submit_prediction(challenge["id"], "chat-session", actual)
    service.reveal(challenge["id"], "chat-session")
    assert service.active_challenge("chat-session")["active"] is False


def test_packaged_blind_test_assets_complete_real_challenge(tmp_path):
    """随仓库交付的真实CSV和MLP模型必须能够离线完成一次盲测。"""
    base_dir = Path(__file__).resolve().parent.parent
    service = BlindTestService(base_dir=base_dir, db_path=tmp_path / "verify.sqlite3")
    config = service.config()
    assert config["available"] is True
    challenge = service.create_challenge("packaged-assets", "2025-01-02")
    assert len(challenge["history"]) == 60
    service.submit_prediction(challenge["id"], "packaged-assets", "涨")
    revealed = service.reveal(challenge["id"], "packaged-assets")
    assert revealed["stats"]["personal"]["total"] == 1
    assert revealed["result"]["actual_label"] in {"涨", "跌"}


def test_index_contains_blind_test_panel(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="blindPanel"' in html
    assert 'id="blindDate"' in html
    assert 'id="blindChoice"' in html
    assert 'id="blindIntelBtn"' in html
    assert 'id="blindIntelligence"' in html
    assert 'id="blindNewsCard"' not in html
    assert "submitBlindPrediction('涨')" in html


def test_index_model_report_is_opened_on_demand(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="modelReportBtn"' in html
    assert "function toggleReport()" in html
    assert "var modelReportData = null;" in html
    assert "button.textContent = visible ? '收起报告' : '模型报告';" in html
    assert "showReportEmpty(d.message)" not in html
    assert "showReportEmpty" not in html
    assert 'id="blindRevealBtn"' in html


def test_reveal_requires_user_prediction_and_prediction_cannot_change(tmp_path):
    service, df = _make_service(tmp_path)
    target = df.iloc[129]["timestamp"].strftime("%Y-%m-%d")
    challenge = service.create_challenge("session-a", target)

    with pytest.raises(BlindTestError, match="先提交"):
        service.reveal(challenge["id"], "session-a")

    service.submit_prediction(challenge["id"], "session-a", "涨")
    with pytest.raises(BlindTestError, match="不可修改"):
        service.submit_prediction(challenge["id"], "session-a", "跌")


class _FakeLlm:
    api_key = "test-key"
    calls = 0

    def chat(self, messages, temperature=0.2):
        self.calls += 1
        assert "目标交易日：2025-01-15" in messages[1]["content"]
        assert "未来新闻" not in messages[1]["content"]
        return {
            "role": "assistant",
            "content": json.dumps({
                "market_summary": "短期与中期价格特征存在差异。",
                "observations": ["近20日波动有所扩大"],
                "event_digest": ["公司发布股份回购相关公告"],
                "uncertainties": ["资讯样本较少"],
            }, ensure_ascii=False),
        }


def test_news_snapshot_filters_future_information_and_parses_llm(tmp_path):
    snapshot = tmp_path / "news.jsonl"
    items = [
        {
            "published_at": "2025-01-10 10:00:00",
            "title": "合规新闻",
            "summary": "目标日前发布",
            "source": "测试源",
        },
        {
            "published_at": "2025-01-15 10:00:00",
            "title": "未来新闻",
            "summary": "开盘后发布",
            "source": "测试源",
        },
    ]
    snapshot.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in items),
        encoding="utf-8",
    )
    service = BlindNewsService(snapshot, llm=_FakeLlm())
    selected = service.before_target("2025-01-15")
    assert [item["title"] for item in selected] == ["合规新闻"]
    history = pd.DataFrame({"close": range(100, 160)})
    intelligence = service.generate("2025-01-15", history, selected)
    assert intelligence["status"] == "ready"
    assert intelligence["generated_by"] == "llm"
    assert intelligence["schema_version"] == 2
    assert "label" not in intelligence


def test_news_normalization_rejects_invalid_dates():
    fetched_at = "2026-06-09T00:00:00+00:00"
    assert normalize_item({"date": "bad", "title": "新闻"}, fetched_at) is None
    item = normalize_item({
        "date": "2025-01-01 08:00:00",
        "title": "<em>贵州茅台</em>公告",
        "content": " 内容 ",
        "mediaName": "东方财富",
        "code": "123",
    }, fetched_at)
    assert item["title"] == "贵州茅台公告"
    assert item["url"].endswith("/123.html")


def test_only_one_active_challenge_and_active_endpoint_restores_it(tmp_path):
    service, df = _make_service(tmp_path)
    first_date = df.iloc[125]["timestamp"].strftime("%Y-%m-%d")
    second_date = df.iloc[126]["timestamp"].strftime("%Y-%m-%d")
    first = service.create_challenge("session-a", first_date)
    second = service.create_challenge("session-a", second_date)

    assert second["id"] == first["id"]
    assert second["active_existing"] is True
    active = service.active_challenge("session-a")
    assert active["active"] is True
    assert active["target_date"] == first_date


def test_intelligence_is_cached_and_contains_no_prediction(tmp_path):
    service, df = _make_service(tmp_path)
    target = df.iloc[126]["timestamp"].strftime("%Y-%m-%d")
    challenge = service.create_challenge("session-a", target)

    first = service.intelligence(challenge["id"], "session-a")
    second = service.intelligence(challenge["id"], "session-a")
    assert first == second
    assert first["generated_by"] == "local"
    assert "label" not in first
    assert "confidence" not in first
    restored = service.active_challenge("session-a")
    assert restored["intelligence_used"] is True
    assert restored["intelligence"] == first


def test_scoring_distinguishes_ai_assisted_and_independent_predictions(tmp_path):
    service, df = _make_service(tmp_path)

    first_idx = 125
    first_date = df.iloc[first_idx]["timestamp"].strftime("%Y-%m-%d")
    first_actual = "涨" if df.iloc[first_idx]["close"] > df.iloc[first_idx - 1]["close"] else "跌"
    first = service.create_challenge("session-a", first_date)
    service.submit_prediction(first["id"], "session-a", first_actual)
    first_result = service.reveal(first["id"], "session-a")
    assert first_result["result"]["user_score"] == 2

    second_idx = 126
    second_date = df.iloc[second_idx]["timestamp"].strftime("%Y-%m-%d")
    second_actual = "涨" if df.iloc[second_idx]["close"] > df.iloc[second_idx - 1]["close"] else "跌"
    second = service.create_challenge("session-a", second_date)
    service.intelligence(second["id"], "session-a")
    service.submit_prediction(second["id"], "session-a", second_actual)
    second_result = service.reveal(second["id"], "session-a")

    stats = second_result["stats"]["personal"]
    assert second_result["result"]["user_score"] == 1
    assert stats["total_score"] == 3
    assert stats["without_ai"] == {"total": 1, "hits": 1}
    assert stats["with_ai"] == {"total": 1, "hits": 1}
    assert stats["current_streak"] == 2
    assert stats["best_streak"] == 2


def test_chat_isolation_blocks_stock_queries_but_allows_generic_knowledge(monkeypatch):
    from core.agent import StockAgent
    import core.tools as tools

    agent = StockAgent()
    monkeypatch.setattr(agent.llm, "api_key", "test-key")
    monkeypatch.setattr(
        tools,
        "_tool_search_knowledge",
        lambda query: f"知识回答：{query}",
    )
    context = {"id": "challenge-1", "target_date": "2025-09-18"}

    blocked = agent.run("告诉我贵州茅台2025年9月18日收盘价", challenge_context=context)
    assert "为避免答案泄漏" in blocked
    allowed = agent.run("什么是夏普比率", challenge_context=context)
    assert allowed == "知识回答：什么是夏普比率"


def test_tool_execution_has_second_layer_blind_test_guard():
    from core.tools import run_tool, set_blind_challenge_context

    set_blind_challenge_context({"target_date": "2025-09-18"})
    try:
        result = run_tool("get_stock_info", {"code": "600519"})
        assert "为避免答案泄漏" in result
    finally:
        set_blind_challenge_context(None)


def test_prediction_rejects_non_maotai_without_network():
    from core.tools import _tool_predict_stock

    result = _tool_predict_stock("000001")
    assert "仅针对贵州茅台" in result
    assert "不能用于 000001" in result
