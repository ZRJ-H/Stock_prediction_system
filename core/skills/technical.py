"""
技术分析 Skill（TechnicalSkill）
=================================
计算全量技术指标并生成结构化分析报告。

编排的工具：
  1. get_daily_kline → OHLCV 数组
  2. compute_ma / compute_macd / compute_rsi / compute_boll / compute_kdj
  3. detect_patterns → K线形态识别
  4. 综合打分 + 操作建议

输出：SkillReport（均线系统 / 趋势指标 / 震荡指标 / 布林带 / 量价 / 形态 / 综合评分）
"""

from __future__ import annotations

from typing import Dict, List, Union

import numpy as np

from core.indicators import (
    IndicatorBundle,
    calc_all_indicators,
    compute_boll,
    compute_kdj,
    compute_ma,
    compute_macd,
    compute_rsi,
    compute_vol_ratio,
    detect_patterns,
)
from core.market_data import KlineBar, get_daily_kline, get_realtime_quote
from core.skills.base import BaseSkill, ReportSection, SkillReport


class TechnicalSkill(BaseSkill):
    name = "technical_analysis"
    description = (
        "对股票进行完整技术分析，输出均线/MACD/RSI/布林带/KDJ/成交量/K线形态"
        "的综合报告，含综合评分和操作建议。适用场景：用户询问技术面、指标、走势分析。"
    )
    parameters = {
        "code": {"type": "string", "description": "6位数字股票代码，如600519"},
        "days": {"type": "string", "description": "计算天数，默认90"},
    }

    def execute(self, code: str, days: str = "90") -> SkillReport:
        try:
            n_days = int(days)
        except (ValueError, TypeError):
            n_days = 90
        n_days = max(60, min(n_days, 365))

        bundle = calc_all_indicators(code, days=n_days)
        q = get_realtime_quote(code)
        name = q.name if q else code
        price = q.price if q else 0.0

        if not bundle.latest:
            return SkillReport(
                skill_name=self.name,
                title=f"{name}({code}) 技术分析",
                sections=[ReportSection(heading="错误", content="无法获取K线数据，请确认代码正确。")],
                summary="数据不足，无法分析。",
            )

        sections = self._build_sections(bundle, price)
        score, conclusion = self._compute_score(bundle)

        return SkillReport(
            skill_name=self.name,
            title=f"{name}({code}) 技术分析报告",
            sections=sections,
            summary=conclusion,
            score=score,
        )

    def _build_sections(self, b: IndicatorBundle, price: float) -> List[ReportSection]:
        sections: List[ReportSection] = []

        # ── 行情快照 ──
        sections.append(ReportSection(
            heading="行情快照",
            content=f"最新价：{price:.2f}",
        ))

        # ── 均线系统 ──
        ma_lines: List[str] = []
        for k in ["MA5", "MA10", "MA20", "MA60"]:
            if k in b.latest:
                ma_lines.append(f"  {k}: {b.latest[k]:.2f}")
        ma_signal = b.recent.get("MA排列", "")
        if "多头" in ma_signal:
            signal = "bullish"
        elif "空头" in ma_signal:
            signal = "bearish"
        else:
            signal = "neutral"
        sections.append(ReportSection(
            heading="均线系统",
            content="\n".join(ma_lines) + f"\n  排列：{ma_signal}",
            signal=signal,
            metrics={k: float(b.latest[k]) for k in ["MA5", "MA10", "MA20", "MA60"] if k in b.latest},
        ))

        # ── MACD ──
        macd_lines = [
            f"  DIF: {b.latest.get('MACD_DIF', '')}",
            f"  DEA: {b.latest.get('MACD_DEA', '')}",
            f"  HIST: {b.latest.get('MACD_HIST', '')}",
            f"  信号: {b.latest.get('MACD信号', '')}",
        ]
        macd_signal = str(b.latest.get("MACD信号", ""))
        sections.append(ReportSection(
            heading="MACD 趋势指标",
            content="\n".join(macd_lines),
            signal="bullish" if "金叉" in macd_signal else "bearish",
        ))

        # ── RSI ──
        rsi_val = b.latest.get("RSI", "")
        rsi_signal = str(b.latest.get("RSI信号", ""))
        sections.append(ReportSection(
            heading="RSI 强弱指标",
            content=f"  RSI(14): {rsi_val}\n  判断: {rsi_signal}",
            signal="bearish" if "超买" in rsi_signal else ("bullish" if "超卖" in rsi_signal else "neutral"),
        ))

        # ── 布林带 ──
        boll_lines = [
            f"  上轨: {b.latest.get('BOLL_UPPER', '')}",
            f"  中轨: {b.latest.get('BOLL_MID', '')}",
            f"  下轨: {b.latest.get('BOLL_LOWER', '')}",
            f"  带宽: {b.latest.get('BOLL_WIDTH', '')}%",
            f"  位置: {b.latest.get('BOLL位置', '')}",
        ]
        boll_pos = str(b.latest.get("BOLL位置", ""))
        boll_signal = "bearish" if "上轨" in boll_pos else ("bullish" if "下轨" in boll_pos else "neutral")
        sections.append(ReportSection(
            heading="布林带 BOLL(20)",
            content="\n".join(boll_lines),
            signal=boll_signal,
        ))

        # ── KDJ ──
        kdj_lines = [
            f"  K: {b.latest.get('KDJ_K', '')}",
            f"  D: {b.latest.get('KDJ_D', '')}",
            f"  J: {b.latest.get('KDJ_J', '')}",
            f"  区域: {b.latest.get('KDJ信号', '')}",
        ]
        kdj_signal = str(b.latest.get("KDJ信号", ""))
        sections.append(ReportSection(
            heading="KDJ 随机指标",
            content="\n".join(kdj_lines),
            signal="bullish" if "金叉" in kdj_signal else ("bearish" if "超买" in kdj_signal else "neutral"),
        ))

        # ── 量价关系 ──
        vol_lines = [
            f"  量比(5): {b.latest.get('VOL_RATIO', '')}",
            f"  判断: {b.latest.get('量能信号', '')}",
        ]
        vol_signal_str = str(b.latest.get("量能信号", ""))
        sections.append(ReportSection(
            heading="量价关系",
            content="\n".join(vol_lines),
            signal="bullish" if "放量" in vol_signal_str else "neutral",
        ))

        # ── K线形态 ──
        pattern_lines: List[str] = []
        for k, v in sorted(b.recent.items()):
            if k.startswith("形态"):
                pattern_lines.append(f"  {v}")
        if not pattern_lines:
            pattern_lines.append("  近期无明显经典形态")
        sections.append(ReportSection(
            heading="K线形态识别",
            content="\n".join(pattern_lines),
        ))

        return sections

    def _compute_score(self, b: IndicatorBundle) -> tuple:
        """综合技术评分（0~100）。

        权重分配：
          均线多头排列: +25
          MACD 金叉:    +20
          RSI 健康区间: +15
          价格在布林带下轨: +15（超跌反弹机会）
          KDJ 金叉区域:  +10
          放量上涨:      +15
        总计 100 分。
        """
        score = 0.0
        signals: List[str] = []

        ma = b.recent.get("MA排列", "")
        macd = str(b.latest.get("MACD信号", ""))
        rsi_sig = str(b.latest.get("RSI信号", ""))
        boll_pos = str(b.latest.get("BOLL位置", ""))
        kdj_sig = str(b.latest.get("KDJ信号", ""))
        vol_sig = str(b.latest.get("量能信号", ""))

        if "多头" in ma:
            score += 25
            signals.append("均线多头排列 [+]")
        elif "空头" in ma:
            signals.append("均线空头排列 [-]")

        if "金叉" in macd:
            score += 20
            signals.append("MACD金叉 [+]")
        elif "死叉" in macd:
            signals.append("MACD死叉 [-]")

        if "超卖" in rsi_sig:
            score += 10
            signals.append("RSI超卖(潜在反弹)")
        elif "超买" in rsi_sig:
            signals.append("RSI超买(注意回调)")
        elif "中性" in rsi_sig:
            score += 15
            signals.append("RSI中性区间 [+]")

        if "下轨" in boll_pos:
            score += 15
            signals.append("价格触及下轨(支撑位) [+]")
        elif "上轨" in boll_pos:
            signals.append("价格触及上轨(压力位)")

        if "金叉" in kdj_sig or "超卖" in kdj_sig:
            score += 10
            signals.append("KDJ金叉/超卖 [+]")

        if "放量" in vol_sig:
            score += 15
            signals.append("放量交投活跃 [+]")
        elif "缩量" in vol_sig:
            signals.append("缩量交投清淡")

        # 结论判定
        if score >= 65:
            conclusion = f"技术面偏多（{score:.0f}/100），多项指标共振看涨。"
        elif score >= 40:
            conclusion = f"技术面中性（{score:.0f}/100），信号分歧，建议观望或轻仓。"
        else:
            conclusion = f"技术面偏空（{score:.0f}/100），多数指标指向弱势。建议谨慎。"

        conclusion += "\n关键信号：" + "；".join(signals) + "。"
        return score, conclusion
