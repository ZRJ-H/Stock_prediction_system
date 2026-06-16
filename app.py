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
  GET  /api/stock/<code>/history?days=90 → 股票历史K线数据
  GET  /api/model/report                → 模型训练报告（只读，不触发训练）

启动方式：
  python app.py     → 默认监听 http://127.0.0.1:5000
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from core.agent import StockAgent
from core.blind_test import BlindTestError, BlindTestService
from core.config import load_local_env
from core.model_service import StockCNNService

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("stock_app")

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent
load_local_env(BASE_DIR / ".env")

# Flask 应用初始化
app = Flask(__name__)

# 全局服务实例（模块级单例，共享于所有请求）
agent = StockAgent()
model_service = StockCNNService(model_dir=BASE_DIR / "models" / "blind_test")
blind_test_service = BlindTestService(base_dir=BASE_DIR)


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
    from core.memory import validate_session_id

    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    session_id = (data.get("session_id") or "").strip()

    if not query:
        return jsonify({"reply": "请输入您想了解的问题。"})

    # session_id 为非空但非法时拒绝，与 /memory 行为一致
    if session_id:
        try:
            validate_session_id(session_id)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    try:
        challenge_context = None
        if session_id:
            active = blind_test_service.active_challenge(session_id)
            if active.get("active"):
                challenge_context = {
                    "id": active["id"],
                    "target_date": active["target_date"],
                }
        reply = agent.run(
            query,
            session_id=session_id,
            challenge_context=challenge_context,
        )
    except Exception:
        logger.exception("处理请求时出错，query=%s", query[:200])
        reply = "抱歉，处理您的请求时出现了内部错误，请稍后重试。"

    return jsonify({"reply": reply})


