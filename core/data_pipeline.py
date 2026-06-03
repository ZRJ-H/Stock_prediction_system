"""
数据预处理管道（Data Pipeline）
===============================
负责将原始股票 CSV/K线数据转换为模型可用的训练/推理样本：
  1. 数据校验：检查必需列、最小数据量
  2. 特征归一化：MinMaxScaler，将各特征缩放到 [0, 1] 区间
  3. 滑动窗口：将时序数据切分为固定长度的窗口样本
  4. 标签构建：基于下一期涨跌生成二分类标签
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# 数据帧必需的列名
REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "label"]


def validate_dataframe(df: pd.DataFrame, required_columns: List[str] | None = None) -> None:
    """校验数据帧是否包含必需的列，以及数据量是否满足最低要求（≥60行）。"""
    required = required_columns or REQUIRED_COLUMNS
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"CSV 缺少必要列: {missing}")
    if len(df) < 60:
        raise ValueError(f"CSV 数据量过少，至少需要 60 行，当前仅 {len(df)} 行。")


@dataclass
class MinMaxFeatureScaler:
    """MinMax 特征归一化器。
    将每个特征线性映射到 [0, 1] 区间，训练时记录 min/max，
    推理时用相同的 min/max 做变换，保证分布一致性。

    Attributes:
        min_values: 每个特征在训练集上的最小值
        max_values: 每个特征在训练集上的最大值
    """
    min_values: Dict[str, float]
    max_values: Dict[str, float]

    @classmethod
    def fit(cls, df: pd.DataFrame, feature_columns: List[str]) -> "MinMaxFeatureScaler":
        """在训练集上拟合归一化器，记录每个特征的 min/max。"""
        min_values = {col: float(df[col].min()) for col in feature_columns}
        max_values = {col: float(df[col].max()) for col in feature_columns}
        return cls(min_values=min_values, max_values=max_values)

    def transform(self, df: pd.DataFrame, feature_columns: List[str]) -> pd.DataFrame:
        """使用已记录的 min/max 对数据做归一化变换。
        公式: x_norm = (x - min) / (max - min)，结果裁剪到 [0, 1]。
        """
        transformed = df.copy()
        for col in feature_columns:
            min_val = self.min_values[col]
            max_val = self.max_values[col]
            span = max_val - min_val
            if span == 0:
                # 常数特征，直接置零（无区分度）
                transformed[col] = 0.0
            else:
                transformed[col] = (transformed[col] - min_val) / span
            # 裁剪异常值（浮点精度可能导致越界）
            transformed[col] = transformed[col].clip(0.0, 1.0)
        return transformed

    def to_file(self, path: Path) -> None:
        """将归一化参数序列化到 JSON 文件，供推理阶段复用。"""
        payload = {"min_values": self.min_values, "max_values": self.max_values}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_file(cls, path: Path) -> "MinMaxFeatureScaler":
        """从 JSON 文件反序列化归一化参数。"""
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(min_values=payload["min_values"], max_values=payload["max_values"])


def build_windows(
    df: pd.DataFrame,
    feature_columns: List[str],
    window_size: int = 60,
) -> np.ndarray:
    """构建滑动窗口样本。
    从时序数据中切出 (样本数, window_size, 特征数) 的三维数组。
    第 t 个窗口 = [t-window_size, t) 区间的所有特征值。
    """
    values = df[feature_columns].to_numpy(dtype=np.float32)
    windows = []
    for idx in range(window_size, len(values)):
        windows.append(values[idx - window_size : idx])
    return np.asarray(windows, dtype=np.float32)


def build_labels(df: pd.DataFrame, window_size: int = 60, label_col: str = "label") -> np.ndarray:
    """构建二分类标签。
    标签定义：下一期涨（>0）→ 1，跌/平（≤0）→ 0。
    标签与 build_windows 的窗口一一对应（第 window_size 行起）。
    """
    labels = (df[label_col].to_numpy()[window_size:] > 0).astype(np.int32)
    return labels


def prepare_training_data(
    df: pd.DataFrame,
    feature_columns: List[str],
    window_size: int = 60,
) -> Tuple[np.ndarray, np.ndarray, MinMaxFeatureScaler]:
    """完整的训练数据准备流程：校验 → 归一化 → 窗口化 → 标签化。

    Returns:
        x: 窗口样本，形状 (样本数, window_size, 特征数)
        y: 二分类标签，形状 (样本数,)
        scaler: 归一化器（需持久化供推理阶段复用）
    """
    validate_dataframe(df)
    scaler = MinMaxFeatureScaler.fit(df, feature_columns)
    transformed = scaler.transform(df, feature_columns)
    x = build_windows(transformed, feature_columns, window_size=window_size)
    y = build_labels(df, window_size=window_size)
    if len(x) == 0 or len(y) == 0:
        raise ValueError("无法构造训练样本，请检查窗口大小和数据长度。")
    return x, y, scaler


def time_series_split(
    x: np.ndarray,
    y: np.ndarray,
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """按时间顺序切分数据（不随机打乱，保留时序依赖）。

    Returns:
        x_train, y_train, x_val, y_val, x_test, y_test
    """
    n = len(x)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))
    return (
        x[:train_end], y[:train_end],
        x[train_end:val_end], y[train_end:val_end],
        x[val_end:], y[val_end:],
    )


def prepare_latest_window(
    df: pd.DataFrame,
    feature_columns: List[str],
    scaler: MinMaxFeatureScaler,
    window_size: int = 60,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """准备推理用的最新窗口样本。
    取最近 window_size 行数据，用训练好的 scaler 做归一化，
    同时提取上下文统计量（最新价、近N期平均涨跌幅）供报告使用。

    Returns:
        latest_window: 形状 (1, window_size, 特征数)
        context: 上下文统计字典，含 latest_close / avg_return_5 / avg_return_20
    """
    validate_dataframe(df, required_columns=["timestamp", "open", "high", "low", "close"])
    if len(df) < window_size:
        raise ValueError(f"数据长度不足 {window_size} 行，无法预测。")

    transformed = scaler.transform(df, feature_columns)
    # 取最近 window_size 行并增加 batch 维度
    latest_window = transformed[feature_columns].iloc[-window_size:].to_numpy(dtype=np.float32)
    latest_window = np.expand_dims(latest_window, axis=0)

    # 计算上下文统计量（用于结果解读）
    close_series = df["close"].astype(float)
    pct = close_series.pct_change().fillna(0.0)
    context = {
        "latest_close": float(close_series.iloc[-1]),
        "avg_return_5": float(pct.iloc[-5:].mean() * 100),
        "avg_return_20": float(pct.iloc[-20:].mean() * 100),
    }
    return latest_window, context
