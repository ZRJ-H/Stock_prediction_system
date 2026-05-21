from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "label"]


def validate_dataframe(df: pd.DataFrame, required_columns: List[str] | None = None) -> None:
    required = required_columns or REQUIRED_COLUMNS
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"CSV 缺少必要列: {missing}")
    if len(df) < 60:
        raise ValueError(f"CSV 数据量过少，至少需要 60 行，当前仅 {len(df)} 行。")


@dataclass
class MinMaxFeatureScaler:
    min_values: Dict[str, float]
    max_values: Dict[str, float]

    @classmethod
    def fit(cls, df: pd.DataFrame, feature_columns: List[str]) -> "MinMaxFeatureScaler":
        min_values = {col: float(df[col].min()) for col in feature_columns}
        max_values = {col: float(df[col].max()) for col in feature_columns}
        return cls(min_values=min_values, max_values=max_values)

    def transform(self, df: pd.DataFrame, feature_columns: List[str]) -> pd.DataFrame:
        transformed = df.copy()
        for col in feature_columns:
            min_val = self.min_values[col]
            max_val = self.max_values[col]
            span = max_val - min_val
            if span == 0:
                transformed[col] = 0.0
            else:
                transformed[col] = (transformed[col] - min_val) / span
            transformed[col] = transformed[col].clip(0.0, 1.0)
        return transformed

    def to_file(self, path: Path) -> None:
        payload = {"min_values": self.min_values, "max_values": self.max_values}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_file(cls, path: Path) -> "MinMaxFeatureScaler":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(min_values=payload["min_values"], max_values=payload["max_values"])


def build_windows(
    df: pd.DataFrame,
    feature_columns: List[str],
    window_size: int = 60,
) -> np.ndarray:
    values = df[feature_columns].to_numpy(dtype=np.float32)
    windows = []
    for idx in range(window_size, len(values)):
        windows.append(values[idx - window_size : idx])
    return np.asarray(windows, dtype=np.float32)


def build_labels(df: pd.DataFrame, window_size: int = 60, label_col: str = "label") -> np.ndarray:
    labels = (df[label_col].to_numpy()[window_size:] > 0).astype(np.int32)
    return labels


def prepare_training_data(
    df: pd.DataFrame,
    feature_columns: List[str],
    window_size: int = 60,
) -> Tuple[np.ndarray, np.ndarray, MinMaxFeatureScaler]:
    validate_dataframe(df)
    scaler = MinMaxFeatureScaler.fit(df, feature_columns)
    transformed = scaler.transform(df, feature_columns)
    x = build_windows(transformed, feature_columns, window_size=window_size)
    y = build_labels(df, window_size=window_size)
    if len(x) == 0 or len(y) == 0:
        raise ValueError("无法构造训练样本，请检查窗口大小和数据长度。")
    return x, y, scaler


def prepare_latest_window(
    df: pd.DataFrame,
    feature_columns: List[str],
    scaler: MinMaxFeatureScaler,
    window_size: int = 60,
) -> Tuple[np.ndarray, Dict[str, float]]:
    validate_dataframe(df, required_columns=["timestamp", "open", "high", "low", "close"])
    if len(df) < window_size:
        raise ValueError(f"数据长度不足 {window_size} 行，无法预测。")

    transformed = scaler.transform(df, feature_columns)
    latest_window = transformed[feature_columns].iloc[-window_size:].to_numpy(dtype=np.float32)
    latest_window = np.expand_dims(latest_window, axis=0)

    close_series = df["close"].astype(float)
    pct = close_series.pct_change().fillna(0.0)
    context = {
        "latest_close": float(close_series.iloc[-1]),
        "avg_return_5": float(pct.iloc[-5:].mean() * 100),
        "avg_return_20": float(pct.iloc[-20:].mean() * 100),
    }
    return latest_window, context
