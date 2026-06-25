"""Deterministic paper-trading database and engine."""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import core.market_data as market_data
from core.memory import validate_session_id
from core.paper_config import PaperTradingConfig, SignalRule, load_paper_trading_config

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "paper_trading" / "paper_trading.sqlite3"
_STOCK_CODE_RE = re.compile(r"^\d{6}\Z")


class PaperTradingError(ValueError):
    """An error safe to return to callers of the paper-trading service."""


@dataclass(frozen=True)
class PaperRunResult:
    """Single-stock paper trading run result."""

    stock_code: str
    trading_date: str
    strategy_version: str
    signal: str
    action: str
    status: str
    reason: str
    quantity: int = 0
    price: float | None = None
    fee: float = 0.0
    slippage: float = 0.0
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "trading_date": self.trading_date,
            "strategy_version": self.strategy_version,
            "signal": self.signal,
            "action": self.action,
            "status": self.status,
            "reason": self.reason,
            "quantity": self.quantity,
            "price": self.price,
            "fee": self.fee,
            "slippage": self.slippage,
            "dry_run": self.dry_run,
        }


class PaperTradingService:
    """Single-account paper trading service backed by SQLite."""

    ACCOUNT_ID = "default"

    def __init__(
        self,
        base_dir: str | Path = BASE_DIR,
        db_path: str | Path | None = None,
        config: PaperTradingConfig | None = None,
        config_path: str | Path | None = None,
        quote_provider: Callable[[str], market_data.StockQuote | None] | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.db_path = Path(db_path or self.base_dir / "data" / "paper_trading" / "paper_trading.sqlite3")
        self.config = config or load_paper_trading_config(config_path or self.base_dir / "config" / "paper_trading.json")
        self.quote_provider = quote_provider or market_data.get_realtime_quote

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_accounts (
                account_id TEXT PRIMARY KEY,
                initial_cash REAL NOT NULL,
                cash REAL NOT NULL,
                realized_pnl REAL NOT NULL DEFAULT 0,
                strategy_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_positions (
                account_id TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL DEFAULT '',
                quantity INTEGER NOT NULL,
                avg_cost REAL NOT NULL,
                latest_price REAL NOT NULL DEFAULT 0,
                market_value REAL NOT NULL DEFAULT 0,
                floating_pnl REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (account_id, stock_code),
                FOREIGN KEY(account_id) REFERENCES paper_accounts(account_id)
            );
            CREATE TABLE IF NOT EXISTS paper_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                trading_date TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL DEFAULT '',
                strategy_version TEXT NOT NULL,
                signal TEXT NOT NULL,
                action TEXT NOT NULL,
                score REAL,
                price REAL,
                quantity INTEGER NOT NULL DEFAULT 0,
                fee REAL NOT NULL DEFAULT 0,
                slippage REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES paper_accounts(account_id)
            );
            CREATE TABLE IF NOT EXISTS paper_daily_equity (
                account_id TEXT NOT NULL,
                trading_date TEXT NOT NULL,
                cash REAL NOT NULL,
                position_value REAL NOT NULL,
                total_assets REAL NOT NULL,
                daily_return REAL NOT NULL DEFAULT 0,
                max_drawdown REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (account_id, trading_date),
                FOREIGN KEY(account_id) REFERENCES paper_accounts(account_id)
            );
            CREATE TABLE IF NOT EXISTS paper_task_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                trading_date TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE(trading_date, stock_code, strategy_version),
                FOREIGN KEY(account_id) REFERENCES paper_accounts(account_id)
            );
            """
        )
        return conn

    def ensure_account(self) -> dict:
        with self._connect() as conn:
            self._ensure_account(conn)
            return self._account_payload(conn)

    def account_summary(self) -> dict:
        with self._connect() as conn:
            self._ensure_account(conn)
            return self._account_payload(conn)

    def positions(self) -> list[dict]:
        with self._connect() as conn:
            self._ensure_account(conn)
            rows = conn.execute(
                """
                SELECT * FROM paper_positions
                WHERE account_id=? AND quantity > 0
                ORDER BY stock_code
                """,
                (self.ACCOUNT_ID,),
            ).fetchall()
            return [dict(row) for row in rows]

    def orders(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            self._ensure_account(conn)
            rows = conn.execute(
                """
                SELECT * FROM paper_orders
                WHERE account_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (self.ACCOUNT_ID, max(1, min(int(limit), 500))),
            ).fetchall()
            return [dict(row) for row in rows]

    def equity_curve(self) -> list[dict]:
        with self._connect() as conn:
            self._ensure_account(conn)
            rows = conn.execute(
                """
                SELECT * FROM paper_daily_equity
                WHERE account_id=?
                ORDER BY trading_date ASC
                """,
                (self.ACCOUNT_ID,),
            ).fetchall()
            return [dict(row) for row in rows]

    def task_runs(self) -> list[dict]:
        with self._connect() as conn:
            self._ensure_account(conn)
            rows = conn.execute(
                """
                SELECT * FROM paper_task_runs
                WHERE account_id=?
                ORDER BY id DESC
                """,
                (self.ACCOUNT_ID,),
            ).fetchall()
            return [dict(row) for row in rows]

    def run_scores(
        self,
        scores: dict[str, float],
        trading_date: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Run deterministic score-based paper trading for supplied stocks."""

        run_date = trading_date or date.today().isoformat()
        self._validate_date(run_date)
        results = []
        for code, score in scores.items():
            results.append(self._run_one(self._normalize_code(code), self._validate_score(score), run_date, dry_run))
        account = None if dry_run else self.account_summary()
        return {
            "trading_date": run_date,
            "strategy_version": self.config.strategy_version,
            "dry_run": dry_run,
            "results": [item.to_dict() for item in results],
            "account": account,
        }

    def _run_one(self, stock_code: str, score: float, trading_date: str, dry_run: bool) -> PaperRunResult:
        rule = self.config.signal_for_score(score)
        if dry_run:
            return self._preview(stock_code, score, trading_date, rule)

        with self._connect() as conn:
            self._ensure_account(conn)
            if self._has_run(conn, trading_date, stock_code):
                return PaperRunResult(
                    stock_code=stock_code,
                    trading_date=trading_date,
                    strategy_version=self.config.strategy_version,
                    signal=rule.name,
                    action=rule.action,
                    status="skipped",
                    reason="duplicate_run",
                )
            quote = self.quote_provider(stock_code)
            if quote is None or quote.price <= 0:
                result = PaperRunResult(
                    stock_code=stock_code,
                    trading_date=trading_date,
                    strategy_version=self.config.strategy_version,
                    signal=rule.name,
                    action=rule.action,
                    status="skipped",
                    reason="quote_unavailable",
                )
                self._record_order(conn, result, score, "")
                self._record_daily_equity(conn, trading_date)
                return result

            task_id = self._start_task(conn, trading_date, stock_code)
            if rule.action == "BUY":
                result = self._buy(conn, trading_date, stock_code, quote, score, rule)
            elif rule.action == "SELL":
                result = self._sell(conn, trading_date, stock_code, quote, score, rule)
            else:
                result = PaperRunResult(
                    stock_code=stock_code,
                    trading_date=trading_date,
                    strategy_version=self.config.strategy_version,
                    signal=rule.name,
                    action=rule.action,
                    status="skipped",
                    reason="hold_signal",
                    price=float(quote.price),
                )
                self._record_order(conn, result, score, quote.name)
                self._update_position_price(conn, stock_code, quote)
            self._finish_task(conn, task_id, result.status, result.reason)
            self._record_daily_equity(conn, trading_date)
            return result

    def _preview(self, stock_code: str, score: float, trading_date: str, rule: SignalRule) -> PaperRunResult:
        quote = self.quote_provider(stock_code)
        if quote is None or quote.price <= 0:
            return PaperRunResult(
                stock_code=stock_code,
                trading_date=trading_date,
                strategy_version=self.config.strategy_version,
                signal=rule.name,
                action=rule.action,
                status="skipped",
                reason="quote_unavailable",
                dry_run=True,
            )
        return PaperRunResult(
            stock_code=stock_code,
            trading_date=trading_date,
            strategy_version=self.config.strategy_version,
            signal=rule.name,
            action=rule.action,
            status="dry_run",
            reason="dry_run",
            price=float(quote.price),
            dry_run=True,
        )

    def _buy(
        self,
        conn: sqlite3.Connection,
        trading_date: str,
        stock_code: str,
        quote: market_data.StockQuote,
        score: float,
        rule: SignalRule,
    ) -> PaperRunResult:
        account = self._account_row(conn)
        self._update_position_price(conn, stock_code, quote)
        position = self._position_row(conn, stock_code)
        cash = float(account["cash"])
        total_assets = self._total_assets(conn)
        current_value = float(position["market_value"]) if position else 0.0
        max_value = total_assets * self.config.max_position_ratio
        budget = min(cash * rule.cash_ratio, max(0.0, max_value - current_value), cash)
        exec_price = float(quote.price) * (1 + self.config.slippage_rate)
        quantity = int(budget / (exec_price * (1 + self.config.commission_rate))) if exec_price > 0 else 0
        if quantity <= 0:
            result = PaperRunResult(
                stock_code=stock_code,
                trading_date=trading_date,
                strategy_version=self.config.strategy_version,
                signal=rule.name,
                action=rule.action,
                status="skipped",
                reason="insufficient_cash_or_position_limit",
                price=exec_price,
            )
            self._record_order(conn, result, score, quote.name)
            return result

        gross = quantity * exec_price
        fee = gross * self.config.commission_rate
        total_cost = gross + fee
        if total_cost > cash + 1e-9:
            result = PaperRunResult(
                stock_code=stock_code,
                trading_date=trading_date,
                strategy_version=self.config.strategy_version,
                signal=rule.name,
                action=rule.action,
                status="skipped",
                reason="insufficient_cash",
                price=exec_price,
            )
            self._record_order(conn, result, score, quote.name)
            return result

        old_qty = int(position["quantity"]) if position else 0
        old_cost_total = float(position["avg_cost"]) * old_qty if position else 0.0
        new_qty = old_qty + quantity
        avg_cost = (old_cost_total + total_cost) / new_qty
        market_value = new_qty * float(quote.price)
        floating_pnl = market_value - new_qty * avg_cost
        now = self._now()
        conn.execute(
            "UPDATE paper_accounts SET cash=?, updated_at=? WHERE account_id=?",
            (cash - total_cost, now, self.ACCOUNT_ID),
        )
        conn.execute(
            """
            INSERT INTO paper_positions(
                account_id, stock_code, stock_name, quantity, avg_cost,
                latest_price, market_value, floating_pnl, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, stock_code) DO UPDATE SET
                stock_name=excluded.stock_name,
                quantity=excluded.quantity,
                avg_cost=excluded.avg_cost,
                latest_price=excluded.latest_price,
                market_value=excluded.market_value,
                floating_pnl=excluded.floating_pnl,
                updated_at=excluded.updated_at
            """,
            (
                self.ACCOUNT_ID,
                stock_code,
                quote.name,
                new_qty,
                avg_cost,
                float(quote.price),
                market_value,
                floating_pnl,
                now,
            ),
        )
        result = PaperRunResult(
            stock_code=stock_code,
            trading_date=trading_date,
            strategy_version=self.config.strategy_version,
            signal=rule.name,
            action=rule.action,
            status="filled",
            reason="score_signal",
            quantity=quantity,
            price=exec_price,
            fee=fee,
            slippage=abs(exec_price - float(quote.price)) * quantity,
        )
        self._record_order(conn, result, score, quote.name)
        return result

    def _sell(
        self,
        conn: sqlite3.Connection,
        trading_date: str,
        stock_code: str,
        quote: market_data.StockQuote,
        score: float,
        rule: SignalRule,
    ) -> PaperRunResult:
        account = self._account_row(conn)
        position = self._position_row(conn, stock_code)
        if position is None or int(position["quantity"]) <= 0:
            result = PaperRunResult(
                stock_code=stock_code,
                trading_date=trading_date,
                strategy_version=self.config.strategy_version,
                signal=rule.name,
                action=rule.action,
                status="skipped",
                reason="insufficient_position",
                price=float(quote.price),
            )
            self._record_order(conn, result, score, quote.name)
            return result

        held_qty = int(position["quantity"])
        quantity = min(held_qty, int(held_qty * rule.sell_ratio))
        if quantity <= 0:
            result = PaperRunResult(
                stock_code=stock_code,
                trading_date=trading_date,
                strategy_version=self.config.strategy_version,
                signal=rule.name,
                action=rule.action,
                status="skipped",
                reason="sell_quantity_zero",
                price=float(quote.price),
            )
            self._record_order(conn, result, score, quote.name)
            return result

        exec_price = float(quote.price) * (1 - self.config.slippage_rate)
        gross = quantity * exec_price
        fee = gross * self.config.commission_rate
        proceeds = gross - fee
        realized = (exec_price - float(position["avg_cost"])) * quantity - fee
        now = self._now()
        conn.execute(
            """
            UPDATE paper_accounts
            SET cash=?, realized_pnl=realized_pnl + ?, updated_at=?
            WHERE account_id=?
            """,
            (float(account["cash"]) + proceeds, realized, now, self.ACCOUNT_ID),
        )
        remaining = held_qty - quantity
        if remaining > 0:
            avg_cost = float(position["avg_cost"])
            market_value = remaining * float(quote.price)
            floating_pnl = market_value - remaining * avg_cost
            conn.execute(
                """
                UPDATE paper_positions
                SET stock_name=?, quantity=?, latest_price=?, market_value=?, floating_pnl=?, updated_at=?
                WHERE account_id=? AND stock_code=?
                """,
                (quote.name, remaining, float(quote.price), market_value, floating_pnl, now, self.ACCOUNT_ID, stock_code),
            )
        else:
            conn.execute(
                "DELETE FROM paper_positions WHERE account_id=? AND stock_code=?",
                (self.ACCOUNT_ID, stock_code),
            )
        result = PaperRunResult(
            stock_code=stock_code,
            trading_date=trading_date,
            strategy_version=self.config.strategy_version,
            signal=rule.name,
            action=rule.action,
            status="filled",
            reason="score_signal",
            quantity=quantity,
            price=exec_price,
            fee=fee,
            slippage=abs(float(quote.price) - exec_price) * quantity,
        )
        self._record_order(conn, result, score, quote.name)
        return result

    def _ensure_account(self, conn: sqlite3.Connection) -> None:
        now = self._now()
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_accounts(
                account_id, initial_cash, cash, realized_pnl, strategy_version, created_at, updated_at
            ) VALUES (?, ?, ?, 0, ?, ?, ?)
            """,
            (
                self.ACCOUNT_ID,
                self.config.initial_cash,
                self.config.initial_cash,
                self.config.strategy_version,
                now,
                now,
            ),
        )

    def _account_row(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM paper_accounts WHERE account_id=?",
            (self.ACCOUNT_ID,),
        ).fetchone()
        if row is None:
            raise PaperTradingError("Paper trading account is not initialized")
        return row

    def _account_payload(self, conn: sqlite3.Connection) -> dict:
        row = self._account_row(conn)
        position_value = self._position_value(conn)
        total_assets = float(row["cash"]) + position_value
        total_return = total_assets / float(row["initial_cash"]) - 1
        return {
            "account_id": row["account_id"],
            "initial_cash": float(row["initial_cash"]),
            "cash": float(row["cash"]),
            "position_value": position_value,
            "realized_pnl": float(row["realized_pnl"]),
            "total_assets": total_assets,
            "total_return": total_return,
            "strategy_version": row["strategy_version"],
        }

    def _position_row(self, conn: sqlite3.Connection, stock_code: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM paper_positions WHERE account_id=? AND stock_code=?",
            (self.ACCOUNT_ID, stock_code),
        ).fetchone()

    def _position_value(self, conn: sqlite3.Connection) -> float:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(market_value), 0) AS position_value
            FROM paper_positions
            WHERE account_id=? AND quantity > 0
            """,
            (self.ACCOUNT_ID,),
        ).fetchone()
        return float(row["position_value"])

    def _total_assets(self, conn: sqlite3.Connection) -> float:
        account = self._account_row(conn)
        return float(account["cash"]) + self._position_value(conn)

    def _has_run(self, conn: sqlite3.Connection, trading_date: str, stock_code: str) -> bool:
        row = conn.execute(
            """
            SELECT 1 FROM paper_task_runs
            WHERE trading_date=? AND stock_code=? AND strategy_version=?
            """,
            (trading_date, stock_code, self.config.strategy_version),
        ).fetchone()
        return row is not None

    def _start_task(self, conn: sqlite3.Connection, trading_date: str, stock_code: str) -> int:
        cursor = conn.execute(
            """
            INSERT INTO paper_task_runs(
                account_id, trading_date, stock_code, strategy_version, status, reason, started_at
            ) VALUES (?, ?, ?, ?, 'running', '', ?)
            """,
            (self.ACCOUNT_ID, trading_date, stock_code, self.config.strategy_version, self._now()),
        )
        if cursor.lastrowid is None:
            raise PaperTradingError("Failed to create paper trading task")
        return int(cursor.lastrowid)

    def _finish_task(self, conn: sqlite3.Connection, task_id: int, status: str, reason: str) -> None:
        conn.execute(
            "UPDATE paper_task_runs SET status=?, reason=?, finished_at=? WHERE id=?",
            (status, reason, self._now(), task_id),
        )

    def _record_order(
        self,
        conn: sqlite3.Connection,
        result: PaperRunResult,
        score: float,
        stock_name: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO paper_orders(
                account_id, trading_date, stock_code, stock_name, strategy_version,
                signal, action, score, price, quantity, fee, slippage, status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.ACCOUNT_ID,
                result.trading_date,
                result.stock_code,
                stock_name,
                result.strategy_version,
                result.signal,
                result.action,
                score,
                result.price,
                result.quantity,
                result.fee,
                result.slippage,
                result.status,
                result.reason,
                self._now(),
            ),
        )

    def _update_position_price(
        self,
        conn: sqlite3.Connection,
        stock_code: str,
        quote: market_data.StockQuote,
    ) -> None:
        position = self._position_row(conn, stock_code)
        if position is None:
            return
        quantity = int(position["quantity"])
        market_value = quantity * float(quote.price)
        floating_pnl = market_value - quantity * float(position["avg_cost"])
        conn.execute(
            """
            UPDATE paper_positions
            SET stock_name=?, latest_price=?, market_value=?, floating_pnl=?, updated_at=?
            WHERE account_id=? AND stock_code=?
            """,
            (quote.name, float(quote.price), market_value, floating_pnl, self._now(), self.ACCOUNT_ID, stock_code),
        )

    def _record_daily_equity(self, conn: sqlite3.Connection, trading_date: str) -> None:
        account = self._account_row(conn)
        cash = float(account["cash"])
        position_value = self._position_value(conn)
        total_assets = cash + position_value
        prev = conn.execute(
            """
            SELECT total_assets FROM paper_daily_equity
            WHERE account_id=? AND trading_date < ?
            ORDER BY trading_date DESC LIMIT 1
            """,
            (self.ACCOUNT_ID, trading_date),
        ).fetchone()
        daily_return = total_assets / float(prev["total_assets"]) - 1 if prev and prev["total_assets"] else 0.0
        peak_row = conn.execute(
            """
            SELECT MAX(total_assets) AS peak FROM paper_daily_equity
            WHERE account_id=?
            """,
            (self.ACCOUNT_ID,),
        ).fetchone()
        peak = max(total_assets, float(peak_row["peak"] or 0))
        max_drawdown = total_assets / peak - 1 if peak else 0.0
        conn.execute(
            """
            INSERT INTO paper_daily_equity(
                account_id, trading_date, cash, position_value, total_assets,
                daily_return, max_drawdown, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, trading_date) DO UPDATE SET
                cash=excluded.cash,
                position_value=excluded.position_value,
                total_assets=excluded.total_assets,
                daily_return=excluded.daily_return,
                max_drawdown=excluded.max_drawdown,
                created_at=excluded.created_at
            """,
            (self.ACCOUNT_ID, trading_date, cash, position_value, total_assets, daily_return, max_drawdown, self._now()),
        )

    @staticmethod
    def _validate_score(score: float) -> float:
        value = float(score)
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise PaperTradingError("Score must be a finite number between 0 and 100")
        return value

    @staticmethod
    def _normalize_code(code: str) -> str:
        value = str(code).strip().zfill(6)
        if not _STOCK_CODE_RE.match(value):
            raise PaperTradingError("Invalid stock code; expected 6 digits")
        return value

    @staticmethod
    def _validate_date(value: str) -> None:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise PaperTradingError("Invalid trading date; expected YYYY-MM-DD") from exc

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def run_configured_stocks(
        self,
        score_provider: Callable[[str], float],
        trading_date: str | None = None,
        stock_codes: Iterable[str] | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Run configured stocks using an injected score provider."""

        codes = list(stock_codes or self.config.stock_list)
        scores = {self._normalize_code(code): float(score_provider(self._normalize_code(code))) for code in codes}
        return self.run_scores(scores, trading_date=trading_date, dry_run=dry_run)


def validate_paper_session_id(session_id: str) -> str:
    """Reuse existing session_id validation for future API integration."""

    return validate_session_id(session_id)
