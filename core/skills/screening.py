"""
选股推荐 Skill（ScreeningSkill）
=================================
多策略选股引擎，对候选池逐个评分排名。

编排的工具：
  1. 获取候选池（内置38只）
  2. 批量行情 + 逐个技术指标
  3. 5种策略评分
  4. 排名 + Top K 推荐

输出：SkillReport（策略说明 / 侯选池 / Top 5 排名 / 推荐理由）
"""

from __future__ import annotations

from typing import List

from core.screener import (
    POOL_SIZE,
    STRATEGIES,
    StockScore,
    _get_pool_codes,
    _score_reversal,
    _score_momentum,
    _score_value,
    _score_dividend,
    _score_balanced,
)
from core.indicators import calc_all_indicators
from core.market_data import get_batch_quotes
from core.skills.base import BaseSkill, ReportSection, SkillReport

# 策略→评分函数映射（与 screener.py 一致）
_SCORER_MAP = {
    "超卖反弹": _score_reversal,
    "趋势强势": _score_momentum,
    "低估值": _score_value,
    "高股息": _score_dividend,
    "综合评分": _score_balanced,
}


class ScreeningSkill(BaseSkill):
    name = "screening"
    description = (
        "按策略筛选并推荐股票。支持5种策略：超卖反弹/趋势强势/低估值/高股息/综合评分。"
        "从候选池中按策略评分，返回Top 5推荐及推荐理由。"
    )
    parameters = {
        "strategy": {"type": "string", "description": "策略名称：超卖反弹/趋势强势/低估值/高股息/综合评分，默认综合评分"},
    }

    def execute(self, strategy: str = "综合评分") -> SkillReport:
        strategy = strategy.strip()
        if strategy not in STRATEGIES:
            available = "、".join(STRATEGIES.keys())
            return SkillReport(
                skill_name=self.name,
                title="选股推荐",
                sections=[ReportSection(heading="错误",
                    content=f"不支持的策略「{strategy}」。可用策略：{available}")],
                summary="策略参数无效。",
            )

        desc, scorer = STRATEGIES[strategy]
        pool = _get_pool_codes()[:POOL_SIZE]

        # Phase 1：批量行情
        quotes = get_batch_quotes(pool)
        candidates: List[StockScore] = []
        for q in quotes:
            candidates.append(StockScore(
                code=q.code, name=q.name, price=q.price,
                change_pct=q.change_pct, pe=q.pe, pb=q.pb,
                has_data=True,
            ))

        # Phase 2：逐个技术指标
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

        # Phase 3：评分
        for c in candidates:
            if c.has_data:
                score, reason = scorer(c)
                c.total_score = score
                if reason:
                    c.reasons.append(reason)

        # Phase 4：排名
        candidates.sort(key=lambda x: x.total_score, reverse=True)
        top = candidates[:5]

        # ── 构建报告 ──
        sections: List[ReportSection] = []

        # 策略说明
        sections.append(ReportSection(
            heading="策略说明",
            content=f"策略：{strategy}\n逻辑：{desc}\n候选池：{len(candidates)}只A股",
        ))

        # Top 5 排名
        top_lines: List[str] = []
        for i, c in enumerate(top):
            pe_str = f"PE={c.pe:.1f}" if c.pe > 0 else "PE=亏损"
            line = (
                f"#{i + 1}  {c.name}({c.code})  得分: {c.total_score:.1f}\n"
                f"    最新价 {c.price:.2f}  涨跌幅 {c.change_pct:+.2f}%  "
                f"{pe_str}  PB={c.pb:.2f}"
            )
            if c.reasons:
                line += f"\n    推荐理由：{c.reasons[0]}"
            if c.has_indicators:
                tech = f"RSI={c.rsi:.0f}"
                if c.macd_signal:
                    tech += f" MACD:{c.macd_signal}"
                if c.ma_align:
                    tech += f" 均线:{c.ma_align}"
                line += f"\n    技术面：{tech}"
            top_lines.append(line)

        sections.append(ReportSection(
            heading=f"Top 5 推荐",
            content="\n\n".join(top_lines),
        ))

        # 综合结论
        best = top[0] if top else None
        if best:
            summary = f"首推 {best.name}({best.code})，得分 {best.total_score:.1f}。"
            if best.reasons:
                summary += f" 核心理由：{best.reasons[0]}。"
        else:
            summary = "未筛选到符合条件的标的。"

        return SkillReport(
            skill_name=self.name,
            title=f"选股推荐 -- {strategy}",
            sections=sections,
            summary=summary,
        )
