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
    session_id = (data.get("session_id") or "").strip()
    if not query:
        return jsonify({"reply": "请输入您想了解的问题。"})
    try:
        reply = agent.run(query, session_id=session_id)
    except Exception:
        reply = f"处理请求时出错:\n{traceback.format_exc()}"
    return jsonify({"reply": reply})


@app.route("/memory", methods=["GET"])
def get_memory():
    """Read user preferences for a session."""
    from core.memory import load_preferences
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    prefs = load_preferences(session_id)
    return jsonify({
        "session_id": prefs.session_id,
        "watchlist": prefs.watchlist,
        "preferred_style": prefs.preferred_style,
        "risk_tolerance": prefs.risk_tolerance,
        "last_session": prefs.last_session,
    })


@app.route("/memory", methods=["POST"])
def update_memory():
    """Update user preferences."""
    from core.memory import update_preference
    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    key = (data.get("key") or "").strip()
    value = (data.get("value") or "").strip()
    if not session_id or not key:
        return jsonify({"error": "缺少 session_id 或 key"}), 400
    msg = update_preference(session_id, key, value)
    return jsonify({"message": msg})


@app.route("/health", methods=["GET"])
def health():
    rag_ready = False
    try:
        from core.rag_service import RAGService
        r = RAGService()
        rag_ready = r.is_ready() or r.initialize()
    except Exception:
        pass
    return jsonify({
        "status": "ok",
        "model_loaded": model_service.has_trained_model(),
        "llm_available": bool(agent.llm.api_key),
        "rag_ready": rag_ready,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
