"""Guizhou Moutai historical blind-test game service."""

from __future__ import annotations

import json
import random
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from core.blind_news import BlindNewsService
from core.memory import validate_session_id
from core.model_service import StockCNNService


class BlindTestError(ValueError):
    """An error safe to return to an API caller."""


class BlindTestService:
    SYMBOL = "600519"
    STOCK_NAME = "贵州茅台"

    def __init__(
        self,
        base_dir: str | Path,
        data_path: str | Path | None = None,
        model_dir: str | Path | None = None,
        db_path: str | Path | None = None,
        news_path: str | Path | None = None,
        news_service: BlindNewsService | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.data_path = Path(data_path or self.base_dir / "data/blind_test/600519_daily.csv")
        self.model_dir = Path(model_dir or self.base_dir / "models/blind_test")
        self.db_path = Path(db_path or self.base_dir / "data/blind_test/blind_test.sqlite3")
        self.news_service = news_service or BlindNewsService(
            news_path or self.base_dir / "data/blind_test/600519_news.jsonl"
        )
        self._df: pd.DataFrame | None = None
        self._model: StockCNNService | None = None
        self._report: dict[str, Any] | None = None

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS session_rounds (
                session_id TEXT PRIMARY KEY,
                round_no INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS challenges (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                round_no INTEGER NOT NULL,
                target_date TEXT NOT NULL,
                predicted_label TEXT NOT NULL,
                confidence REAL NOT NULL,
                baseline_label TEXT NOT NULL,
                actual_label TEXT,
                actual_return REAL,
                model_correct INTEGER,
                baseline_correct INTEGER,
                revealed INTEGER NOT NULL DEFAULT 0,
                counted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                revealed_at TEXT,
                UNIQUE(session_id, round_no, target_date)
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(challenges)")}
        migrations = {
            "user_label": "TEXT",
            "user_submitted_at": "TEXT",
            "user_correct": "INTEGER",
            "intelligence_used": "INTEGER",
            "intelligence_json": "TEXT",
            "intelligence_generated_at": "TEXT",
            "user_score": "INTEGER",
            "news_status": "TEXT",
            "news_label": "TEXT",
            "news_confidence": "REAL",
            "news_reasons": "TEXT",
            "news_risk": "TEXT",
            "news_message": "TEXT",
            "news_items_json": "TEXT",
            "news_correct": "INTEGER",
        }
        for name, sql_type in migrations.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE challenges ADD COLUMN {name} {sql_type}")
        return conn

    def _round_no(self, conn: sqlite3.Connection, session_id: str) -> int:
        conn.execute(
            "INSERT OR IGNORE INTO session_rounds(session_id, round_no) VALUES (?, 1)",
            (session_id,),
        )
        row = conn.execute(
            "SELECT round_no FROM session_rounds WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row["round_no"])

    def _load_assets(self) -> tuple[pd.DataFrame, StockCNNService, dict[str, Any]]:
        if not self.data_path.exists():
            raise BlindTestError("盲测数据尚未准备，请先运行数据准备脚本。")
        report_path = self.model_dir / "training_report.json"
        if not report_path.exists():
            raise BlindTestError("盲测模型尚未训练。")

        if self._df is None:
            df = pd.read_csv(self.data_path)
            required = {"timestamp", "open", "high", "low", "close", "vol", "label"}
            if not required.issubset(df.columns):
                raise BlindTestError("盲测数据文件字段不完整。")
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna().sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
            if len(df) <= 60:
                raise BlindTestError("盲测数据不足60个交易日。")
            self._df = df

        if self._report is None:
            try:
                self._report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BlindTestError("盲测训练报告无法读取。") from exc
            if self._report.get("symbol") != self.SYMBOL:
                raise BlindTestError("模型元数据与贵州茅台不匹配。")

        if self._model is None:
            service = StockCNNService(model_dir=self.model_dir)
            try:
                service.load()
            except Exception as exc:
                raise BlindTestError("盲测模型无法加载。") from exc
            self._model = service
        return self._df, self._model, self._report

    def _test_indices(self, df: pd.DataFrame, report: dict[str, Any]) -> list[int]:
        start = pd.Timestamp(report["test_start"])
        end = pd.Timestamp(report["test_end"])
        indices = [
            idx for idx, value in enumerate(df["timestamp"])
            if idx >= 60 and start <= value <= end
        ]
        if not indices:
            raise BlindTestError("训练报告中的测试区间没有可用交易日。")
        return indices

    def config(self) -> dict[str, Any]:
        try:
            df, _, report = self._load_assets()
            indices = self._test_indices(df, report)
        except BlindTestError as exc:
            return {
                "available": False,
                "symbol": self.SYMBOL,
                "stock_name": self.STOCK_NAME,
                "message": str(exc),
            }
        return {
            "available": True,
            "symbol": self.SYMBOL,
            "stock_name": self.STOCK_NAME,
            "window_size": 60,
            "test_start": df.iloc[indices[0]]["timestamp"].strftime("%Y-%m-%d"),
            "test_end": df.iloc[indices[-1]]["timestamp"].strftime("%Y-%m-%d"),
            "test_days": len(indices),
            "data_source": report.get("data_source", "AKShare / 东方财富"),
            "adjust": report.get("adjust", "qfq"),
            "snapshot_date": report.get("snapshot_date"),
            "sklearn_version": report.get("sklearn_version"),
            "news": self.news_service.coverage(),
        }

    @staticmethod
    def _bars(df: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "date": row.timestamp.strftime("%Y-%m-%d"),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": int(row.vol),
            }
            for row in df.itertuples()
        ]

    def create_challenge(self, session_id: str, target_date: str = "") -> dict[str, Any]:
        validate_session_id(session_id)
        df, model, report = self._load_assets()
        indices = self._test_indices(df, report)
        index_by_date = {df.iloc[idx]["timestamp"].strftime("%Y-%m-%d"): idx for idx in indices}

        with self._connect() as conn:
            round_no = self._round_no(conn, session_id)
            active = conn.execute(
                """
                SELECT * FROM challenges
                WHERE session_id=? AND round_no=? AND revealed=0
                ORDER BY created_at DESC LIMIT 1
                """,
                (session_id, round_no),
            ).fetchone()
            if active:
                active_idx = index_by_date.get(active["target_date"])
                if active_idx is None:
                    raise BlindTestError("当前活动挑战的数据已不可用，请重置个人成绩。")
                payload = self._challenge_payload(active, df, active_idx)
                payload["active_existing"] = True
                payload["message"] = "当前轮次已有未揭晓挑战，请先完成或重置后再创建新题。"
                return payload
            if target_date:
                idx = index_by_date.get(target_date)
                if idx is None:
                    raise BlindTestError("指定日期不是隔离测试区间内的交易日。")
            else:
                used = {
                    row["target_date"]
                    for row in conn.execute(
                        "SELECT target_date FROM challenges WHERE session_id=? AND round_no=?",
                        (session_id, round_no),
                    )
                }
                candidates = [
                    idx for idx in indices
                    if df.iloc[idx]["timestamp"].strftime("%Y-%m-%d") not in used
                ]
                idx = random.choice(candidates or indices)
                target_date = df.iloc[idx]["timestamp"].strftime("%Y-%m-%d")

            existing = conn.execute(
                "SELECT * FROM challenges WHERE session_id=? AND round_no=? AND target_date=?",
                (session_id, round_no, target_date),
            ).fetchone()
            if existing:
                return self._challenge_payload(existing, df, idx)

            history = df.iloc[idx - 60:idx].copy()
            model_result = model.predict(history)
            previous_return = float(df.iloc[idx - 1]["close"] / df.iloc[idx - 2]["close"] - 1)
            baseline_label = "涨" if previous_return > 0 else "跌"
            news_items = self.news_service.before_target(target_date)
            challenge_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO challenges(
                    id, session_id, round_no, target_date, predicted_label,
                    confidence, baseline_label, news_items_json,
                    intelligence_used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    challenge_id, session_id, round_no, target_date,
                    model_result["label"], float(model_result["confidence"]), baseline_label,
                    json.dumps(news_items, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
            return self._challenge_payload(row, df, idx)

    @staticmethod
    def _news_items(row: sqlite3.Row) -> list[dict[str, Any]]:
        try:
            return json.loads(row["news_items_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def _challenge_payload(
        self, row: sqlite3.Row, df: pd.DataFrame, idx: int
    ) -> dict[str, Any]:
        submitted = bool(row["user_label"])
        payload = {
            "id": row["id"],
            "symbol": self.SYMBOL,
            "stock_name": self.STOCK_NAME,
            "target_date": row["target_date"],
            "history": self._bars(df.iloc[idx - 60:idx]),
            "test_range": self.config(),
            "submitted": submitted,
            "revealed": bool(row["revealed"]),
            "intelligence_used": bool(row["intelligence_used"]),
        }
        if row["intelligence_json"]:
            try:
                payload["intelligence"] = json.loads(row["intelligence_json"])
            except json.JSONDecodeError:
                payload["intelligence"] = None
        if submitted:
            payload.update({
                "user_prediction": row["user_label"],
                "model_prediction": {
                    "label": row["predicted_label"],
                    "confidence": row["confidence"],
                },
            })
        if row["revealed"]:
            payload["result"] = self._result_payload(row)
            target = df.loc[df["timestamp"] == pd.Timestamp(row["target_date"])].iloc[0]
            payload["target_bar"] = self._bars(pd.DataFrame([target]))[0]
        return payload

    @staticmethod
    def _result_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "actual_label": row["actual_label"],
            "actual_return": row["actual_return"],
            "user_label": row["user_label"],
            "user_correct": bool(row["user_correct"]),
            "user_score": int(row["user_score"] or 0),
            "intelligence_used": bool(row["intelligence_used"]),
            "model_label": row["predicted_label"],
            "model_correct": bool(row["model_correct"]),
            "baseline_label": row["baseline_label"],
            "baseline_correct": bool(row["baseline_correct"]),
        }

    def submit_prediction(
        self, challenge_id: str, session_id: str, label: str
    ) -> dict[str, Any]:
        validate_session_id(session_id)
        if label not in {"涨", "跌"}:
            raise BlindTestError("用户预测只能选择“涨”或“跌”。")
        df, _, _ = self._load_assets()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
            if row is None:
                raise BlindTestError("挑战不存在。")
            if row["session_id"] != session_id:
                raise BlindTestError("无权操作其他会话的挑战。")
            if row["user_label"] and row["user_label"] != label:
                raise BlindTestError("预测提交后不可修改。")
            if not row["user_label"]:
                conn.execute(
                    """
                    UPDATE challenges SET user_label=?, user_submitted_at=?
                    WHERE id=?
                    """,
                    (
                        label,
                        datetime.now(timezone.utc).isoformat(),
                        challenge_id,
                    ),
                )
                row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
            idx = df.index[df["timestamp"] == pd.Timestamp(row["target_date"])].tolist()[0]
            return self._challenge_payload(row, df, idx)

    def active_challenge(self, session_id: str) -> dict[str, Any]:
        validate_session_id(session_id)
        df, _, report = self._load_assets()
        index_by_date = {
            df.iloc[idx]["timestamp"].strftime("%Y-%m-%d"): idx
            for idx in self._test_indices(df, report)
        }
        with self._connect() as conn:
            round_no = self._round_no(conn, session_id)
            row = conn.execute(
                """
                SELECT * FROM challenges
                WHERE session_id=? AND round_no=? AND revealed=0
                ORDER BY created_at DESC LIMIT 1
                """,
                (session_id, round_no),
            ).fetchone()
            if row is None:
                return {"active": False, "round_no": round_no}
            idx = index_by_date.get(row["target_date"])
            if idx is None:
                return {"active": False, "round_no": round_no}
            payload = self._challenge_payload(row, df, idx)
            payload["active"] = True
            return payload

    def intelligence(self, challenge_id: str, session_id: str) -> dict[str, Any]:
        validate_session_id(session_id)
        df, _, _ = self._load_assets()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
            if row is None:
                raise BlindTestError("挑战不存在。")
            if row["session_id"] != session_id:
                raise BlindTestError("无权操作其他会话的挑战。")
            if row["revealed"]:
                raise BlindTestError("挑战已经揭晓，无需再生成赛前情报。")
            if row["intelligence_json"]:
                cached = json.loads(row["intelligence_json"])
                if cached.get("schema_version") == 2:
                    return cached

            matches = df.index[df["timestamp"] == pd.Timestamp(row["target_date"])].tolist()
            if not matches:
                raise BlindTestError("目标交易日数据不存在。")
            idx = matches[0]
            history = df.iloc[idx - 60:idx].copy()
            news_items = self._news_items(row)
            intelligence = self.news_service.generate(row["target_date"], history, news_items)
            conn.execute(
                """
                UPDATE challenges SET intelligence_used=1, intelligence_json=?,
                    intelligence_generated_at=? WHERE id=?
                """,
                (
                    json.dumps(intelligence, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                    challenge_id,
                ),
            )
            conn.commit()
            return intelligence

    def reveal(self, challenge_id: str, session_id: str) -> dict[str, Any]:
        validate_session_id(session_id)
        df, _, _ = self._load_assets()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
            if row is None:
                raise BlindTestError("挑战不存在。")
            if row["session_id"] != session_id:
                raise BlindTestError("无权揭晓其他会话的挑战。")
            if not row["user_label"]:
                raise BlindTestError("请先提交你的涨跌预测，再揭晓结果。")

            if not row["revealed"]:
                matches = df.index[df["timestamp"] == pd.Timestamp(row["target_date"])].tolist()
                if not matches:
                    raise BlindTestError("目标交易日数据不存在。")
                idx = matches[0]
                actual_return = float(df.iloc[idx]["close"] / df.iloc[idx - 1]["close"] - 1)
                actual_label = "涨" if actual_return > 0 else "跌"
                user_correct = int(row["user_label"] == actual_label)
                user_score = user_correct * (1 if row["intelligence_used"] else 2)
                conn.execute(
                    """
                    UPDATE challenges SET actual_label=?, actual_return=?,
                        user_correct=?, user_score=?, model_correct=?,
                        baseline_correct=?, revealed=1, counted=1, revealed_at=?
                    WHERE id=?
                    """,
                    (
                        actual_label,
                        actual_return,
                        user_correct,
                        user_score,
                        int(row["predicted_label"] == actual_label),
                        int(row["baseline_label"] == actual_label),
                        datetime.now(timezone.utc).isoformat(),
                        challenge_id,
                    ),
                )
                row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()

            target = df.loc[df["timestamp"] == pd.Timestamp(row["target_date"])].iloc[0]
            payload = {
                "id": challenge_id,
                "target_bar": self._bars(pd.DataFrame([target]))[0],
                "result": self._result_payload(row),
            }
            conn.commit()
        payload["stats"] = self.stats(session_id)
        return payload

    @staticmethod
    def _summarize(conn: sqlite3.Connection, where: str = "", params: tuple = ()) -> dict[str, Any]:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(user_correct), 0) AS user_hits,
                   COALESCE(SUM(model_correct), 0) AS model_hits,
                   COALESCE(SUM(baseline_correct), 0) AS baseline_hits,
                   COALESCE(SUM(user_score), 0) AS total_score,
                   COALESCE(SUM(CASE WHEN user_score IS NOT NULL AND intelligence_used=1 THEN 1 ELSE 0 END), 0) AS with_ai_total,
                   COALESCE(SUM(CASE WHEN user_score IS NOT NULL AND intelligence_used=1 THEN user_correct ELSE 0 END), 0) AS with_ai_hits,
                   COALESCE(SUM(CASE WHEN user_score IS NOT NULL AND intelligence_used=0 THEN 1 ELSE 0 END), 0) AS without_ai_total,
                   COALESCE(SUM(CASE WHEN user_score IS NOT NULL AND intelligence_used=0 THEN user_correct ELSE 0 END), 0) AS without_ai_hits
            FROM challenges WHERE counted=1 {where}
            """,
            params,
        ).fetchone()
        total = int(row["total"])
        result = {
            "total": total,
            "total_score": int(row["total_score"]),
            "with_ai": {
                "total": int(row["with_ai_total"]),
                "hits": int(row["with_ai_hits"]),
            },
            "without_ai": {
                "total": int(row["without_ai_total"]),
                "hits": int(row["without_ai_hits"]),
            },
        }
        for name in ("user", "model", "baseline"):
            hits = int(row[f"{name}_hits"])
            result[f"{name}_hits"] = hits
            result[f"{name}_accuracy"] = hits / total if total else 0.0
        return result

    @staticmethod
    def _streaks(conn: sqlite3.Connection, session_id: str, round_no: int) -> dict[str, int]:
        rows = conn.execute(
            """
            SELECT user_correct FROM challenges
            WHERE counted=1 AND user_score IS NOT NULL
              AND session_id=? AND round_no=?
            ORDER BY revealed_at ASC
            """,
            (session_id, round_no),
        ).fetchall()
        current = 0
        best = 0
        for row in rows:
            if row["user_correct"]:
                current += 1
                best = max(best, current)
            else:
                current = 0
        return {"current_streak": current, "best_streak": best}

    def stats(self, session_id: str) -> dict[str, Any]:
        validate_session_id(session_id)
        with self._connect() as conn:
            round_no = self._round_no(conn, session_id)
            personal = self._summarize(
                conn, "AND session_id=? AND round_no=?", (session_id, round_no)
            )
            personal.update(self._streaks(conn, session_id, round_no))
            return {
                "personal": personal,
                "global": self._summarize(conn),
                "round_no": round_no,
            }

    def reset(self, session_id: str) -> dict[str, Any]:
        validate_session_id(session_id)
        with self._connect() as conn:
            round_no = self._round_no(conn, session_id) + 1
            conn.execute(
                "UPDATE session_rounds SET round_no=? WHERE session_id=?",
                (round_no, session_id),
            )
            conn.commit()
        return self.stats(session_id)
