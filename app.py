from __future__ import annotations

from pathlib import Path

import pandas as pd
from flask import Flask, render_template, request

from core.llm_service import LLMExplainer
from core.model_service import StockCNNService


BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "dataset" / "tt.csv"

app = Flask(__name__)
model_service = StockCNNService(model_dir=BASE_DIR / "models")
explainer = LLMExplainer()


def bootstrap_model() -> str:
    if model_service.has_trained_model():
        model_service.load()
        return "已加载历史训练模型。"

    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"缺少基础训练数据: {DATASET_PATH}")

    base_df = pd.read_csv(DATASET_PATH)
    metrics = model_service.train(base_df, epochs=8, batch_size=32)
    return f"已完成初始化训练，测试集准确率 {metrics['test_accuracy']:.4f}"


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    explanation = None
    error = None
    bootstrap_message = None

    try:
        bootstrap_message = bootstrap_model()
    except Exception as exc:  # pylint: disable=broad-except
        error = f"模型初始化失败: {exc}"

    if request.method == "POST" and error is None:
        file = request.files.get("stock_file")
        if file is None or file.filename == "":
            error = "请先上传 CSV 文件。"
        else:
            try:
                df = pd.read_csv(file)
                result = model_service.predict(df)
                explanation = explainer.explain(result)
            except Exception as exc:  # pylint: disable=broad-except
                error = f"预测失败: {exc}"

    return render_template(
        "index.html",
        result=result,
        explanation=explanation,
        error=error,
        bootstrap_message=bootstrap_message,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
