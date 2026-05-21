"""Stock screening and recommendation engine.

Iterates over the built-in stock pool, fetches real-time data + indicators,
scores each stock by configurable strategies, and returns ranked results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from core.indicators import calc_all_indicators
from core.market_data import get_batch_quotes, search_stock

POOL_SIZE = 30  # how many stocks from the built-in list to screen


def _get_pool_codes() -> List[str]:
    """Return the screening pool — first POOL_SIZE stocks from the built-in list."""
    from core.market_data import _load_stock_list
    df = _load_stock_list()
    return df["code"].head(POOL_SIZE).tolist()


@dataclass
class StockScore:
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


def _score_reversal(s: StockScore) -> Tuple[float, str]:
    """Score for oversold reversal candidates. Higher = better."""
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
            score += 0.5  # still oversold but not reversed yet
        if s.vol_signal and "缩量" in s.vol_signal:
            score += 0.5
            reasons.append("缩量(抛压减轻)")
    return score, "；".join(reasons)


def _score_momentum(s: StockScore) -> Tuple[float, str]:
    """Score for trend-following (strong momentum)."""
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
    if s.change_pct > 0:
        score += s.change_pct * 20  # amplify positive momentum
        if s.change_pct > 3:
            reasons.append(f"今日涨幅{s.change_pct:+.1f}%")
    return score, "；".join(reasons)


def _score_value(s: StockScore) -> Tuple[float, str]:
    """Score for value investing (low valuation)."""
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


def _score_balanced(s: StockScore) -> Tuple[float, str]:
    """Composite score combining all perspectives."""
    r_score, r_reason = _score_reversal(s)
    m_score, m_reason = _score_momentum(s)
    v_score, v_reason = _score_value(s)
    all_reasons = [r for r in [r_reason, m_reason, v_reason] if r]
    total = r_score * 0.4 + m_score * 0.3 + v_score * 0.3
    return total, " | ".join(all_reasons)


def _score_dividend(s: StockScore) -> Tuple[float, str]:
    """Score for dividend/value stability (bank/utility heavy)."""
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


STRATEGIES: Dict[str, Tuple[str, Callable]] = {
    "超卖反弹": ("寻找 RSI 超卖 + MACD 拐头 的反弹机会", _score_reversal),
    "趋势强势": ("寻找均线多头排列 + 放量上涨的趋势股", _score_momentum),
    "低估值": ("寻找 PE/PB 偏低 + RSI 偏弱 的价值洼地", _score_value),
    "高股息": ("寻找 PE<10 + PB<1.5 的低估值蓝筹", _score_dividend),
    "综合评分": ("结合超卖反转 + 趋势动量 + 价值低估 的综合评分", _score_balanced),
}


def screen_stocks(strategy: str = "综合评分", pool_size: int = POOL_SIZE, top_k: int = 5) -> str:
    """Main entry: screen stocks by strategy, return formatted results."""
    strategy = strategy.strip()
    if strategy not in STRATEGIES:
        available = "、".join(STRATEGIES.keys())
        return f"不支持的策略「{strategy}」。可用策略：{available}"

    desc, scorer = STRATEGIES[strategy]
    pool = _get_pool_codes()[:pool_size]

    # Phase 1: batch fetch real-time quotes
    quotes = get_batch_quotes(pool)
    candidates: List[StockScore] = []
    for q in quotes:
        candidates.append(StockScore(
            code=q.code, name=q.name, price=q.price,
            change_pct=q.change_pct, pe=q.pe, pb=q.pb,
            has_data=True,
        ))

    # Phase 2: fetch indicators for top candidates (computationally heavier)
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
            pass

    # Phase 3: score
    for c in candidates:
        if c.has_data:
            score, reason = scorer(c)
            c.total_score = score
            if reason:
                c.reasons.append(reason)

    # Phase 4: rank and format
    candidates.sort(key=lambda x: x.total_score, reverse=True)
    top = candidates[:top_k]

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


def recommend_stock(style: str = "综合评分") -> str:
    """User-friendly entry point for 'recommend me a stock'."""
    style_map = {
        "短线": "超卖反弹",
        "趋势": "趋势强势",
        "价值": "低估值",
        "稳健": "高股息",
        "默认": "综合评分",
    }
    strategy = style_map.get(style, style_map.get("默认", "综合评分"))
    return screen_stocks(strategy=strategy, top_k=5)
