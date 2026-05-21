"""Technical indicators computed from daily K-line data. Pure numpy, zero external deps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from core.market_data import KlineBar, get_daily_kline


@dataclass
class IndicatorBundle:
    code: str
    name: str
    latest: Dict[str, float]
    recent: Dict[str, str]

    def format(self) -> str:
        lines = [f"{self.name}({self.code}) 技术指标分析：\n"]
        lines.append("── 均线系统 ──")
        for k in ["MA5", "MA10", "MA20", "MA60"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]:.2f}")
        lines.append("── 趋势指标 ──")
        for k in ["MACD_DIF", "MACD_DEA", "MACD_HIST", "MACD信号"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]}")
        lines.append("── 震荡指标 ──")
        for k in ["RSI", "RSI信号", "KDJ_K", "KDJ_D", "KDJ_J", "KDJ信号"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]}")
        lines.append("── 布林带 ──")
        for k in ["BOLL_UPPER", "BOLL_MID", "BOLL_LOWER", "BOLL_WIDTH", "BOLL位置"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]}")
        lines.append("── 量价关系 ──")
        for k in ["VOL_RATIO", "量能信号"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]}")
        lines.append("\n── 综合建议 ──")
        lines.append("⚠️ 指标仅供参考，不构成投资建议。请结合基本面与市场环境综合判断。")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# Moving Averages
# ═══════════════════════════════════════════════════════════

def _ema(data: np.ndarray, period: int) -> np.ndarray:
    result = np.zeros_like(data)
    result[0] = data[0]
    multiplier = 2.0 / (period + 1)
    for i in range(1, len(data)):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def compute_ma(close: np.ndarray) -> Dict[str, np.ndarray]:
    ma = {}
    for p in [5, 10, 20, 60]:
        if len(close) >= p:
            ma[f"MA{p}"] = np.convolve(close, np.ones(p) / p, mode="valid")
    ma["EMA12"] = _ema(close, 12)
    ma["EMA26"] = _ema(close, 26)
    return ma


# ═══════════════════════════════════════════════════════════
# MACD
# ═══════════════════════════════════════════════════════════

def compute_macd(close: np.ndarray) -> Dict[str, np.ndarray]:
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    hist = 2 * (dif - dea)
    return {"MACD_DIF": dif, "MACD_DEA": dea, "MACD_HIST": hist}


# ═══════════════════════════════════════════════════════════
# RSI
# ═══════════════════════════════════════════════════════════

def compute_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.zeros_like(close)
    avg_loss = np.zeros_like(close)
    avg_gain[period] = gain[: period + 1].mean()
    avg_loss[period] = loss[: period + 1].mean()
    for i in range(period + 1, len(close)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
    return 100.0 - 100.0 / (1.0 + rs)


# ═══════════════════════════════════════════════════════════
# BOLL (Bollinger Bands)
# ═══════════════════════════════════════════════════════════

def compute_boll(close: np.ndarray, period: int = 20, std_mult: float = 2.0) -> Dict[str, np.ndarray]:
    mid = np.zeros_like(close)
    upper = np.zeros_like(close)
    lower = np.zeros_like(close)
    for i in range(period - 1, len(close)):
        window = close[i - period + 1 : i + 1]
        mid[i] = window.mean()
        std = window.std()
        upper[i] = mid[i] + std_mult * std
        lower[i] = mid[i] - std_mult * std
    return {"BOLL_UPPER": upper, "BOLL_MID": mid, "BOLL_LOWER": lower}


# ═══════════════════════════════════════════════════════════
# KDJ
# ═══════════════════════════════════════════════════════════

def compute_kdj(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 9) -> Dict[str, np.ndarray]:
    n = len(close)
    k = np.zeros(n)
    d = np.zeros(n)
    j = np.zeros(n)
    k[period - 1] = 50.0
    d[period - 1] = 50.0
    for i in range(period - 1, n):
        hh = high[i - period + 1 : i + 1].max()
        ll = low[i - period + 1 : i + 1].min()
        rsv = ((close[i] - ll) / (hh - ll)) * 100 if hh != ll else 50.0
        k[i] = 2.0 / 3.0 * k[i - 1] + 1.0 / 3.0 * rsv
        d[i] = 2.0 / 3.0 * d[i - 1] + 1.0 / 3.0 * k[i]
        j[i] = 3.0 * k[i] - 2.0 * d[i]
    return {"KDJ_K": k, "KDJ_D": d, "KDJ_J": j}


# ═══════════════════════════════════════════════════════════
# Volume ratio
# ═══════════════════════════════════════════════════════════

def compute_vol_ratio(volume: np.ndarray, period: int = 5) -> np.ndarray:
    ma = np.zeros_like(volume)
    for i in range(period - 1, len(volume)):
        ma[i] = volume[i - period + 1 : i + 1].mean()
    return np.divide(volume, ma, out=np.ones_like(volume), where=ma > 0)


# ═══════════════════════════════════════════════════════════
# K-line patterns
# ═══════════════════════════════════════════════════════════

def detect_patterns(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> List[str]:
    """Detect candlestick patterns in the most recent bars."""
    patterns: List[str] = []
    n = len(close)
    if n < 3:
        return patterns

    body = close - open_
    upper_wick = high - np.maximum(open_, close)
    lower_wick = np.minimum(open_, close) - low
    body_abs = np.abs(body)

    # Helper: check last N bars
    def last(idx: int = -1):
        return body[idx], upper_wick[idx], lower_wick[idx], body_abs[idx]

    b, uw, lw, ba = last(-1)
    range_val = high[-1] - low[-1]

    # Hammer (锤子线): small body, long lower wick, tiny upper wick
    if range_val > 0:
        if lw > 2 * ba and uw < 0.3 * ba and ba > 0:
            patterns.append("锤子线（看涨反转信号）")
        # Inverted hammer
        if uw > 2 * ba and lw < 0.3 * ba and ba > 0:
            patterns.append("倒锤子线（潜在反转信号）")
        # Doji (十字星)
        if ba < 0.1 * range_val:
            patterns.append("十字星（多空均衡）")

    # Bullish engulfing (看涨吞没)
    if n >= 2:
        b0, _, _, ba0 = body[-2], 0, 0, abs(body[-2])
        if body[-2] < 0 < body[-1] and abs(body[-1]) > 1.5 * abs(body[-2]):
            if close[-1] > open_[-2] and open_[-1] < close[-2]:
                patterns.append("看涨吞没（强烈反转信号）")

    # Bearish engulfing (看跌吞没)
    if n >= 2:
        if body[-2] > 0 > body[-1] and abs(body[-1]) > 1.5 * abs(body[-2]):
            if close[-1] < open_[-2] and open_[-1] > close[-2]:
                patterns.append("看跌吞没（强烈反转信号）")

    # Three soldiers / crows (三兵/三鸦)
    if n >= 3:
        if all(body[-3:][i] > 0 for i in range(3)):
            if all(close[-3:][i] > close[-3:][i - 1] for i in range(1, 3)):
                patterns.append("三连阳（持续看涨）")
        if all(body[-3:][i] < 0 for i in range(3)):
            if all(close[-3:][i] < close[-3:][i - 1] for i in range(1, 3)):
                patterns.append("三连阴（持续看跌）")

    return patterns


# ═══════════════════════════════════════════════════════════
# Main calculator
# ═══════════════════════════════════════════════════════════

def calc_all_indicators(code: str, days: int = 90) -> IndicatorBundle:
    bars = get_daily_kline(code, days=days)
    if not bars:
        return IndicatorBundle(code=code, name=code, latest={}, recent={})

    q = __import__("core.market_data", fromlist=["get_realtime_quote"]).get_realtime_quote(code)
    name = q.name if q else code

    close = np.array([b.close for b in bars], dtype=np.float64)
    open_ = np.array([b.open for b in bars], dtype=np.float64)
    high = np.array([b.high for b in bars], dtype=np.float64)
    low = np.array([b.low for b in bars], dtype=np.float64)
    volume = np.array([b.volume for b in bars], dtype=np.float64)

    latest: Dict[str, float] = {}
    recent: Dict[str, str] = {}

    # MA
    ma = compute_ma(close)
    for k, v in ma.items():
        if len(v) > 0:
            latest[k] = float(v[-1])
    # MA alignment
    if "MA5" in latest and "MA20" in latest:
        if latest["MA5"] > latest["MA20"]:
            recent["MA排列"] = "多头排列（短中期向好）"
        else:
            recent["MA排列"] = "空头排列（短中期偏弱）"

    # MACD
    macd = compute_macd(close)
    latest["MACD_DIF"] = float(round(macd["MACD_DIF"][-1], 4))
    latest["MACD_DEA"] = float(round(macd["MACD_DEA"][-1], 4))
    latest["MACD_HIST"] = float(round(macd["MACD_HIST"][-1], 4))
    if macd["MACD_DIF"][-1] > macd["MACD_DEA"][-1]:
        latest["MACD信号"] = "金叉（看涨）"
    else:
        latest["MACD信号"] = "死叉（看跌）"

    # RSI
    rsi = compute_rsi(close)
    rsi_val = float(rsi[-1])
    latest["RSI"] = f"{rsi_val:.1f}"
    if rsi_val > 70:
        latest["RSI信号"] = "超买区域，注意回调风险"
    elif rsi_val < 30:
        latest["RSI信号"] = "超卖区域，可能反弹"
    else:
        latest["RSI信号"] = "中性区间"

    # BOLL
    boll = compute_boll(close)
    latest["BOLL_UPPER"] = float(round(boll["BOLL_UPPER"][-1], 2))
    latest["BOLL_MID"] = float(round(boll["BOLL_MID"][-1], 2))
    latest["BOLL_LOWER"] = float(round(boll["BOLL_LOWER"][-1], 2))
    width = (boll["BOLL_UPPER"][-1] - boll["BOLL_LOWER"][-1]) / boll["BOLL_MID"][-1] * 100
    latest["BOLL_WIDTH"] = float(round(width, 2))
    cp = close[-1]
    if cp >= boll["BOLL_UPPER"][-1]:
        latest["BOLL位置"] = "触及上轨（压力位）"
    elif cp <= boll["BOLL_LOWER"][-1]:
        latest["BOLL位置"] = "触及下轨（支撑位）"
    else:
        latest["BOLL位置"] = "通道内运行"

    # KDJ
    kdj = compute_kdj(high, low, close)
    latest["KDJ_K"] = float(round(kdj["KDJ_K"][-1], 2))
    latest["KDJ_D"] = float(round(kdj["KDJ_D"][-1], 2))
    latest["KDJ_J"] = float(round(kdj["KDJ_J"][-1], 2))
    k_val = kdj["KDJ_K"][-1]
    d_val = kdj["KDJ_D"][-1]
    if k_val > 80 and d_val > 80:
        latest["KDJ信号"] = "超买区"
    elif k_val < 20 and d_val < 20:
        latest["KDJ信号"] = "超卖区"
    elif k_val > d_val:
        latest["KDJ信号"] = "金叉区域"
    else:
        latest["KDJ信号"] = "死叉区域"

    # Volume
    vol_ratio = compute_vol_ratio(volume)
    latest["VOL_RATIO"] = float(round(vol_ratio[-1], 2))
    if latest["VOL_RATIO"] > 1.5:
        latest["量能信号"] = "放量（交投活跃）"
    elif latest["VOL_RATIO"] < 0.5:
        latest["量能信号"] = "缩量（交投清淡）"
    else:
        latest["量能信号"] = "正常"

    # Patterns
    patterns = detect_patterns(open_, high, low, close)
    if patterns:
        for i, p in enumerate(patterns):
            recent[f"形态{i + 1}"] = p
    else:
        recent["形态"] = "近期无明显经典形态"

    return IndicatorBundle(code=code, name=name, latest=latest, recent=recent)
