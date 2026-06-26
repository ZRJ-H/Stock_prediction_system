"""Excel report export for paper trading."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Iterable, cast

import pandas as pd

from core.paper_trading import PaperTradingService

DISCLAIMER = "仅为模拟交易与技术演示，不构成投资建议。"


class PaperReportService:
    """Build XLSX reports from the paper-trading service state."""

    def __init__(self, service: PaperTradingService) -> None:
        self.service = service

    def generate_xlsx(self) -> BytesIO:
        """Generate a multi-sheet XLSX workbook in memory."""

        account = self.service.account_summary()
        positions = self.service.positions()
        orders = self.service.orders(limit=500)
        equity = self.service.equity_curve()
        task_runs = self.service.task_runs()
        metadata = self._metadata(account, equity, task_runs)

        buffer = BytesIO()
        with pd.ExcelWriter(cast(Any, buffer), engine="openpyxl") as writer:
            self._frame([account], _ACCOUNT_COLUMNS).to_excel(writer, sheet_name="Account", index=False)
            self._frame(positions, _POSITION_COLUMNS).to_excel(writer, sheet_name="Positions", index=False)
            self._frame(orders, _ORDER_COLUMNS).to_excel(writer, sheet_name="Orders", index=False)
            self._frame(equity, _EQUITY_COLUMNS).to_excel(writer, sheet_name="Equity", index=False)
            self._frame(task_runs, _TASK_RUN_COLUMNS).to_excel(writer, sheet_name="TaskRuns", index=False)
            pd.DataFrame(metadata, columns=cast(Any, ["key", "value"])).to_excel(writer, sheet_name="Metadata", index=False)
        buffer.seek(0)
        return buffer

    def _metadata(self, account: dict, equity: list[dict], task_runs: list[dict]) -> list[tuple[str, str]]:
        return [
            ("generated_at", datetime.now(timezone.utc).isoformat()),
            ("strategy_version", str(account.get("strategy_version", ""))),
            ("simulation_account_id", str(account.get("account_id", ""))),
            ("simulation_start_at", str(account.get("created_at", ""))),
            ("data_range", self._data_range(equity, task_runs)),
            ("disclaimer", DISCLAIMER),
        ]

    @staticmethod
    def _data_range(equity: list[dict], task_runs: list[dict]) -> str:
        dates = []
        dates.extend(str(item["trading_date"]) for item in equity if item.get("trading_date"))
        dates.extend(str(item["trading_date"]) for item in task_runs if item.get("trading_date"))
        if not dates:
            return ""
        return f"{min(dates)} ~ {max(dates)}"

    @staticmethod
    def _frame(rows: Iterable[dict], columns: list[str]) -> pd.DataFrame:
        return pd.DataFrame(list(rows), columns=cast(Any, columns))


_ACCOUNT_COLUMNS = [
    "account_id",
    "initial_cash",
    "cash",
    "position_value",
    "realized_pnl",
    "total_assets",
    "total_return",
    "strategy_version",
    "created_at",
    "updated_at",
]
_POSITION_COLUMNS = [
    "account_id",
    "stock_code",
    "stock_name",
    "quantity",
    "avg_cost",
    "latest_price",
    "market_value",
    "floating_pnl",
    "updated_at",
]
_ORDER_COLUMNS = [
    "id",
    "account_id",
    "trading_date",
    "stock_code",
    "stock_name",
    "strategy_version",
    "signal",
    "action",
    "score",
    "price",
    "quantity",
    "fee",
    "slippage",
    "status",
    "reason",
    "created_at",
]
_EQUITY_COLUMNS = [
    "account_id",
    "trading_date",
    "cash",
    "position_value",
    "total_assets",
    "daily_return",
    "max_drawdown",
    "created_at",
]
_TASK_RUN_COLUMNS = [
    "id",
    "account_id",
    "trading_date",
    "stock_code",
    "strategy_version",
    "status",
    "reason",
    "started_at",
    "finished_at",
]