@app.route("/memory", methods=["GET"])
def get_memory():
    """读取指定会话的持久化用户偏好。

    Query Params:
        session_id: 会话 ID（必填）

    Response（JSON）:
        session_id / watchlist / preferred_style / risk_tolerance / last_session
    """
    from core.memory import load_preferences, validate_session_id

    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    try:
        validate_session_id(session_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

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
    from core.memory import update_preference, validate_session_id

    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    key = (data.get("key") or "").strip()
    value = (data.get("value") or "").strip()

    if not session_id or not key:
        return jsonify({"error": "缺少 session_id 或 key"}), 400
    try:
        validate_session_id(session_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    msg = update_preference(session_id, key, value)
    return jsonify({"message": msg})


@app.route("/health", methods=["GET"])
def health():
    """健康检查接口：返回各核心模块的状态（轻量级，不触发重型初始化）。

    前端通过此接口展示状态指示灯：
      - model_loaded:  CNN/MLP 模型文件是否存在
      - llm_available: OPENAI_API_KEY 是否已配置
      - rag_ready:     RAG 索引文件是否存在（不加载 embedding 模型）
    """
    from core.rag_service import INDEX_PATH, has_knowledge_sources

    rag_index_ready = INDEX_PATH.exists()
    rag_source_ready = has_knowledge_sources()

    return jsonify({
        "status": "ok",
        "model_loaded": model_service.has_trained_model(),
        "llm_available": bool(agent.llm.api_key),
        "llm_base_url": agent.llm.base_url if agent.llm.api_key else None,
        "llm_model": agent.llm.model_name if agent.llm.api_key else None,
        "rag_ready": rag_index_ready or rag_source_ready,
        "rag_index_ready": rag_index_ready,
        "rag_source_ready": rag_source_ready,
    })


@app.route("/api/stock/<code>/history", methods=["GET"])
def stock_history(code):
    """返回股票历史日K线数据，供前端 ECharts 图表使用。

    URL Path:
        code: 6 位股票代码

    Query Params:
        days: 获取天数（默认 90，范围 1-365）

    Response（JSON）:
        正常：{"code": "600519", "days": 90, "items": [{date, open, high, low, close, volume}, ...]}
        非法代码：400 {"error": "股票代码格式无效..."}
        无数据：  503 {"error": "K线数据暂不可用"}
    """
    import re
    from core.market_data import get_daily_kline

    # 校验股票代码格式：必须是 6 位数字
    if not re.fullmatch(r"\d{6}", code):
        return jsonify({"error": "股票代码格式无效，请输入6位数字代码"}), 400

    days = request.args.get("days", 90, type=int)
    days = max(1, min(days, 365))  # 限制 1-365 天

    bars = get_daily_kline(code, days=days)
    if not bars:
        return jsonify({"error": "K线数据暂不可用"}), 503

    return jsonify({
        "code": code,
        "days": days,
        "items": [b.to_dict() for b in bars],
    })


@app.route("/api/model/report", methods=["GET"])
def model_report():
    """返回模型训练报告（不触发训练，仅读取已有文件）。

    Response（JSON）:
        报告存在 → 200 {"available": true, ...report fields}
        报告不存在 → 200 {"available": false, "message": "尚未训练模型..."}
    """
    import json as _json
    report_path = BASE_DIR / "models" / "blind_test" / "training_report.json"
    legacy_report_path = BASE_DIR / "models" / "training_report.json"
    if not report_path.exists() and legacy_report_path.exists():
        report_path = legacy_report_path
    if not report_path.exists():
        return jsonify({
            "available": False,
            "message": (
                "尚未训练贵州茅台真实日线模型。请先准备数据，再运行 "
                "python train_model.py --data data/blind_test/600519_daily.csv "
                "--model-dir models/blind_test --backend mlp --symbol 600519。"
            ),
        })
    try:
        report = _json.loads(report_path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError:
        return jsonify({
            "available": False,
            "message": "训练报告文件损坏，请重新运行 python train_model.py。",
        })
    report["available"] = True
    return jsonify(report)


@app.route("/api/blind-test/config", methods=["GET"])
def blind_test_config():
    """返回历史盲测的股票、模型和测试区间信息。"""
    return jsonify(blind_test_service.config())


@app.route("/api/blind-test/active", methods=["GET"])
def active_blind_test_challenge():
    """Return the current round's unrevealed challenge for page restoration."""
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    try:
        return jsonify(blind_test_service.active_challenge(session_id))
    except (BlindTestError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/blind-test/challenges", methods=["POST"])
def create_blind_test_challenge():
    """随机或按指定测试日创建一个历史盲测挑战。"""
    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    target_date = (data.get("target_date") or "").strip()
    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    try:
        result = blind_test_service.create_challenge(session_id, target_date)
    except (BlindTestError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("创建历史盲测挑战失败")
        return jsonify({"error": "创建历史盲测挑战失败"}), 500
    return jsonify(result)


@app.route("/api/blind-test/challenges/<challenge_id>/prediction", methods=["POST"])
def submit_blind_test_prediction(challenge_id):
    """锁定用户预测，并公开 MLP 与新闻 AI 的赛前判断。"""
    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    label = (data.get("label") or "").strip()
    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    try:
        result = blind_test_service.submit_prediction(challenge_id, session_id, label)
    except (BlindTestError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("提交历史盲测用户预测失败 id=%s", challenge_id)
        return jsonify({"error": "提交用户预测失败"}), 500
    return jsonify(result)


@app.route("/api/blind-test/challenges/<challenge_id>/intelligence", methods=["POST"])
def generate_blind_test_intelligence(challenge_id):
    """Generate or return the cached leakage-safe intelligence brief."""
    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    try:
        result = blind_test_service.intelligence(challenge_id, session_id)
    except (BlindTestError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("生成历史盲测情报失败 id=%s", challenge_id)
        return jsonify({"error": "生成 AI 情报失败"}), 500
    return jsonify(result)


@app.route("/api/blind-test/challenges/<challenge_id>/reveal", methods=["POST"])
def reveal_blind_test_challenge(challenge_id):
    """揭晓盲测目标日；同一挑战只计分一次。"""
    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    try:
        result = blind_test_service.reveal(challenge_id, session_id)
    except (BlindTestError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("揭晓历史盲测挑战失败 id=%s", challenge_id)
        return jsonify({"error": "揭晓历史盲测挑战失败"}), 500
    return jsonify(result)


@app.route("/api/blind-test/stats", methods=["GET"])
def blind_test_stats():
    """返回当前会话和全局盲测成绩。"""
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    try:
        return jsonify(blind_test_service.stats(session_id))
    except (BlindTestError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/blind-test/reset", methods=["POST"])
def reset_blind_test_stats():
    """开启当前会话的新一轮成绩，全局历史不删除。"""
    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "缺少 session_id"}), 400
    try:
        return jsonify(blind_test_service.reset(session_id))
    except (BlindTestError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    # debug 模式由 FLASK_DEBUG 环境变量控制（默认关闭）
    is_debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=is_debug)
