"""Paper trading database and engine tests."""

from __future__ import annotations

import pytest

from core.market_data import StockQuote
from core.paper_config import PaperTradingConfig, SignalRule
from core.paper_trading import PaperTradingService


def _rules() -> list[SignalRule]:
    return [
        SignalRule("STRONG_BUY", "BUY", min_score=75, cash_ratio=0.3),
        SignalRule("BUY", "BUY", min_score=60, max_score=75, cash_ratio=0.15),
        SignalRule("HOLD", "HOLD", min_score=45, max_score=60, min_inclusive=False),
        SignalRule(
            "SELL",
            "SELL",
            min_score=30,
            max_score=45,
            min_inclusive=False,
            max_inclusive=True,
            sell_ratio=0.5,
        ),
        SignalRule("STRONG_SELL", "SELL", max_score=30, max_inclusive=True, sell_ratio=1.0),
    ]


def _config(initial_cash=100000.0, commission_rate=0.0, slippage_rate=0.0) -> PaperTradingConfig:
    return PaperTradingConfig(
        strategy_version="test-v1",
        initial_cash=initial_cash,
        stock_list=["600519", "000001"],
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        max_position_ratio=1.0,
        signals=_rules(),
    )


def _quote(code="600519", price=100.0, name="Test Stock") -> StockQuote:
    return StockQuote(
        code=code,
        name=name,
        market="SH" if code.startswith("6") else "SZ",
        price=price,
        open=price,
        high=price,
        low=price,
        pre_close=price,
        change_pct=0.0,
        change_amount=0.0,
        volume=10000,
        amount=price * 10000,
        turnover=0.1,
        pe=10.0,
        pb=1.0,
        total_mv=100.0,
        time="2026-06-25 15:00:00",
    )


def _service(tmp_path, config=None, quotes=None) -> PaperTradingService:
    quote_map = quotes or {"600519": _quote("600519", 100.0)}

    def quote_provider(code):
        value = quote_map.get(code)
        if isinstance(value, list):
            return value.pop(0) if value else None
        return value

    return PaperTradingService(
        base_dir=tmp_path,
        db_path=tmp_path / "paper.sqlite3",
        config=config or _config(),
        quote_provider=quote_provider,
    )


def test_score_boundaries_match_default_strategy():
    config = _config()

    assert config.signal_for_score(75).name == "STRONG_BUY"
    assert config.signal_for_score(60).name == "BUY"
    assert config.signal_for_score(59.9).name == "HOLD"
    assert config.signal_for_score(45.1).name == "HOLD"
    assert config.signal_for_score(45).name == "SELL"
    assert config.signal_for_score(30.1).name == "SELL"
    assert config.signal_for_score(30).name == "STRONG_SELL"


def test_insufficient_cash_cannot_buy(tmp_path):
    service = _service(tmp_path, config=_config(initial_cash=100.0), quotes={"600519": _quote(price=1000.0)})

    result = service.run_scores({"600519": 80}, trading_date="2026-06-25")

    item = result["results"][0]
    assert item["status"] == "skipped"
    assert item["reason"] == "insufficient_cash_or_position_limit"
    assert service.account_summary()["cash"] == 100.0
    assert service.positions() == []


def test_insufficient_position_cannot_sell(tmp_path):
    service = _service(tmp_path)

    result = service.run_scores({"600519": 20}, trading_date="2026-06-25")

    item = result["results"][0]
    assert item["status"] == "skipped"
    assert item["reason"] == "insufficient_position"
    assert service.account_summary()["cash"] == 100000.0


def test_buy_updates_cash_position_and_daily_equity(tmp_path):
    service = _service(tmp_path, quotes={"600519": _quote(price=100.0)})

    result = service.run_scores({"600519": 80}, trading_date="2026-06-25")

    item = result["results"][0]
    assert item["status"] == "filled"
    assert item["action"] == "BUY"
    assert item["quantity"] == 300
    account = service.account_summary()
    assert account["cash"] == pytest.approx(70000.0)
    assert account["position_value"] == pytest.approx(30000.0)
    assert account["total_assets"] == pytest.approx(100000.0)
    positions = service.positions()
    assert len(positions) == 1
    assert positions[0]["stock_code"] == "600519"
    assert positions[0]["quantity"] == 300
    assert positions[0]["avg_cost"] == pytest.approx(100.0)
    equity = service.equity_curve()
    assert len(equity) == 1
    assert equity[0]["total_assets"] == pytest.approx(100000.0)


def test_sell_updates_cash_position_and_realized_pnl(tmp_path):
    quotes = {"600519": [_quote(price=100.0), _quote(price=110.0)]}
    service = _service(tmp_path, quotes=quotes)
    service.run_scores({"600519": 80}, trading_date="2026-06-25")

    result = service.run_scores({"600519": 20}, trading_date="2026-06-26")

    item = result["results"][0]
    assert item["status"] == "filled"
    assert item["action"] == "SELL"
    assert item["quantity"] == 300
    assert service.positions() == []
    account = service.account_summary()
    assert account["cash"] == pytest.approx(103000.0)
    assert account["realized_pnl"] == pytest.approx(3000.0)
    assert account["total_assets"] == pytest.approx(103000.0)


