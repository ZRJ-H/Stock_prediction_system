"""
记忆系统（Memory System）
=========================
两层记忆架构：

1. 会话记忆（Session Memory）
   - 存储：内存字典（进程级），30 分钟 TTL
   - 内容：最近 20 条对话消息（10 轮对话）
   - 用途：为 LLM 提供上下文连续性

2. 持久化偏好（Persistent User Preferences）
   - 存储：JSON 文件（data/memory/{session_id}.json）
   - 内容：关注列表、分析风格、风险偏好
   - 用途：跨会话保留用户习惯，注入 System Prompt
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent
# 持久化偏好存储目录
MEMORY_DIR = BASE_DIR / "data" / "memory"

# ═════════════════════════════════════════════════════════════
# session_id 安全校验
# ═════════════════════════════════════════════════════════════

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}\Z")


def validate_session_id(session_id: str) -> str:
    """校验 session_id 格式合法性。

    规则：1~80 字符，仅允许字母、数字、下划线、短横线。
    拒绝空字符串、含路径分隔符/点号/空白的输入。

    Returns:
        校验通过的 session_id

    Raises:
        ValueError: 格式不合法
    """
    if not session_id:
        raise ValueError("session_id 不能为空")
    if len(session_id) > 80:
        raise ValueError("session_id 长度不能超过 80 个字符")
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError("session_id 只能包含字母、数字、下划线和短横线")
    return session_id


def _safe_memory_path(session_id: str) -> Path:
    """生成安全的偏好文件路径（校验 + 路径穿越防护）。
    确保最终路径在 MEMORY_DIR 下。
    """
    validate_session_id(session_id)
    path = (MEMORY_DIR / f"{session_id}.json").resolve()
    if not str(path).startswith(str(MEMORY_DIR.resolve())):
        raise ValueError("非法的 session_id：路径穿越检测")
    return path

# ═════════════════════════════════════════════════════════════
# 会话记忆（Session Memory）—— 进程内，TTL 自动过期
# ═════════════════════════════════════════════════════════════

SESSION_TTL = 1800  # 会话超时时间（秒）= 30 分钟

# 全局会话存储：{session_id: {"messages": [...], "_ts": timestamp}}
_session_store: Dict[str, Dict[str, Any]] = {}


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """获取会话记录，同时刷新 TTL 时间戳。
    过期会话自动清理并返回 None。
    """
    entry = _session_store.get(session_id)
    if entry is None:
        return None
    # TTL 检查：超过 30 分钟未活动则清除
    if time.time() - entry["_ts"] > SESSION_TTL:
        del _session_store[session_id]
        return None
    # 刷新活动时间戳（每次访问续期）
    entry["_ts"] = time.time()
    return entry


def create_session(session_id: str) -> Dict[str, Any]:
    """创建新的会话记录。"""
    entry = {"messages": [], "_ts": time.time()}
    _session_store[session_id] = entry
    return entry


def add_message(session_id: str, role: str, content: str) -> None:
    """向会话中追加一条消息。
    自动滚动窗口：最多保留最近 20 条消息（避免内存膨胀）。
    """
    entry = get_session(session_id) or create_session(session_id)
    entry["messages"].append({"role": role, "content": content})
    # 滑动窗口：超过 20 条时丢弃最早的
    if len(entry["messages"]) > 20:
        entry["messages"] = entry["messages"][-20:]


def get_history(session_id: str) -> List[Dict[str, str]]:
    """获取会话的完整消息历史（供 LLM 上下文注入）。"""
    entry = get_session(session_id)
    if entry is None:
        return []
    return entry["messages"]


# ═════════════════════════════════════════════════════════════
# 持久化用户偏好（Persistent User Preferences）
# ═════════════════════════════════════════════════════════════


@dataclass
class UserPreferences:
    """用户偏好实体。

    Attributes:
        session_id:      会话唯一标识（前端 localStorage 生成）
        watchlist:       关注的股票代码列表
        preferred_style: 偏好的分析风格（technical | fundamental | balanced）
        risk_tolerance:  风险承受能力（conservative | moderate | aggressive）
        last_session:    上次活跃时间
    """
    session_id: str = ""
    watchlist: List[str] = field(default_factory=list)
    preferred_style: str = "balanced"
    risk_tolerance: str = "moderate"
    last_session: str = ""

    def to_prompt_hint(self) -> str:
        """生成紧凑的偏好提示，用于注入 System Prompt。

        仅在用户有个性化配置时才生成（避免不必要的 prompt token 消耗）。
        """
        if not self.watchlist and self.preferred_style == "balanced":
            return ""
        parts = []
        if self.watchlist:
            parts.append(f"用户关注股票: {', '.join(self.watchlist)}")
        if self.preferred_style != "balanced":
            parts.append(f"偏好分析风格: {self.preferred_style}")
        if self.risk_tolerance != "moderate":
            parts.append(f"风险偏好: {self.risk_tolerance}")
        return "用户偏好：" + "；".join(parts)


def load_preferences(session_id: str) -> UserPreferences:
    """从 JSON 文件加载用户偏好。

    Args:
        session_id: 会话 ID（对应用户设备/浏览器）

    Returns:
        UserPreferences（文件不存在或 session_id 非法时返回默认值）
    """
    try:
        path = _safe_memory_path(session_id)
    except ValueError:
        return UserPreferences(session_id=session_id)
    if not path.exists():
        return UserPreferences(session_id=session_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return UserPreferences(
            session_id=session_id,
            watchlist=data.get("watchlist", []),
            preferred_style=data.get("preferred_style", "balanced"),
            risk_tolerance=data.get("risk_tolerance", "moderate"),
            last_session=data.get("last_session", ""),
        )
    except (json.JSONDecodeError, Exception):
        return UserPreferences(session_id=session_id)


def save_preferences(prefs: UserPreferences) -> None:
    """将用户偏好持久化到 JSON 文件。"""
    path = _safe_memory_path(prefs.session_id)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    prefs.last_session = time.strftime("%Y-%m-%d %H:%M:%S")
    data = {
        "watchlist": prefs.watchlist,
        "preferred_style": prefs.preferred_style,
        "risk_tolerance": prefs.risk_tolerance,
        "last_session": prefs.last_session,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_preference(session_id: str, key: str, value: str) -> str:
    """更新单个偏好项并返回确认消息。

    支持的 key：
      - watchlist:         关注列表（逗号分隔的 6 位代码）
      - preferred_style:   分析风格（technical | fundamental | balanced）
      - risk_tolerance:    风险偏好（conservative | moderate | aggressive）

    Returns:
        操作结果描述文本
    """
    try:
        validate_session_id(session_id)
    except ValueError as e:
        return f"无效的 session_id：{e}"

    prefs = load_preferences(session_id)
    prefs.session_id = session_id

    # 有效 key 及其值的类型
    valid_keys = {
        "watchlist": "list",
        "preferred_style": "str",
        "risk_tolerance": "str",
    }
    if key not in valid_keys:
        return f"不支持的偏好设置: {key}。可用: {', '.join(valid_keys.keys())}"

    if key == "watchlist":
        codes = [c.strip() for c in value.split(",") if c.strip()]
        # 格式校验：6 位纯数字
        for code in codes:
            if not (len(code) == 6 and code.isdigit()):
                return f"无效的股票代码: {code}，应为6位数字"
        prefs.watchlist = codes
    elif key == "preferred_style":
        if value not in ("technical", "fundamental", "balanced"):
            return f"无效的分析风格: {value}，可用: technical, fundamental, balanced"
        prefs.preferred_style = value
    elif key == "risk_tolerance":
        if value not in ("conservative", "moderate", "aggressive"):
            return f"无效的风险偏好: {value}，可用: conservative, moderate, aggressive"
        prefs.risk_tolerance = value

    save_preferences(prefs)
    return f"偏好已更新: {key} = {value}"
