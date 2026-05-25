"""
选股筛选引擎（Stock Screener）
==============================
从内置股票池中，基于实时行情 + 技术指标 + 量化评分策略，筛选并排名候选股票。

支持的 5 种策略：
  1. 超卖反弹 —— RSI 超卖（<30）+ MACD 金叉 + 缩量（抛压减轻）
  2. 趋势强势 —— 均线多头排列 + MACD 金叉 + 放量上涨
  3. 低估值    —— PE/PB 偏低 + RSI 偏弱（价值洼地）
  4. 高股息    —— PE<10 + PB<1.5（低估值蓝筹，适合稳健型）
  5. 综合评分  —— 以上三维度的加权综合（超卖×0.4 + 趋势×0.3 + 价值×0.3）

筛选流程：
  1. 从内置池取 30 只股票
  2. 批量获取实时行情
  3. 逐个计算技术指标（取最近 60 天 K线）
  4. 按策略评分 → 排名 → 输出 Top 5
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from core.indicators import calc_all_indicators
from core.market_data import get_batch_quotes, search_stock

# 默认筛选池大小
POOL_SIZE = 30


def _get_pool_codes() -> List[str]:
    """获取筛选候选池：内置列表前 POOL_SIZE 只股票。"""
    from core.market_data import _load_stock_list
    df = _load_stock_list()
    return df["code"].head(POOL_SIZE).tolist()


@dataclass
class StockScore:
    """单只股票的评分结果。

    Attributes:
        code:             股票代码
        name:             股票名称
        price:            最新价
        change_pct:       今日涨跌幅(%)
        pe:               市盈率
        pb:               市净率
        total_score:      综合得分（越高越好）
        component_scores: 各维度分项得分
        reasons:          推荐理由（文本列表）
        has_data:         是否有实时行情数据
        has_indicators:   是否成功计算技术指标
        rsi:              RSI 数值
        macd_signal:      MACD 信号（金叉/死叉）
        ma_align:         均线排列（多头/空头）
        vol_signal:       量能信号（放量/缩量/正常）
    """
    code: str
    name: str
    price: float
    change_pct: float
    pe: float
    pb: float
    total_score: float = 0.0
    component_scores: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    has_data: bool = False
    has_indicators: bool = False
    rsi: float = 50.0
    macd_signal: str = ""
    ma_align: str = ""
    vol_signal: str = ""


# ═════════════════════════════════════════════════════════════
# 策略 1：超卖反弹
# ═════════════════════════════════════════════════════════════

def _score_reversal(s: StockScore) -> Tuple[float, str]:
    """评分：寻找超卖后反弹的标的。

    加分项：
      - RSI < 30（深度超卖）        → +3.0
      - RSI 30~40（偏弱）           → +1.5
      - MACD 金叉（拐头信号）        → +2.0
      - 均线仍空头（尚未反转但超卖）  → +0.5
      - 缩量（抛压减轻）             → +0.5
    """
    reasons: List[str] = []
    score = 0.0
    if s.has_indicators:
        if s.rsi < 30:
            score += 3.0
            reasons.append(f"RSI={s.rsi:.0f}(超卖)")
        elif s.rsi < 40:
            score += 1.5
            reasons.append(f"RSI={s.rsi:.0f}(偏弱)")
        if s.macd_signal and "金叉" in s.macd_signal:
            score += 2.0
            reasons.append("MACD金叉")
        if s.ma_align and "空头" in s.ma_align:
            score += 0.5
        if s.vol_signal and "缩量" in s.vol_signal:
            score += 0.5
            reasons.append("缩量(抛压减轻)")
    return score, "；".join(reasons)


# ═════════════════════════════════════════════════════════════
# 策略 2：趋势强势
# ═════════════════════════════════════════════════════════════

def _score_momentum(s: StockScore) -> Tuple[float, str]:
    """评分：寻找趋势走强的标的。

    加分项：
      - 均线多头排列        → +3.0
      - MACD 金叉           → +2.0
      - RSI 40~70（健康区域）→ +1.5
      - 放量（资金关注）     → +2.0
      - 今日涨幅贡献         → change_pct × 20
    """
    reasons: List[str] = []
    score = 0.0
    if s.has_indicators:
        if s.ma_align and "多头" in s.ma_align:
            score += 3.0
            reasons.append("均线多头排列")
        if s.macd_signal and "金叉" in s.macd_signal:
            score += 2.0
            reasons.append("MACD金叉")
        if 40 < s.rsi < 70:
            score += 1.5
            reasons.append(f"RSI={s.rsi:.0f}(健康区域)")
        if s.vol_signal and "放量" in s.vol_signal:
            score += 2.0
            reasons.append("放量(资金关注)")
    # 今日涨幅正向贡献
    if s.change_pct > 0:
        score += s.change_pct * 20
        if s.change_pct > 3:
            reasons.append(f"今日涨幅{s.change_pct:+.1f}%")
    return score, "；".join(reasons)


# ═════════════════════════════════════════════════════════════
# 策略 3：低估值
# ═════════════════════════════════════════════════════════════

def _score_value(s: StockScore) -> Tuple[float, str]:
    """评分：寻找估值偏低的标的。

    加分项：
      - PE 5~15（偏低）     → +2.5
      - PE ≤5（极低，需警惕）→ +1.5
      - PB < 1.0（破净）    → +2.0
      - PB 1.0~1.5（偏低）  → +1.0
      - RSI < 40（超卖区）  → +1.0
    """
    reasons: List[str] = []
    score = 0.0
    if s.pe > 5 and s.pe < 15:
        score += 2.5
        reasons.append(f"PE={s.pe:.1f}(偏低)")
    elif 0 < s.pe <= 5:
        score += 1.5
        reasons.append(f"PE={s.pe:.1f}(极低,留意行业)")
    if s.pb < 1.0:
        score += 2.0
        reasons.append(f"PB={s.pb:.2f}(破净)")
    elif s.pb < 1.5:
        score += 1.0
        reasons.append(f"PB={s.pb:.2f}(偏低)")
    if s.has_indicators and s.rsi < 40:
        score += 1.0
        reasons.append("RSI偏低(超卖区)")
    return score, "；".join(reasons)


# ═════════════════════════════════════════════════════════════
# 策略 4：综合评分（加权融合）
# ═════════════════════════════════════════════════════════════

def _score_balanced(s: StockScore) -> Tuple[float, str]:
    """评分：超卖×0.4 + 趋势×0.3 + 价值×0.3 的加权综合。

    设计意图：重反转 + 兼顾趋势和估值，避免单一维度偏误。
    """
    r_score, r_reason = _score_reversal(s)
    m_score, m_reason = _score_momentum(s)
    v_score, v_reason = _score_value(s)
    all_reasons = [r for r in [r_reason, m_reason, v_reason] if r]
    total = r_score * 0.4 + m_score * 0.3 + v_score * 0.3
    return total, " | ".join(all_reasons)


# ═════════════════════════════════════════════════════════════
# 策略 5：高股息/稳健型
# ═════════════════════════════════════════════════════════════

def _score_dividend(s: StockScore) -> Tuple[float, str]:
    """评分：寻找低估值蓝筹（适合高股息/稳健型投资者）。

    加分项：
      - PE < 10（低估值）  → +3.0
      - PB < 1.0（破净）   → +2.5
      - PB 1.0~1.5（偏低） → +1.5
      - 近期下跌（逢低关注）→ +1.0
    """
    reasons: List[str] = []
    score = 0.0
    if 0 < s.pe < 10:
        score += 3.0
        reasons.append(f"PE={s.pe:.1f}(低估值)")
    if s.pb < 1.0:
        score += 2.5
        reasons.append(f"PB={s.pb:.2f}(破净)")
    elif s.pb < 1.5:
        score += 1.5
        reasons.append(f"PB={s.pb:.2f}(偏低)")
    if s.has_indicators and s.change_pct < 0:
        score += 1.0
        reasons.append("近期调整(逢低关注)")
    return score, "；".join(reasons)


# ═════════════════════════════════════════════════════════════
# 策略注册表
# ═════════════════════════════════════════════════════════════

# 策略名 → (描述, 评分函数)
STRATEGIES: Dict[str, Tuple[str, Callable]] = {
    "超卖反弹": ("寻找 RSI 超卖 + MACD 拐头 的反弹机会", _score_reversal),
    "趋势强势": ("寻找均线多头排列 + 放量上涨的趋势股", _score_momentum),
    "低估值": ("寻找 PE/PB 偏低 + RSI 偏弱 的价值洼地", _score_value),
    "高股息": ("寻找 PE<10 + PB<1.5 的低估值蓝筹", _score_dividend),
    "综合评分": ("结合超卖反转 + 趋势动量 + 价值低估 的综合评分", _score_balanced),
}


# ═════════════════════════════════════════════════════════════
# 主入口：选股筛选
# ═════════════════════════════════════════════════════════════

def screen_stocks(strategy: str = "综合评分", pool_size: int = POOL_SIZE, top_k: int = 5) -> str:
    """按指定策略筛选股票并返回格式化结果。

    执行阶段：
      Phase 1 — 批量获取实时行情（快）
      Phase 2 — 逐个计算技术指标（慢，约 0.5s/只）
      Phase 3 — 策略评分
      Phase 4 — 排名 + 格式化输出

    Args:
        strategy:  策略名称（见 STRATEGIES 的 keys）
        pool_size: 候选池大小
        top_k:     返回 Top K 结果

    Returns:
        格式化的选股报告文本
    """
    strategy = strategy.strip()
    if strategy not in STRATEGIES:
        available = "、".join(STRATEGIES.keys())
        return f"不支持的策略「{strategy}」。可用策略：{available}"

    desc, scorer = STRATEGIES[strategy]
    pool = _get_pool_codes()[:pool_size]

    # Phase 1：批量获取实时行情
    quotes = get_batch_quotes(pool)
    candidates: List[StockScore] = []
    for q in quotes:
        candidates.append(StockScore(
            code=q.code, name=q.name, price=q.price,
            change_pct=q.change_pct, pe=q.pe, pb=q.pb,
            has_data=True,
        ))

    # Phase 2：逐个计算技术指标（计算密集，不并行以节约资源）
    for c in candidates:
        if not c.has_data:
            continue
        try:
            bundle = calc_all_indicators(c.code, days=60)
            c.has_indicators = True
            c.rsi = float(str(bundle.latest.get("RSI", "50")))
            c.macd_signal = str(bundle.latest.get("MACD信号", ""))
            c.ma_align = bundle.recent.get("MA排列", "")
            c.vol_signal = str(bundle.latest.get("量能信号", ""))
        except Exception:
            pass  # 单只股票指标计算失败不影响整体

    # Phase 3：策略评分
    for c in candidates:
        if c.has_data:
            score, reason = scorer(c)
            c.total_score = score
            if reason:
                c.reasons.append(reason)

    # Phase 4：按得分降序排列，取 Top K
    candidates.sort(key=lambda x: x.total_score, reverse=True)
    top = candidates[:top_k]

    # 格式化输出
    lines = [f"选股策略：{strategy} — {desc}\n"]
    lines.append(f"从 {len(candidates)} 只股票中筛选，Top {top_k} 结果：\n")

    for i, c in enumerate(top):
        pe_str = f"PE={c.pe:.1f}" if c.pe > 0 else "PE=亏损"
        lines.append(f"#{i + 1}  {c.name}({c.code})  最新价 {c.price:.2f}  "
                     f"涨跌幅 {c.change_pct:+.2f}%  {pe_str}  PB={c.pb:.2f}")
        if c.reasons:
            lines.append(f"    推荐理由：{c.reasons[0]}")
        if c.has_indicators:
            indicators_note = f"RSI={c.rsi:.0f}"
            if c.macd_signal:
                indicators_note += f" MACD:{c.macd_signal}"
            if c.ma_align:
                indicators_note += f" 均线:{c.ma_align}"
            lines.append(f"    技术面：{indicators_note}")
        lines.append("")

    lines.append("⚠️ 以上为量化筛选结果，不构成投资建议。请结合个人风险偏好与市场环境判断。")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════
# 推荐入口：用户友好的选股推荐
# ═════════════════════════════════════════════════════════════

def recommend_stock(style: str = "综合评分") -> str:
    """根据投资风格推荐股票（用户友好封装）。

    风格映射：
      短线 → 超卖反弹（找反弹机会）
      趋势 → 趋势强势（顺势做多）
      价值 → 低估值（捡便宜）
      稳健 → 高股息（蓝筹低估值）
      默认 → 综合评分

    Args:
        style: 投资风格（中文）

    Returns:
        格式化的推荐报告文本
    """
    style_map = {
        "短线": "超卖反弹",
        "趋势": "趋势强势",
        "价值": "低估值",
        "稳健": "高股息",
        "默认": "综合评分",
    }
    strategy = style_map.get(style, style_map.get("默认", "综合评分"))
    return screen_stocks(strategy=strategy, top_k=5)
