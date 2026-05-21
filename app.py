from __future__ import annotations

import traceback
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from core.agent import StockAgent
from core.model_service import StockCNNService

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
agent = StockAgent()
model_service = StockCNNService(model_dir=BASE_DIR / "models")


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"reply": "请输入您想了解的问题。"})
    try:
        reply = agent.run(query)
    except Exception:
        reply = f"处理请求时出错:\n{traceback.format_exc()}"
    return jsonify({"reply": reply})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "model_loaded": model_service.has_trained_model(),
        "llm_available": bool(agent.llm.api_key),
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
