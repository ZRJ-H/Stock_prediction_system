"""
风险评估 Skill（RiskSkill）
============================
计算股票风险指标并生成风险评估报告。

风险维度：
  1. 波动率（日收益率标准差年化）
  2. 最大回撤（Max Drawdown）
  3. 下行风险（Downside Deviation）
  4. 简易 Beta（vs 沪深300，如有指数数据）
  5. 仓位建议（基于风险等级）

输出：SkillReport（波动率 / 最大回撤 / 风险等级 / 仓位建议）
"""

from __future__ import annotations

import math
from typing import List

import numpy as np

from core.market_data import get_daily_kline, get_realtime_quote
from core.skills.base import BaseSkill, ReportSection, SkillReport


# 年化交易日
TRADING_DAYS = 252


class RiskSkill(BaseSkill):
    name = "risk_assessment"
    description = (
        "评估股票的投资风险，计算波动率、最大回撤、下行风险等指标，"
        "给出风险等级和仓位建议。适用场景：用户询问风险、止损位、仓位管理。"
    )
    parameters = {
        "code": {"type": "string", "description": "6位数字股票代码，如600519"},
        "days": {"type": "string", "description": "分析天数，默认252（约1年）"},
    }

    def execute(self, code: str, days: str = "252") -> SkillReport:
        try:
            n_days = int(days)
        except (ValueError, TypeError):
            n_days = 252
        n_days = max(60, min(n_days, 504))

        bars = get_daily_kline(code, days=n_days)
        q = get_realtime_quote(code)
        name = q.name if q else code
        price = q.price if q else 0.0

        if len(bars) < 20:
            return SkillReport(
                skill_name=self.name,
                title=f"{name}({code}) 风险评估",
                sections=[ReportSection(heading="错误", content="数据不足（需要至少20个交易日），无法评估风险。")],
                summary="数据不足。",
            )

        close = np.array([b.close for b in bars], dtype=np.float64)
        sections = self._compute_risk(close, price, name, code)
        level, conclusion = self._risk_conclusion(sections)

        return SkillReport(
            skill_name=self.name,
            title=f"{name}({code}) 风险评估报告",
            sections=sections,
            summary=conclusion,
            score=100 - min(level * 25, 100),
        )

    def _compute_risk(self, close: np.ndarray, price: float,
                      name: str, code: str) -> List[ReportSection]:
        sections: List[ReportSection] = []

        # 日收益率
        returns = np.diff(close) / close[:-1]
        n = len(returns)

        # ── 波动率 ──
        daily_vol = float(np.std(returns))
        annual_vol = daily_vol * math.sqrt(TRADING_DAYS)
        vol_signal = ""
        if annual_vol < 0.20:
            vol_desc = "低波动（<20%），股价运行平稳"
            vol_signal = "neutral"
        elif annual_vol < 0.35:
            vol_desc = "中等波动（20%~35%）"
            vol_signal = "neutral"
        elif annual_vol < 0.50:
            vol_desc = "高波动（35%~50%），注意价格波动风险"
            vol_signal = "bearish"
        else:
            vol_desc = "极高波动（>50%），风险显著"
            vol_signal = "bearish"

        sections.append(ReportSection(
            heading="波动率分析",
            content=(
                f"  日波动率: {daily_vol:.4f}（{daily_vol * 100:.2f}%）\n"
                f"  年化波动率: {annual_vol:.2%}\n"
                f"  判断：{vol_desc}"
            ),
            signal=vol_signal,
            metrics={"daily_vol": daily_vol, "annual_vol": annual_vol},
        ))

        # ── 最大回撤 ──
        peak = np.maximum.accumulate(close)
        drawdown = (peak - close) / peak
        max_dd = float(np.max(drawdown))
        max_dd_idx = int(np.argmax(drawdown))
        dd_signal = ""
        if max_dd < 0.10:
            dd_desc = "轻微回撤（<10%），下行风险低"
            dd_signal = "bullish"
        elif max_dd < 0.20:
            dd_desc = "中等回撤（10%~20%）"
            dd_signal = "neutral"
        elif max_dd < 0.35:
            dd_desc = "大幅回撤（20%~35%），需设止损"
            dd_signal = "bearish"
        else:
            dd_desc = "极端回撤（>35%），历史波动剧烈"
            dd_signal = "bearish"

        sections.append(ReportSection(
            heading="最大回撤",
            content=f"  历史最大回撤: {max_dd:.2%}\n  判断：{dd_desc}",
            signal=dd_signal,
            metrics={"max_drawdown": max_dd},
        ))

        # ── 下行风险 ──
        neg_returns = returns[returns < 0]
        if len(neg_returns) > 0:
            downside_dev = float(np.std(neg_returns)) * math.sqrt(TRADING_DAYS)
        else:
            downside_dev = 0.0
        sections.append(ReportSection(
            heading="下行风险",
            content=f"  下行标准差（年化）: {downside_dev:.2%}\n  （仅统计负收益日的波动，更真实反映亏损风险）",
            metrics={"downside_dev": downside_dev},
        ))

        # ── VaR（风险价值）─
        var_95 = float(np.percentile(returns, 5))
        var_99 = float(np.percentile(returns, 1))
        sections.append(ReportSection(
            heading="VaR 风险价值",
            content=(
                f"  95% VaR (日): {var_95:.2%} -- 95%概率下，单日最大亏损不超过 {abs(var_95) * price:.2f}元（基准价{price:.2f}）\n"
                f"  99% VaR (日): {var_99:.2%} -- 极端情况下的单日最大亏损估计"
            ),
            metrics={"var_95": var_95, "var_99": var_99},
        ))

        # ── 仓位建议 ──
        if annual_vol < 0.20 and max_dd < 0.10:
            position = "可考虑常规仓位（≤30%总资产）"
            stop_loss_pct = 0.05
        elif annual_vol < 0.35 and max_dd < 0.20:
            position = "建议中等仓位（≤20%总资产）"
            stop_loss_pct = 0.08
        elif annual_vol < 0.50:
            position = "建议轻仓（≤10%总资产），严格止损"
            stop_loss_pct = 0.10
        else:
            position = "建议极轻仓或观望（≤5%总资产）"
            stop_loss_pct = 0.12

        stop_price = price * (1 - stop_loss_pct)
        sections.append(ReportSection(
            heading="仓位与止损建议",
            content=(
                f"  建议仓位：{position}\n"
                f"  参考止损位：{stop_price:.2f}（-{stop_loss_pct:.0%}）\n"
                f"  [!] 以上仅为基于历史波动率的参考建议，请根据个人风险承受能力调整。"
            ),
            signal="neutral",
        ))

        return sections

    def _risk_conclusion(self, sections: List[ReportSection]) -> tuple:
        """判定风险等级（0=低风险, 3=高风险）。"""
        bearish_count = sum(1 for s in sections if s.signal == "bearish")
        bullish_count = sum(1 for s in sections if s.signal == "bullish")

        if bearish_count >= 3:
            level = 3
            text = "高风险：波动率+回撤+下行风险均偏高，建议严格控制仓位和止损。"
        elif bearish_count >= 2:
            level = 2
            text = "中高风险：部分风险指标偏高，建议轻仓操作并设置止损。"
        elif bullish_count >= 2:
            level = 0
            text = "低风险：波动和回撤可控，适合稳健型投资者。"
        else:
            level = 1
            text = "中等风险：风险指标在可接受范围内，注意仓位控制。"
        return level, text
