from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier

try:
    from tensorflow import keras

    HAS_TF = True
except ImportError:
    keras = None
    HAS_TF = False

from core.data_pipeline import MinMaxFeatureScaler, prepare_latest_window, prepare_training_data


class StockCNNService:
    def __init__(
        self,
        model_dir: str | Path,
        feature_columns: List[str] | None = None,
        window_size: int = 60,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.model_path = self.model_dir / "stock_cnn.keras"
        self.fallback_model_path = self.model_dir / "stock_mlp.joblib"
        self.scaler_path = self.model_dir / "scaler.json"
        self.meta_path = self.model_dir / "meta.json"

        self.feature_columns = feature_columns or ["open", "high", "low", "close", "vol"]
        self.window_size = window_size
        self.model = None
        self.scaler: MinMaxFeatureScaler | None = None

    def _build_model(self):
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
        has_dl = self.model_path.exists() and self.scaler_path.exists() and self.meta_path.exists()
        has_fallback = (
            self.fallback_model_path.exists() and self.scaler_path.exists() and self.meta_path.exists()
        )
        return has_dl or has_fallback

    def load(self) -> None:
        if not self.has_trained_model():
            raise FileNotFoundError("未找到已训练模型。")
        if self.model_path.exists() and HAS_TF:
            self.model = keras.models.load_model(self.model_path)
        elif self.fallback_model_path.exists():
            self.model = joblib.load(self.fallback_model_path)
        else:
            raise FileNotFoundError("模型文件存在，但当前环境缺少可加载后端。")
        self.scaler = MinMaxFeatureScaler.from_file(self.scaler_path)
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.window_size = int(meta["window_size"])
        self.feature_columns = list(meta["feature_columns"])

    def train(self, df: pd.DataFrame, epochs: int = 12, batch_size: int = 32) -> Dict[str, float]:
        x, y, scaler = prepare_training_data(
            df=df,
            feature_columns=self.feature_columns,
            window_size=self.window_size,
        )
        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=0.2, random_state=42, stratify=y
        )

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

    def ensure_ready(self) -> None:
        if self.model is not None and self.scaler is not None:
            return
        self.load()

    def predict(self, df: pd.DataFrame) -> Dict[str, float | str]:
        self.ensure_ready()
        if self.model is None or self.scaler is None:
            raise RuntimeError("模型未就绪。")

        x, context = prepare_latest_window(
            df=df,
            feature_columns=self.feature_columns,
            scaler=self.scaler,
            window_size=self.window_size,
        )
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