def test_fee_and_slippage_are_applied_to_buy(tmp_path):
    config = _config(commission_rate=0.001, slippage_rate=0.01)
    service = _service(tmp_path, config=config, quotes={"600519": _quote(price=100.0)})

    result = service.run_scores({"600519": 80}, trading_date="2026-06-25")

    item = result["results"][0]
    assert item["status"] == "filled"
    assert item["price"] == pytest.approx(101.0)
    expected_qty = int(30000 / (101.0 * 1.001))
    expected_fee = expected_qty * 101.0 * 0.001
    assert item["quantity"] == expected_qty
    assert item["fee"] == pytest.approx(expected_fee)
    assert item["slippage"] == pytest.approx(expected_qty * 1.0)
    account = service.account_summary()
    assert account["cash"] == pytest.approx(100000 - expected_qty * 101.0 - expected_fee)


def test_duplicate_task_run_is_blocked(tmp_path):
    service = _service(tmp_path)
    first = service.run_scores({"600519": 80}, trading_date="2026-06-25")

    second = service.run_scores({"600519": 80}, trading_date="2026-06-25")

    assert first["results"][0]["status"] == "filled"
    assert second["results"][0]["status"] == "skipped"
    assert second["results"][0]["reason"] == "duplicate_run"
    assert len(service.orders()) == 1
    assert len(service.task_runs()) == 1


def test_missing_quote_is_skipped_and_records_reason(tmp_path):
    service = _service(tmp_path, quotes={"600519": None})

    result = service.run_scores({"600519": 80}, trading_date="2026-06-25")

    item = result["results"][0]
    assert item["status"] == "skipped"
    assert item["reason"] == "quote_unavailable"
    assert item["price"] is None
    assert service.orders()[0]["reason"] == "quote_unavailable"
    assert service.task_runs() == []
    assert service.account_summary()["cash"] == pytest.approx(100000.0)


def test_hold_signal_records_no_trade_order(tmp_path):
    service = _service(tmp_path)

    result = service.run_scores({"600519": 50}, trading_date="2026-06-25")

    item = result["results"][0]
    assert item["status"] == "skipped"
    assert item["reason"] == "hold_signal"
    assert item["action"] == "HOLD"
    assert service.orders()[0]["signal"] == "HOLD"
    assert service.positions() == []


def test_dry_run_has_no_database_side_effects(tmp_path):
    service = _service(tmp_path)

    result = service.run_scores({"600519": 80}, trading_date="2026-06-25", dry_run=True)

    assert result["results"][0]["status"] == "dry_run"
    assert result["account"] is None
    assert not service.db_path.exists()
    assert service.orders() == []
    assert service.positions() == []
    assert service.task_runs() == []

def test_invalid_score_is_rejected_before_signal_selection(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="Score must be"):
        service.run_scores({"600519": float("nan")}, trading_date="2026-06-25")
    with pytest.raises(ValueError, match="Score must be"):
        service.run_scores({"600519": 101}, trading_date="2026-06-25")


def test_quote_failure_can_retry_same_day_when_quote_recovers(tmp_path):
    quotes = {"600519": [None, _quote(price=100.0)]}
    service = _service(tmp_path, quotes=quotes)

    first = service.run_scores({"600519": 80}, trading_date="2026-06-25")
    second = service.run_scores({"600519": 80}, trading_date="2026-06-25")

    assert first["results"][0]["reason"] == "quote_unavailable"
    assert second["results"][0]["status"] == "filled"
    assert len(service.task_runs()) == 1


def test_existing_position_is_repriced_before_buy_limit(tmp_path):
    config = _config(initial_cash=100000.0)
    config = PaperTradingConfig(
        strategy_version=config.strategy_version,
        initial_cash=config.initial_cash,
        stock_list=config.stock_list,
        commission_rate=config.commission_rate,
        slippage_rate=config.slippage_rate,
        max_position_ratio=0.45,
        signals=config.signals,
    )
    quotes = {"600519": [_quote(price=100.0), _quote(price=200.0)]}
    service = _service(tmp_path, config=config, quotes=quotes)
    service.run_scores({"600519": 80}, trading_date="2026-06-25")

    result = service.run_scores({"600519": 80}, trading_date="2026-06-26")

    item = result["results"][0]
    assert item["status"] == "skipped"
    assert item["reason"] == "insufficient_cash_or_position_limit"
    assert service.positions()[0]["latest_price"] == pytest.approx(200.0)
    assert service.positions()[0]["market_value"] == pytest.approx(60000.0)


def test_account_summary_includes_timestamps(tmp_path):
    service = _service(tmp_path)

    account = service.account_summary()

    assert account["created_at"]
    assert account["updated_at"]


def test_run_scores_validates_all_scores_before_writing(tmp_path):
    service = _service(
        tmp_path,
        quotes={
            "600519": _quote("600519", 100.0),
            "000001": _quote("000001", 10.0),
        },
    )

    with pytest.raises(ValueError, match="Score must be"):
        service.run_scores({"600519": 80, "000001": 101}, trading_date="2026-06-25")

    assert not service.db_path.exists()
