"""
Flask 主应用（Stock Prediction Web App）
========================================
提供股票分析助手的 Web 界面和 REST API。

路由说明：
  GET  /            → 前端聊天界面（index.html）
  POST /chat        → 对话接口（接收 {query, session_id}，返回 {reply}）
  GET  /memory      → 读取用户偏好（需 ?session_id=xxx）
  POST /memory      → 更新用户偏好（接收 {session_id, key, value}）
  GET  /health      → 健康检查（模型/LLM/RAG 状态）

启动方式：
  python app.py     → 监听 http://127.0.0.1:5000
"""

from __future__ import annotations

import traceback
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from core.agent import StockAgent
from core.model_service import StockCNNService

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent

# Flask 应用初始化
app = Flask(__name__)

# 全局服务实例（模块级单例，共享于所有请求）
agent = StockAgent()
model_service = StockCNNService(model_dir=BASE_DIR / "models")


@app.route("/", methods=["GET"])
def index():
    """渲染前端聊天页面。"""
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    """对话接口：接收用户查询，返回 Agent 分析结果。

    Request Body（JSON）:
        query:      用户输入的问题（必填）
        session_id: 客户端会话标识（可选，用于记忆和偏好）

    Response（JSON）:
        reply: Agent 的分析回复文本
    """
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    session_id = (data.get("session_id") or "").strip()

    if not query:
        return jsonify({"reply": "请输入您想了解的问题。"})

    try:
        reply = agent.run(query, session_id=session_id)
    except Exception:
        # 异常时返回完整堆栈（调试友好）
        reply = f"处理请求时出错:\n{traceback.format_exc()}"

    return jsonify({"reply": reply})


@app.route("/memory", methods=["GET"])
def get_memory():
    """读取指定会话的持久化用户偏好。

    Query Params:
        session_id: 会话 ID（必填）

    Response（JSON）:
        session_id / watchlist / preferred_style / risk_tolerance / last_session
    """
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
    """更新用户偏好。

    Request Body（JSON）:
        session_id: 会话 ID（必填）
        key:        偏好项名称（watchlist | preferred_style | risk_tolerance）
        value:      偏好值

    Response（JSON）:
        message: 操作结果描述
    """
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
    """健康检查接口：返回各核心模块的状态。

    前端通过此接口展示状态指示灯：
      - model_loaded:  CNN/MLP 模型是否已训练
      - llm_available: OPENAI_API_KEY 是否已配置
      - rag_ready:     RAG 知识库是否已构建并加载
    """
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
    # 开发模式启动（生产环境请使用 gunicorn 等 WSGI 服务器）
    app.run(host="127.0.0.1", port=5000, debug=True)
