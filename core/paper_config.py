"""Paper trading configuration loading."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "paper_trading.json"
_STOCK_CODE_RE = re.compile(r"^\d{6}\Z")


@dataclass(frozen=True)
class SignalRule:
    """Configurable score-to-action mapping."""

    name: str
    action: str
    min_score: float | None = None
    max_score: float | None = None
    min_inclusive: bool = True
    max_inclusive: bool = False
    cash_ratio: float = 0.0
    sell_ratio: float = 0.0

    def matches(self, score: float) -> bool:
        if self.min_score is not None:
            if self.min_inclusive and score < self.min_score:
                return False
            if not self.min_inclusive and score <= self.min_score:
                return False
        if self.max_score is not None:
            if self.max_inclusive and score > self.max_score:
                return False
            if not self.max_inclusive and score >= self.max_score:
                return False
        return True


@dataclass(frozen=True)
class PaperTradingConfig:
    """Configuration for the deterministic paper-trading engine."""

    strategy_version: str = "paper-v1"
    initial_cash: float = 100000.0
    stock_list: list[str] = field(default_factory=lambda: ["600519", "000001"])
    commission_rate: float = 0.0003
    slippage_rate: float = 0.001
    max_position_ratio: float = 0.3
    signals: list[SignalRule] = field(default_factory=list)

    def signal_for_score(self, score: float) -> SignalRule:
        for rule in self.signals:
            if rule.matches(score):
                return rule
        raise ValueError(f"No paper trading signal rule matches score {score}")


def _validate_ratio(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")


def _validate_stock_list(codes: list[str]) -> list[str]:
    normalized = []
    for code in codes:
        value = str(code).strip().zfill(6)
        if not _STOCK_CODE_RE.match(value):
            raise ValueError(f"Invalid stock code: {code}")
        normalized.append(value)
    if not normalized:
        raise ValueError("Paper trading stock list cannot be empty")
    return normalized


def _rule_from_dict(data: dict[str, Any]) -> SignalRule:
    rule = SignalRule(
        name=str(data["name"]).strip(),
        action=str(data["action"]).strip().upper(),
        min_score=None if data.get("min_score") is None else float(data["min_score"]),
        max_score=None if data.get("max_score") is None else float(data["max_score"]),
        min_inclusive=bool(data.get("min_inclusive", True)),
        max_inclusive=bool(data.get("max_inclusive", False)),
        cash_ratio=float(data.get("cash_ratio", 0.0)),
        sell_ratio=float(data.get("sell_ratio", 0.0)),
    )
    if rule.action not in {"BUY", "SELL", "HOLD"}:
        raise ValueError(f"Unsupported paper trading action: {rule.action}")
    _validate_ratio("cash_ratio", rule.cash_ratio)
    _validate_ratio("sell_ratio", rule.sell_ratio)
    return rule


def load_paper_trading_config(path: str | Path = DEFAULT_CONFIG_PATH) -> PaperTradingConfig:
    """Load paper trading config from JSON."""

    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Paper trading config does not exist: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Paper trading config is not valid JSON: {config_path}") from exc

    signals = [_rule_from_dict(item) for item in data.get("signals", [])]
    if not signals:
        raise ValueError("Paper trading config requires signals")

    config = PaperTradingConfig(
        strategy_version=str(data.get("strategy_version", "paper-v1")).strip() or "paper-v1",
        initial_cash=float(data.get("initial_cash", 100000.0)),
        stock_list=_validate_stock_list(list(data.get("stock_list", []))),
        commission_rate=float(data.get("commission_rate", 0.0003)),
        slippage_rate=float(data.get("slippage_rate", 0.001)),
        max_position_ratio=float(data.get("max_position_ratio", 0.3)),
        signals=signals,
    )
    if config.initial_cash <= 0:
        raise ValueError("initial_cash must be greater than 0")
    _validate_ratio("commission_rate", config.commission_rate)
    _validate_ratio("slippage_rate", config.slippage_rate)
    _validate_ratio("max_position_ratio", config.max_position_ratio)
    return config
