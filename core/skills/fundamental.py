"""
基本面分析 Skill（FundamentalSkill）
=====================================
获取财报数据并进行估值分析。

编排的数据：
  1. 实时行情 → PE/PB/总市值
  2. AKShare 财报 → 营收/净利润/ROE/毛利率等
  3. 估值评分 → PE/PB 区间判断 + 综合评级

输出：SkillReport（估值指标 / 盈利能力 / 财务健康 / 综合评级）
"""

from __future__ import annotations

from typing import List

from core.fundamentals import FinancialReport, fetch_financials
from core.market_data import get_realtime_quote
from core.skills.base import BaseSkill, ReportSection, SkillReport


class FundamentalSkill(BaseSkill):
    name = "fundamental_analysis"
    description = (
        "对股票进行基本面分析，获取PE/PB/ROE/毛利率/营收/净利润等核心财务指标，"
        "并给出估值评级（低估/合理/高估）。适用场景：用户询问基本面、财报、估值。"
    )
    parameters = {
        "code": {"type": "string", "description": "6位数字股票代码，如600519"},
    }

    def execute(self, code: str) -> SkillReport:
        q = get_realtime_quote(code)
        name = q.name if q else code
        price = q.price if q else 0.0
        pe = q.pe if q else 0.0
        pb = q.pb if q else 0.0

        report: FinancialReport = fetch_financials(code)
        sections = self._build_sections(code, name, price, pe, pb, report)
        score, conclusion = self._compute_score(pe, pb, report)

        return SkillReport(
            skill_name=self.name,
            title=f"{name}({code}) 基本面分析报告",
            sections=sections,
            summary=conclusion,
            score=score,
        )

    def _build_sections(self, code: str, name: str, price: float,
                        pe: float, pb: float, fr: FinancialReport) -> List[ReportSection]:
        sections: List[ReportSection] = []

        # ── 估值快照 ──
        pe_str = f"PE(TTM): {pe:.2f}" if pe > 0 else "PE: 亏损"
        sections.append(ReportSection(
            heading="估值快照",
            content=f"最新价：{price:.2f}\n{pe_str}\nPB: {pb:.2f}",
        ))

        # ── 估值区间判断 ──
        valuation_lines: List[str] = []
        signal = "neutral"
        if pe <= 0:
            valuation_lines.append("  公司当前处于亏损状态，PE 指标不适用")
            signal = "bearish"
        elif pe < 10:
            valuation_lines.append(f"  PE={pe:.1f}：低估值区间（<10），可能被低估")
            signal = "bullish"
        elif pe < 20:
            valuation_lines.append(f"  PE={pe:.1f}：合理估值区间（10~20）")
            signal = "neutral"
        elif pe < 40:
            valuation_lines.append(f"  PE={pe:.1f}：偏高估值区间（20~40），注意溢价风险")
            signal = "bearish"
        else:
            valuation_lines.append(f"  PE={pe:.1f}：高估值区间（>40），需谨慎评估成长性")
            signal = "bearish"

        if pb < 1.0:
            valuation_lines.append(f"  PB={pb:.2f}：破净状态，资产价值可能被低估")
            if signal == "bearish":
                signal = "neutral"
        elif pb < 2.0:
            valuation_lines.append(f"  PB={pb:.2f}：市净率偏低")
        else:
            valuation_lines.append(f"  PB={pb:.2f}：市净率正常/偏高")

        sections.append(ReportSection(
            heading="估值分析",
            content="\n".join(valuation_lines),
            signal=signal,
        ))

        # ── 财务指标 ──
        if fr.indicators:
            label_map = {
                "revenue": "营业总收入",
                "net_profit": "净利润",
                "roe": "ROE（净资产收益率）",
                "gross_margin": "毛利率",
                "debt_ratio": "资产负债率",
                "eps": "每股收益(EPS)",
                "bvps": "每股净资产(BVPS)",
            }
            fin_lines: List[str] = []
            for key, label in label_map.items():
                if key in fr.indicators:
                    fin_lines.append(f"  {label}: {fr.indicators[key]}")
            fin_lines.append(f"\n  数据来源：{fr.source}")
            sections.append(ReportSection(
                heading="核心财务指标",
                content="\n".join(fin_lines),
            ))
        else:
            sections.append(ReportSection(
                heading="核心财务指标",
                content=f"  财报数据暂不可用。\n  原因：{fr.source}",
            ))

        return sections

    def _compute_score(self, pe: float, pb: float, fr: FinancialReport) -> tuple:
        """基本面评分（0~100）。

        权重：
          PE 估值区间: 40分
          PB 估值区间: 25分
          ROE 水平:    20分
          财务数据完整性: 15分
        """
        score = 0.0
        signals: List[str] = []

        # PE 维度（40分）
        if pe <= 0:
            signals.append("PE: 亏损，无法评分")
        elif pe < 8:
            score += 40
            signals.append("PE极低 [+]")
        elif pe < 15:
            score += 32
            signals.append("PE偏低 [+]")
        elif pe < 25:
            score += 20
            signals.append("PE适中")
        elif pe < 40:
            score += 8
            signals.append("PE偏高 [-]")
        else:
            signals.append("PE过高 [-]")

        # PB 维度（25分）
        if pb < 1.0:
            score += 25
            signals.append("PB破净 [+]")
        elif pb < 2.0:
            score += 18
            signals.append("PB合理 [+]")
        elif pb < 5.0:
            score += 8
            signals.append("PB偏高")
        else:
            signals.append("PB过高 [-]")

        # ROE 维度（20分，从财报中提取）
        roe_str = fr.indicators.get("roe", "")
        if roe_str:
            try:
                roe_val = float(str(roe_str).replace("%", "").strip())
                if roe_val > 20:
                    score += 20
                    signals.append(f"ROE={roe_val:.1f}%（优秀） [+]")
                elif roe_val > 10:
                    score += 14
                    signals.append(f"ROE={roe_val:.1f}%（良好） [+]")
                elif roe_val > 5:
                    score += 8
                    signals.append(f"ROE={roe_val:.1f}%（一般）")
                else:
                    score += 3
                    signals.append(f"ROE={roe_val:.1f}%（偏低）")
            except ValueError:
                pass

        # 数据完整性
        if fr.indicators:
            score += min(15, len(fr.indicators) * 2)

        # 结论
        if score >= 65:
            conclusion = f"基本面评分 {score:.0f}/100，估值偏低/合理，具备安全边际。"
        elif score >= 40:
            conclusion = f"基本面评分 {score:.0f}/100，估值中性，需结合成长性综合判断。"
        else:
            conclusion = f"基本面评分 {score:.0f}/100，估值偏高或数据不足，建议谨慎。"

        if signals:
            conclusion += "\n关键信号：" + "；".join(signals) + "。"
        return score, conclusion
