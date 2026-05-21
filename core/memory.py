"""Conversation session memory + persistent user preferences."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "data" / "memory"

# ═══════════════════════════════════════════════════════════
# Session Memory (in-process, TTL-based)
# ═══════════════════════════════════════════════════════════

SESSION_TTL = 1800  # 30 minutes

_session_store: Dict[str, Dict[str, Any]] = {}


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    entry = _session_store.get(session_id)
    if entry is None:
        return None
    if time.time() - entry["_ts"] > SESSION_TTL:
        del _session_store[session_id]
        return None
    entry["_ts"] = time.time()
    return entry


def create_session(session_id: str) -> Dict[str, Any]:
    entry = {"messages": [], "_ts": time.time()}
    _session_store[session_id] = entry
    return entry


def add_message(session_id: str, role: str, content: str) -> None:
    entry = get_session(session_id) or create_session(session_id)
    entry["messages"].append({"role": role, "content": content})
    # Keep last 20 messages (10 turns)
    if len(entry["messages"]) > 20:
        entry["messages"] = entry["messages"][-20:]


def get_history(session_id: str) -> List[Dict[str, str]]:
    entry = get_session(session_id)
    if entry is None:
        return []
    return entry["messages"]


# ═══════════════════════════════════════════════════════════
# Persistent User Preferences
# ═══════════════════════════════════════════════════════════


@dataclass
class UserPreferences:
    session_id: str = ""
    watchlist: List[str] = field(default_factory=list)
    preferred_style: str = "balanced"  # technical | fundamental | balanced
    risk_tolerance: str = "moderate"  # conservative | moderate | aggressive
    last_session: str = ""

    def to_prompt_hint(self) -> str:
        """Generate a compact preference hint for SYSTEM_PROMPT."""
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
    path = MEMORY_DIR / f"{session_id}.json"
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
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    prefs.last_session = time.strftime("%Y-%m-%d %H:%M:%S")
    data = {
        "watchlist": prefs.watchlist,
        "preferred_style": prefs.preferred_style,
        "risk_tolerance": prefs.risk_tolerance,
        "last_session": prefs.last_session,
    }
    path = MEMORY_DIR / f"{prefs.session_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_preference(session_id: str, key: str, value: str) -> str:
    """Update a single preference. Returns confirmation message."""
    prefs = load_preferences(session_id)
    prefs.session_id = session_id
    valid_keys = {
        "watchlist": "list",
        "preferred_style": "str",
        "risk_tolerance": "str",
    }
    if key not in valid_keys:
        return f"不支持的偏好设置: {key}。可用: {', '.join(valid_keys.keys())}"

    if key == "watchlist":
        codes = [c.strip() for c in value.split(",") if c.strip()]
        # Validate codes are 6-digit
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
