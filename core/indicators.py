"""
技术指标计算模块（Technical Indicators）
=========================================
纯 NumPy 实现，零外部依赖。基于日K线数据计算以下指标：

均线系统：
  - MA5/MA10/MA20/MA60        : 简单移动平均线
  - EMA12/EMA26                : 指数移动平均线（MACD 子组件）
趋势指标：
  - MACD（DIF/DEA/柱线）+ 金叉/死叉判断
震荡指标：
  - RSI（14 日相对强弱指标）+ 超买/超卖判断
  - KDJ（9 日随机指标）+ 金叉/死叉区域判断
通道指标：
  - BOLL（20 日布林带）：上轨/中轨/下轨 + 宽度 + 价格位置
量价关系：
  - 量比（5 日均量对比）+ 放量/缩量判断
K线形态：
  - 锤子线 / 倒锤子线 / 十字星 / 看涨吞没 / 看跌吞没 / 三连阳 / 三连阴
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Union

import numpy as np

from core.market_data import KlineBar, get_daily_kline


@dataclass
class IndicatorBundle:
    """技术指标计算结果包。

    Attributes:
        code:   股票代码
        name:   股票名称
        latest: 最新一期的指标值（key: 指标名 → value: 数值或定性文本）
        recent: 近期定性判断（key: 判据名 → value: 文字描述）
    """
    code: str
    name: str
    latest: Dict[str, Union[float, str]]   # MACD信号/RSI信号等为中文描述（str）
    recent: Dict[str, str]

    def format(self) -> str:
        """将指标包格式化为可读的文本报告。"""
        lines = [f"{self.name}({self.code}) 技术指标分析：\n"]
        # 均线系统
        lines.append("── 均线系统 ──")
        for k in ["MA5", "MA10", "MA20", "MA60"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]:.2f}")
        # 趋势指标
        lines.append("── 趋势指标 ──")
        for k in ["MACD_DIF", "MACD_DEA", "MACD_HIST", "MACD信号"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]}")
        # 震荡指标
        lines.append("── 震荡指标 ──")
        for k in ["RSI", "RSI信号", "KDJ_K", "KDJ_D", "KDJ_J", "KDJ信号"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]}")
        # 布林带
        lines.append("── 布林带 ──")
        for k in ["BOLL_UPPER", "BOLL_MID", "BOLL_LOWER", "BOLL_WIDTH", "BOLL位置"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]}")
        # 量价关系
        lines.append("── 量价关系 ──")
        for k in ["VOL_RATIO", "量能信号"]:
            if k in self.latest:
                lines.append(f"  {k}: {self.latest[k]}")
        lines.append("\n── 综合建议 ──")
        lines.append("⚠️ 指标仅供参考，不构成投资建议。请结合基本面与市场环境综合判断。")
        return "\n".join(lines)


# ═════════════════════════════════════════════════════════════
# 指数移动平均线（EMA）—— MACD / 其他指标的基础组件
# ═════════════════════════════════════════════════════════════

def _ema(data: np.ndarray, period: int) -> np.ndarray:
    """计算指数移动平均线。

    公式：EMA_t = (Price_t - EMA_{t-1}) × multiplier + EMA_{t-1}
    其中 multiplier = 2 / (period + 1)

    Args:
        data:   价格序列（close 或其他）
        period: EMA 周期

    Returns:
        与输入等长的 EMA 序列（首个值用 data[0] 初始化）
    """
    result = np.zeros_like(data)
    result[0] = data[0]
    multiplier = 2.0 / (period + 1)
    for i in range(1, len(data)):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


# ═════════════════════════════════════════════════════════════
# 简单移动平均线（MA）
# ═════════════════════════════════════════════════════════════

def compute_ma(close: np.ndarray) -> Dict[str, np.ndarray]:
    """计算多周期简单移动平均线（MA5/MA10/MA20/MA60）及 EMA12/EMA26。

    Args:
        close: 收盘价序列

    Returns:
        字典 {周期名: MA 序列}，MA 序列比输入短 (period - 1) 个元素
    """
    ma = {}
    for p in [5, 10, 20, 60]:
        if len(close) >= p:
            # 等权卷积 → SMA
            ma[f"MA{p}"] = np.convolve(close, np.ones(p) / p, mode="valid")
    # MACD 所需的 EMA 基序列
    ma["EMA12"] = _ema(close, 12)
    ma["EMA26"] = _ema(close, 26)
    return ma


# ═════════════════════════════════════════════════════════════
# MACD（指数平滑异同移动平均线）
# ═════════════════════════════════════════════════════════════

def compute_macd(close: np.ndarray) -> Dict[str, np.ndarray]:
    """计算 MACD 指标。

    DIF  = EMA12 - EMA26                   （快慢线差值）
    DEA  = EMA9(DIF)                        （信号线）
    HIST = 2 × (DIF - DEA)                   （柱线，放大两倍便于观察）

    Returns:
        {"MACD_DIF": ..., "MACD_DEA": ..., "MACD_HIST": ...}
    """
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    hist = 2 * (dif - dea)
    return {"MACD_DIF": dif, "MACD_DEA": dea, "MACD_HIST": hist}


# ═════════════════════════════════════════════════════════════
# RSI（相对强弱指标）
# ═════════════════════════════════════════════════════════════

def compute_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """计算 RSI（Wilder's Smoothing Method）。

    公式：RSI = 100 - 100 / (1 + RS)
    其中 RS = avg_gain / avg_loss（使用 Wilder 指数平滑）

    Args:
        close:  收盘价序列
        period: 计算周期（默认 14）

    Returns:
        与输入等长的 RSI 序列（前 period 个值为 0）
    """
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_gain = np.zeros_like(close)
    avg_loss = np.zeros_like(close)
    # 首个平滑值使用简单平均初始化
    avg_gain[period] = gain[: period + 1].mean()
    avg_loss[period] = loss[: period + 1].mean()
    # 后续用 Wilder 指数平滑递推
    for i in range(period + 1, len(close)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period

    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
    return 100.0 - 100.0 / (1.0 + rs)


# ═════════════════════════════════════════════════════════════
# BOLL（布林带）
# ═════════════════════════════════════════════════════════════

def compute_boll(close: np.ndarray, period: int = 20, std_mult: float = 2.0) -> Dict[str, np.ndarray]:
    """计算布林带（Bollinger Bands）。

    中轨 = MA(period)
    上轨 = 中轨 + std_mult × 标准差
    下轨 = 中轨 - std_mult × 标准差

    Args:
        close:    收盘价序列
        period:   均线周期（默认 20）
        std_mult: 标准差倍数（默认 2.0）

    Returns:
        {"BOLL_UPPER": 上轨, "BOLL_MID": 中轨, "BOLL_LOWER": 下轨}
    """
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


# ═════════════════════════════════════════════════════════════
# KDJ（随机指标）
# ═════════════════════════════════════════════════════════════

def compute_kdj(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 9) -> Dict[str, np.ndarray]:
    """计算 KDJ 随机指标。

    RSV = (close - period_low) / (period_high - period_low) × 100
    K   = 2/3 × K_prev + 1/3 × RSV
    D   = 2/3 × D_prev + 1/3 × K
    J   = 3K - 2D

    Args:
        high/low/close: 价格序列
        period:         计算周期（默认 9）

    Returns:
        {"KDJ_K": K值, "KDJ_D": D值, "KDJ_J": J值}
    """
    n = len(close)
    k = np.zeros(n)
    d = np.zeros(n)
    j = np.zeros(n)
    # 初始值设为 50（中性）
    k[period - 1] = 50.0
    d[period - 1] = 50.0
    for i in range(period - 1, n):
        hh = high[i - period + 1 : i + 1].max()
        ll = low[i - period + 1 : i + 1].min()
        # RSV：当前收盘在最近 period 日内的相对位置
        rsv = ((close[i] - ll) / (hh - ll)) * 100 if hh != ll else 50.0
        k[i] = 2.0 / 3.0 * k[i - 1] + 1.0 / 3.0 * rsv
        d[i] = 2.0 / 3.0 * d[i - 1] + 1.0 / 3.0 * k[i]
        j[i] = 3.0 * k[i] - 2.0 * d[i]
    return {"KDJ_K": k, "KDJ_D": d, "KDJ_J": j}


# ═════════════════════════════════════════════════════════════
# 量比（Volume Ratio）
# ═════════════════════════════════════════════════════════════

def compute_vol_ratio(volume: np.ndarray, period: int = 5) -> np.ndarray:
    """计算量比 = 当日成交量 / 近 N 日均量。

    Args:
        volume: 成交量序列
        period: 均量周期（默认 5 日）

    Returns:
        量比序列（首 period-1 个值为 1.0）
    """
    ma = np.zeros_like(volume)
    for i in range(period - 1, len(volume)):
        ma[i] = volume[i - period + 1 : i + 1].mean()
    return np.divide(volume, ma, out=np.ones_like(volume), where=ma > 0)


# ═════════════════════════════════════════════════════════════
# K线形态识别
# ═════════════════════════════════════════════════════════════

def detect_patterns(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> List[str]:
    """检测最近几根 K 线的经典形态。

    支持的形态：
      - 锤子线（看涨反转）  : 长下影 + 小实体 + 短上影
      - 倒锤子线（潜在反转）: 长上影 + 小实体 + 短下影
      - 十字星（多空均衡）  : 实体极小（< 振幅的 10%）
      - 看涨吞没（强烈反转）: 阴线+阳线，阳线实体包住阴线
      - 看跌吞没（强烈反转）: 阳线+阴线，阴线实体包住阳线
      - 三连阳（持续看涨）  : 连续 3 根阳线 + 收盘递增
      - 三连阴（持续看跌）  : 连续 3 根阴线 + 收盘递减
    """
    patterns: List[str] = []
    n = len(close)
    if n < 3:
        return patterns

    # 计算 K 线组件
    body = close - open_                         # 实体（正=阳线，负=阴线）
    upper_wick = high - np.maximum(open_, close)  # 上影线
    lower_wick = np.minimum(open_, close) - low   # 下影线
    body_abs = np.abs(body)                       # 实体绝对值

    def last(idx: int = -1):
        """便捷函数：取第 idx 根 K 线的组件。"""
        return body[idx], upper_wick[idx], lower_wick[idx], body_abs[idx]

    b, uw, lw, ba = last(-1)
    range_val = high[-1] - low[-1]  # 最新 K 线的振幅

    # 锤子线：下影线长（>2倍实体），上影线极短，有一定实体
    if range_val > 0:
        if lw > 2 * ba and uw < 0.3 * ba and ba > 0:
            patterns.append("锤子线（看涨反转信号）")
        # 倒锤子线：上影线长（>2倍实体），下影线极短
        if uw > 2 * ba and lw < 0.3 * ba and ba > 0:
            patterns.append("倒锤子线（潜在反转信号）")
        # 十字星：实体远小于振幅（< 10%）
        if ba < 0.1 * range_val:
            patterns.append("十字星（多空均衡）")

    # 看涨吞没：前阴后阳，阳线实体 > 1.5×阴线实体，且价格区间包住前一根
    if n >= 2:
        if body[-2] < 0 < body[-1] and abs(body[-1]) > 1.5 * abs(body[-2]):
            if close[-1] > open_[-2] and open_[-1] < close[-2]:
                patterns.append("看涨吞没（强烈反转信号）")

    # 看跌吞没：前阳后阴，阴线实体 > 1.5×阳线实体，且价格区间包住前一根
    if n >= 2:
        if body[-2] > 0 > body[-1] and abs(body[-1]) > 1.5 * abs(body[-2]):
            if close[-1] < open_[-2] and open_[-1] > close[-2]:
                patterns.append("看跌吞没（强烈反转信号）")

    # 三连阳：连续 3 根阳线，收盘价递增
    if n >= 3:
        if all(body[-3:][i] > 0 for i in range(3)):
            if all(close[-3:][i] > close[-3:][i - 1] for i in range(1, 3)):
                patterns.append("三连阳（持续看涨）")
        # 三连阴：连续 3 根阴线，收盘价递减
        if all(body[-3:][i] < 0 for i in range(3)):
            if all(close[-3:][i] < close[-3:][i - 1] for i in range(1, 3)):
                patterns.append("三连阴（持续看跌）")

    return patterns


# ═════════════════════════════════════════════════════════════
# 主计算入口：一次性计算全部技术指标
# ═════════════════════════════════════════════════════════════

def calc_all_indicators(code: str, days: int = 90) -> IndicatorBundle:
    """对指定股票计算全部技术指标，返回 IndicatorBundle。

    计算流程：
      1. 获取日K线数据
      2. 提取 OHLCV 的 NumPy 数组
      3. 依次计算 MA / MACD / RSI / BOLL / KDJ / 量比
      4. 为每个指标生成最新量化值 + 定性判断
      5. 检测 K 线形态

    Args:
        code: 6 位股票代码
        days: 拉取的 K 线天数（默认 90 天）

    Returns:
        IndicatorBundle（数据不足时返回空 latest/recent）
    """
    bars = get_daily_kline(code, days=days)
    if not bars:
        return IndicatorBundle(code=code, name=code, latest={}, recent={})

    # 获取股票名称（用于展示）
    q = __import__("core.market_data", fromlist=["get_realtime_quote"]).get_realtime_quote(code)
    name = q.name if q else code

    # 提取 OHLCV 为 NumPy 数组
    close = np.array([b.close for b in bars], dtype=np.float64)
    open_ = np.array([b.open for b in bars], dtype=np.float64)
    high = np.array([b.high for b in bars], dtype=np.float64)
    low = np.array([b.low for b in bars], dtype=np.float64)
    volume = np.array([b.volume for b in bars], dtype=np.float64)

    latest: Dict[str, Union[float, str]] = {}
    recent: Dict[str, str] = {}

    # ── 均线系统 ──
    ma = compute_ma(close)
    for k, v in ma.items():
        if len(v) > 0:
            latest[k] = float(v[-1])
    # 均线排列判断（多头/空头）
    if "MA5" in latest and "MA20" in latest:
        if float(latest["MA5"]) > float(latest["MA20"]):
            recent["MA排列"] = "多头排列（短中期向好）"
        else:
            recent["MA排列"] = "空头排列（短中期偏弱）"

    # ── MACD ──
    macd = compute_macd(close)
    latest["MACD_DIF"] = float(round(macd["MACD_DIF"][-1], 4))
    latest["MACD_DEA"] = float(round(macd["MACD_DEA"][-1], 4))
    latest["MACD_HIST"] = float(round(macd["MACD_HIST"][-1], 4))
    # 金叉/死叉：DIF 上穿/下穿 DEA
    if macd["MACD_DIF"][-1] > macd["MACD_DEA"][-1]:
        latest["MACD信号"] = "金叉（看涨）"
    else:
        latest["MACD信号"] = "死叉（看跌）"

    # ── RSI ──
    rsi = compute_rsi(close)
    rsi_val = float(rsi[-1])
    latest["RSI"] = f"{rsi_val:.1f}"
    if rsi_val > 70:
        latest["RSI信号"] = "超买区域，注意回调风险"
    elif rsi_val < 30:
        latest["RSI信号"] = "超卖区域，可能反弹"
    else:
        latest["RSI信号"] = "中性区间"

    # ── 布林带 ──
    boll = compute_boll(close)
    latest["BOLL_UPPER"] = float(round(boll["BOLL_UPPER"][-1], 2))
    latest["BOLL_MID"] = float(round(boll["BOLL_MID"][-1], 2))
    latest["BOLL_LOWER"] = float(round(boll["BOLL_LOWER"][-1], 2))
    # 带宽 = (上轨 - 下轨) / 中轨 × 100%
    width = (boll["BOLL_UPPER"][-1] - boll["BOLL_LOWER"][-1]) / boll["BOLL_MID"][-1] * 100
    latest["BOLL_WIDTH"] = float(round(width, 2))
    # 价格在布林带中的位置
    cp = close[-1]
    if cp >= boll["BOLL_UPPER"][-1]:
        latest["BOLL位置"] = "触及上轨（压力位）"
    elif cp <= boll["BOLL_LOWER"][-1]:
        latest["BOLL位置"] = "触及下轨（支撑位）"
    else:
        latest["BOLL位置"] = "通道内运行"

    # ── KDJ ──
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

    # ── 量能 ──
    vol_ratio = compute_vol_ratio(volume)
    latest["VOL_RATIO"] = float(round(vol_ratio[-1], 2))
    if float(latest["VOL_RATIO"]) > 1.5:
        latest["量能信号"] = "放量（交投活跃）"
    elif float(latest["VOL_RATIO"]) < 0.5:
        latest["量能信号"] = "缩量（交投清淡）"
    else:
        latest["量能信号"] = "正常"

    # ── K线形态 ──
    patterns = detect_patterns(open_, high, low, close)
    if patterns:
        for i, p in enumerate(patterns):
            recent[f"形态{i + 1}"] = p
    else:
        recent["形态"] = "近期无明显经典形态"

    return IndicatorBundle(code=code, name=name, latest=latest, recent=recent)
