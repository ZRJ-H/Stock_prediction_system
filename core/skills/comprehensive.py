"""
综合分析 Skill（ComprehensiveSkill）
=====================================
对单只股票进行全方位综合分析，调用其他 Skill 并汇总。

编排的 Skill：
  1. TechnicalSkill  → 技术面
  2. FundamentalSkill → 基本面
  3. RiskSkill       → 风险评估
  4. NewsSkill       → 舆情分析

输出：SkillReport（汇总所有 Skill 的报告和综合结论）
"""

from __future__ import annotations

from typing import List

from core.skills.base import BaseSkill, ReportSection, SkillReport
from core.skills.technical import TechnicalSkill
from core.skills.fundamental import FundamentalSkill
from core.skills.risk import RiskSkill
from core.skills.news import NewsSkill


class ComprehensiveSkill(BaseSkill):
    name = "comprehensive_analysis"
    description = (
        "对一只股票进行全面综合分析：技术面+基本面+风险评估+新闻舆情，"
        "一次调用产出完整的多维度报告。适用于用户要求「综合分析」「全面看看」等场景。"
    )
    parameters = {
        "code": {"type": "string", "description": "6位数字股票代码，如600519"},
    }

    def execute(self, code: str) -> SkillReport:
        technical = TechnicalSkill()
        fundamental = FundamentalSkill()
        risk = RiskSkill()
        news = NewsSkill()

        reports = {}

        # 逐个执行（顺序执行以控制并发和错误隔离）
        # 技术分析
        try:
            reports["technical"] = technical.execute(code)
        except Exception as e:
            reports["technical"] = SkillReport(
                skill_name="technical_analysis",
                title="技术分析",
                sections=[ReportSection(heading="错误", content=f"技术分析失败: {e}")],
                summary="技术分析不可用。",
            )

        # 基本面
        try:
            reports["fundamental"] = fundamental.execute(code)
        except Exception as e:
            reports["fundamental"] = SkillReport(
                skill_name="fundamental_analysis",
                title="基本面分析",
                sections=[ReportSection(heading="错误", content=f"基本面分析失败: {e}")],
                summary="基本面分析不可用。",
            )

        # 风险评估
        try:
            reports["risk"] = risk.execute(code)
        except Exception as e:
            reports["risk"] = SkillReport(
                skill_name="risk_assessment",
                title="风险评估",
                sections=[ReportSection(heading="错误", content=f"风险评估失败: {e}")],
                summary="风险评估不可用。",
            )

        # 新闻舆情
        try:
            reports["news"] = news.execute(code)
        except Exception as e:
            reports["news"] = SkillReport(
                skill_name="news_sentiment",
                title="新闻舆情",
                sections=[ReportSection(heading="错误", content=f"舆情分析失败: {e}")],
                summary="舆情分析不可用。",
            )

        return self._merge(code, reports)

    def _merge(self, code: str, reports: dict) -> SkillReport:
        """将多个子报告合并为综合报告。"""
        from core.market_data import get_realtime_quote
        q = get_realtime_quote(code)
        name = q.name if q else code

        # 汇总所有章节
        sections: List[ReportSection] = []
        for key, label in [
            ("technical", "一、技术面分析"),
            ("fundamental", "二、基本面分析"),
            ("risk", "三、风险评估"),
            ("news", "四、新闻舆情"),
        ]:
            r = reports.get(key)
            if r:
                # 合并该子报告的所有节
                for sec in r.sections:
                    sec.heading = f"{label} > {sec.heading}"
                    sections.append(sec)
                if r.summary:
                    sections.append(ReportSection(
                        heading=f"{label} 小结",
                        content=r.summary,
                    ))

        # 综合评分（加权平均四个维度）
        scores = []
        score_details: List[str] = []
        for key, weight, label in [
            ("technical", 0.35, "技术面"),
            ("fundamental", 0.25, "基本面"),
            ("risk", 0.25, "风险评估"),
            ("news", 0.15, "舆情"),
        ]:
            r = reports.get(key)
            if r and r.score is not None:
                scores.append(r.score * weight)
                score_details.append(f"{label}: {r.score:.0f}/100 (权重{weight:.0%})")

        total_score = sum(scores) / sum(
            w for k, w, _ in [
                ("technical", 0.35, ""),
                ("fundamental", 0.25, ""),
                ("risk", 0.25, ""),
                ("news", 0.15, ""),
            ] if reports.get(k) and reports[k].score is not None
        ) if scores else None

        # 综合结论
        conclusions: List[str] = []
        for key, label in [
            ("technical", "技术面"),
            ("fundamental", "基本面"),
            ("risk", "风险"),
            ("news", "舆情"),
        ]:
            r = reports.get(key)
            if r and r.summary:
                conclusions.append(f"【{label}】{r.summary}")

        if total_score is not None:
            if total_score >= 65:
                overall = f"综合评分 {total_score:.0f}/100，各维度表现较好，整体偏积极。"
            elif total_score >= 40:
                overall = f"综合评分 {total_score:.0f}/100，多空交织，建议关注关键信号变化。"
            else:
                overall = f"综合评分 {total_score:.0f}/100，多个维度提示谨慎。"
        else:
            overall = "部分维度数据不足，无法给出综合评分。"

        summary = overall + "\n\n" + "\n".join(conclusions)

        return SkillReport(
            skill_name=self.name,
            title=f"{name}({code}) 综合分析报告",
            sections=sections,
            summary=summary,
            score=total_score,
        )
