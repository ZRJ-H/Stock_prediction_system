"""
模型训练与推理服务（Model Service）
===================================
封装股票涨跌预测模型的完整生命周期：

训练后端（自动选择）：
  - TensorFlow CNN：一维卷积网络，序列特征提取能力强
  - sklearn MLP（fallback）：TF 不可用时自动降级为多层感知机

模型架构（CNN）：
  Input(60, N_features) → Conv1D(64, k=5) → MaxPool1D(2)
  → Conv1D(32, k=3) → GlobalAvgPool1D → Dense(32) → Dropout(0.2) → Dense(2, softmax)

持久化：
  - stock_cnn.keras / stock_mlp.joblib ：模型权重
  - scaler.json                        ：归一化参数
  - meta.json                          ：窗口大小、特征列、后端类型
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path
from typing import Dict, List

import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier

# 抑制 sklearn 版本兼容性警告
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

# 运行时检测 TensorFlow 是否可用
try:
    from tensorflow import keras

    HAS_TF = True
except ImportError:
    keras = None
    HAS_TF = False

from core.data_pipeline import MinMaxFeatureScaler, prepare_latest_window, prepare_training_data, time_series_split


class StockCNNService:
    """股票预测模型服务。

    职责：
      - train():   从 DataFrame 训练模型并持久化
      - predict(): 加载模型并预测最新窗口的涨跌方向
      - load():    从磁盘加载已训练的模型
      - has_trained_model(): 检查是否有可用的模型文件

    支持双后端：
      - TensorFlow CNN（首选，需 pip install tensorflow）
      - sklearn MLP（自动降级，零额外依赖）
    """

    def __init__(
        self,
        model_dir: str | Path,
        feature_columns: List[str] | None = None,
        window_size: int = 60,
    ) -> None:
        """初始化模型服务。

        Args:
            model_dir:       模型文件存放目录
            feature_columns: 使用的特征列名（默认 OHLCV）
            window_size:     滑动窗口大小（默认 60 个交易日）
        """
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.model_path = self.model_dir / "stock_cnn.keras"
        self.fallback_model_path = self.model_dir / "stock_mlp.joblib"
        self.scaler_path = self.model_dir / "scaler.json"
        self.meta_path = self.model_dir / "meta.json"

        self.feature_columns = feature_columns or ["open", "high", "low", "close", "vol"]
        self.window_size = window_size
        self.model = None        # 训练/加载后的模型实例
        self.scaler: MinMaxFeatureScaler | None = None

    def _build_model(self):
        """构建 CNN 模型（TensorFlow 后端）。

        架构设计：
          - Conv1D × 2：提取局部时序特征
          - MaxPool1D：降采样，增强鲁棒性
          - GlobalAvgPool1D：替代 Flatten，参数更少
          - Dropout(0.2)：防过拟合
          - Dense(2, softmax)：二分类（涨 / 跌）
        """
        if not HAS_TF:
            raise RuntimeError("TensorFlow 不可用，无法构建 CNN。")
        model = keras.Sequential(
            [
                keras.layers.Input(shape=(self.window_size, len(self.feature_columns))),
                keras.layers.Conv1D(64, kernel_size=5, activation="relu", padding="same"),
                keras.layers.MaxPool1D(pool_size=2),
                keras.layers.Conv1D(32, kernel_size=3, activation="relu", padding="same"),
                keras.layers.GlobalAveragePooling1D(),
                keras.layers.Dense(32, activation="relu"),
                keras.layers.Dropout(0.2),
                keras.layers.Dense(2, activation="softmax"),
            ]
        )
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=1e-3),
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )
        return model

    def has_trained_model(self) -> bool:
        """检查是否存在可用的已训练模型。

        Returns:
            True 当 CNN 模型文件或 MLP 降级模型存在时
        """
        has_dl = self.model_path.exists() and self.scaler_path.exists() and self.meta_path.exists()
        has_fallback = (
            self.fallback_model_path.exists() and self.scaler_path.exists() and self.meta_path.exists()
        )
        return has_dl or has_fallback

    def load(self) -> None:
        """从磁盘加载已训练的模型和归一化参数。

        加载优先级：TensorFlow CNN > sklearn MLP（降级）

        Raises:
            FileNotFoundError: 无模型文件或缺少可加载后端
        """
        if not self.has_trained_model():
            raise FileNotFoundError("未找到已训练模型。")
        if self.model_path.exists() and HAS_TF:
            self.model = keras.models.load_model(self.model_path)
        elif self.fallback_model_path.exists():
            self.model = joblib.load(self.fallback_model_path)
        else:
            raise FileNotFoundError("模型文件存在，但当前环境缺少可加载后端。")
        # 恢复归一化器和元数据
        self.scaler = MinMaxFeatureScaler.from_file(self.scaler_path)
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.window_size = int(meta["window_size"])
        self.feature_columns = list(meta["feature_columns"])

    def train(self, df: pd.DataFrame, epochs: int = 12, batch_size: int = 32) -> Dict[str, float]:
        """训练模型并持久化到磁盘。

        流程：数据预处理 → 训练/验证拆分 → 训练 → 保存模型/归一化器/元数据

        Args:
            df:         包含 OHLCV 和 label 列的 DataFrame
            epochs:     训练轮数（仅 CNN 模式使用）
            batch_size: 批次大小（仅 CNN 模式使用）

        Returns:
            {"test_loss": float, "test_accuracy": float}
        """
        # 1. 数据预处理：归一化 + 窗口化
        x, y, scaler = prepare_training_data(
            df=df,
            feature_columns=self.feature_columns,
            window_size=self.window_size,
        )
        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=0.2, random_state=42, stratify=y
        )

        # 2. 根据可用后段选择模型训练
        if HAS_TF:
            model = self._build_model()
            model.fit(
                x_train,
                y_train,
                validation_data=(x_test, y_test),
                epochs=epochs,
                batch_size=batch_size,
                verbose=0,
            )
            loss, accuracy = model.evaluate(x_test, y_test, verbose=0)
            model.save(self.model_path)
            backend = "tensorflow_cnn"
        else:
            # MLP 降级：将窗口展平为 1D 向量
            x_train_flat = x_train.reshape((x_train.shape[0], -1))
            x_test_flat = x_test.reshape((x_test.shape[0], -1))
            model = MLPClassifier(
                hidden_layer_sizes=(128, 64),
                activation="relu",
                learning_rate_init=1e-3,
                max_iter=300,
                random_state=42,
            )
            model.fit(x_train_flat, y_train)
            accuracy = model.score(x_test_flat, y_test)
            loss = 1.0 - accuracy
            joblib.dump(model, self.fallback_model_path)
            backend = "sklearn_mlp_fallback"

        # 3. 持久化归一化器和元数据
        scaler.to_file(self.scaler_path)
        self.meta_path.write_text(
            json.dumps(
                {
                    "window_size": self.window_size,
                    "feature_columns": self.feature_columns,
                    "backend": backend,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self.model = model
        self.scaler = scaler
        return {"test_loss": float(loss), "test_accuracy": float(accuracy)}

    def train_with_time_split(
        self, df: pd.DataFrame, epochs: int = 12, batch_size: int = 32
    ) -> Dict[str, object]:
        """使用时间序列切分训练模型，生成训练报告。

        与 train() 的区别：
          - 不随机打乱，严格按时间顺序切分（70%训练/15%验证/15%测试）
          - Scaler 仅在训练段拟合，避免未来信息泄漏到 val/test
          - 计算 baseline_accuracy（训练集多数类在测试集上的准确率）
          - 返回完整报告（含日期范围、样本量、模型文件列表）

        Returns:
            dict with keys: backend, sample_count, window_size, train_accuracy,
            val_accuracy, test_accuracy, baseline_accuracy, train_start, train_end,
            val_start, val_end, test_start, test_end, model_files
        """
        import numpy as np
        from core.data_pipeline import build_labels, build_windows, validate_dataframe

        # 1. 校验 + 先构建窗口/标签（未归一化），再时序切分
        validate_dataframe(df)
        w = self.window_size
        x_all = build_windows(df, self.feature_columns, window_size=w)
        y_all = build_labels(df, window_size=w)
        if len(x_all) == 0:
            raise ValueError("无法构造训练样本，请检查窗口大小和数据长度。")

        x_train, y_train, x_val, y_val, x_test, y_test = time_series_split(
            x_all, y_all, train_ratio=0.7, val_ratio=0.15
        )
        if len(x_train) == 0 or len(x_val) == 0 or len(x_test) == 0:
            raise ValueError(
                f"时间序列切分后训练/验证/测试集不能为空 "
                f"(train={len(x_train)}, val={len(x_val)}, test={len(x_test)}, "
                f"总样本={len(x_all)}, window={w})。请增大数据集或减小窗口。"
            )

        # 2. Scaler 仅在训练段拟合，再用于 val/test（杜绝未来信息泄漏）
        train_end_row = w + len(x_train)           # 训练段在原始 df 中的结束行号
        scaler = MinMaxFeatureScaler.fit(
            df.iloc[:train_end_row], self.feature_columns,
        )
        # 将 scaler 应用于全量数据后，重建各段的归一化窗口
        transformed = scaler.transform(df, self.feature_columns)
        x_all_norm = build_windows(transformed, self.feature_columns, window_size=w)
        x_tr, y_tr, x_va, y_va, x_te, y_te = time_series_split(
            x_all_norm, y_all, train_ratio=0.7, val_ratio=0.15
        )

        # 3. 基线准确率：训练集多数类在测试集上的准确率
        majority_class = int(np.bincount(y_train).argmax())
        baseline_acc = float((y_test == majority_class).mean())

        # 4. 日期范围（labels 对应行号 w..n-1）
        ts = df["timestamp"].astype(str)

        def _ts(i):
            if 0 <= i < len(ts):
                return str(ts.iloc[i])[:10]
            return "N/A"

        # 5. 训练模型
        if HAS_TF:
            model = self._build_model()
            model.fit(
                x_tr, y_tr,
                validation_data=(x_va, y_va),
                epochs=epochs, batch_size=batch_size, verbose=0,
            )
            _, train_acc = model.evaluate(x_tr, y_tr, verbose=0)
            _, val_acc = model.evaluate(x_va, y_va, verbose=0)
            _, test_acc = model.evaluate(x_te, y_te, verbose=0)
            model.save(self.model_path)
            backend = "tensorflow_cnn"
        else:
            x_tr_f = x_tr.reshape((x_tr.shape[0], -1))
            x_va_f = x_va.reshape((x_va.shape[0], -1))
            x_te_f = x_te.reshape((x_te.shape[0], -1))
            model = MLPClassifier(
                hidden_layer_sizes=(128, 64), activation="relu",
                learning_rate_init=1e-3, max_iter=300, random_state=42,
            )
            model.fit(x_tr_f, y_tr)
            train_acc = float(model.score(x_tr_f, y_tr))
            val_acc = float(model.score(x_va_f, y_va))
            test_acc = float(model.score(x_te_f, y_te))
            joblib.dump(model, self.fallback_model_path)
            backend = "sklearn_mlp_fallback"

        # 6. 持久化
        scaler.to_file(self.scaler_path)
        self.meta_path.write_text(
            json.dumps({
                "window_size": self.window_size,
                "feature_columns": self.feature_columns,
                "backend": backend,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.model = model
        self.scaler = scaler

        # 7. 模型文件列表
        model_files = ["scaler.json", "meta.json"]
        if backend == "tensorflow_cnn":
            model_files.insert(0, "stock_cnn.keras")
        else:
            model_files.insert(0, "stock_mlp.joblib")

        return {
            "backend": backend,
            "sample_count": len(x_all),
            "window_size": self.window_size,
            "train_accuracy": round(train_acc, 4),
            "val_accuracy": round(val_acc, 4),
            "test_accuracy": round(test_acc, 4),
            "baseline_accuracy": round(baseline_acc, 4),
            "train_start": _ts(w),
            "train_end": _ts(w + len(x_train) - 1),
            "val_start": _ts(w + len(x_train)),
            "val_end": _ts(w + len(x_train) + len(x_val) - 1),
            "test_start": _ts(w + len(x_train) + len(x_val)),
            "test_end": _ts(w + len(x_train) + len(x_val) + len(x_test) - 1),
            "model_files": model_files,
        }

    def ensure_ready(self) -> None:
        """确保模型已加载（懒加载：如未加载则自动 load）。"""
        if self.model is not None and self.scaler is not None:
            return
        self.load()

    def predict(self, df: pd.DataFrame) -> Dict[str, float | str]:
        """对最新窗口做涨跌预测。

        Args:
            df: 包含 OHLCV 列的 DataFrame（至少 window_size 行）

        Returns:
            {
                "label":         "涨" | "跌",
                "confidence":    预测置信度（0~1），
                "prob_up":       上涨概率，
                "prob_down":     下跌概率，
                "latest_close":  最新收盘价，
                "avg_return_5":  近 5 期平均涨跌幅(%),
                "avg_return_20": 近 20 期平均涨跌幅(%),
            }
        """
        self.ensure_ready()
        if self.model is None or self.scaler is None:
            raise RuntimeError("模型未就绪。")

        # 准备最新窗口 + 上下文统计
        x, context = prepare_latest_window(
            df=df,
            feature_columns=self.feature_columns,
            scaler=self.scaler,
            window_size=self.window_size,
        )

        # 推理：区分 TF（predict）和 sklearn（predict_proba）
        if HAS_TF and hasattr(self.model, "predict") and self.model_path.exists():
            prob = self.model.predict(x, verbose=0)[0]
            prob_down = float(prob[0])
            prob_up = float(prob[1])
        else:
            x_flat = x.reshape((x.shape[0], -1))
            prob = self.model.predict_proba(x_flat)[0]
            prob_down = float(prob[0])
            prob_up = float(prob[1])

        label = "涨" if prob_up >= prob_down else "跌"
        confidence = max(prob_up, prob_down)
        return {
            "label": label,
            "confidence": confidence,
            "prob_up": prob_up,
            "prob_down": prob_down,
            "latest_close": context["latest_close"],
            "avg_return_5": context["avg_return_5"],
            "avg_return_20": context["avg_return_20"],
        }
