"""
综合分析 Skill（ComprehensiveSkill）
=====================================
对单只股票进行全方位综合分析，调用其他 Skill 并汇总为结构化报告。

编排的 Skill：
  1. TechnicalSkill  → 技术面
  2. FundamentalSkill → 基本面
  3. RiskSkill       → 风险评估
  4. NewsSkill       → 舆情分析

输出：SkillReport（固定章节：结论/技术面/基本面/风险/舆情/操作建议/免责声明）
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
        errors = {}  # 记录各模块失败原因，用于降级提示

        # 技术分析
        try:
            reports["technical"] = technical.execute(code)
        except Exception as e:
            errors["technical"] = str(e)
            reports["technical"] = self._fallback_report(
                "technical_analysis", "技术面分析",
                "技术面数据当前不可用，本次分析跳过该维度。"
            )

        # 基本面
        try:
            reports["fundamental"] = fundamental.execute(code)
        except Exception as e:
            errors["fundamental"] = str(e)
            reports["fundamental"] = self._fallback_report(
                "fundamental_analysis", "基本面分析",
                "基本面数据当前不可用（可能因 AKShare 未启用或财报数据缺失），本次分析跳过该维度。"
            )

        # 风险评估
        try:
            reports["risk"] = risk.execute(code)
        except Exception as e:
            errors["risk"] = str(e)
            reports["risk"] = self._fallback_report(
                "risk_assessment", "风险评估",
                "风险数据当前不可用，本次分析跳过该维度。"
            )

        # 新闻舆情
        try:
            reports["news"] = news.execute(code)
        except Exception as e:
            errors["news"] = str(e)
            reports["news"] = self._fallback_report(
                "news_sentiment", "新闻舆情",
                "舆情数据当前不可用（可能因网络问题或数据源无响应），本次分析跳过该维度。"
            )

        return self._merge(code, reports, errors)

    def _fallback_report(self, skill_name: str, title: str, reason: str) -> SkillReport:
        """构造子模块不可用时的降级报告。"""
        return SkillReport(
            skill_name=skill_name,
            title=title,
            sections=[ReportSection(heading="提示", content=reason)],
            summary=reason,
            score=None,
        )

    def _merge(self, code: str, reports: dict, errors: dict) -> SkillReport:
        """将子报告合并为目标格式的综合性报告。

        输出固定 7 章节（严格顺序）：
          1.【结论】     → 综合评分 + 各维度简述 + 降级提示
          2.【技术面】   → TechnicalSkill 报告
          3.【基本面】   → FundamentalSkill 报告
          4.【风险】     → RiskSkill 报告
          5.【舆情】     → NewsSkill 报告
          6.【操作建议】 → 各维度信号的辅助判断（非确定性买卖建议）
          7.【免责声明】 → 固定风险提示
        """
        from core.market_data import get_realtime_quote
        q = get_realtime_quote(code)
        name = q.name if q else code

        # 维度配置：(key, 章节标题, 权重)
        dimensions = [
            ("technical",   "【技术面】", 0.35),
            ("fundamental", "【基本面】", 0.25),
            ("risk",        "【风险】",   0.25),
            ("news",        "【舆情】",   0.15),
        ]

        # ── 第一遍：收集评分和信号 ──
        scores_list = []       # (score, weight) 用于加权计算
        dimension_signals = []  # 各维度信号摘要，用于结论和操作建议

        for key, heading, weight in dimensions:
            r = reports.get(key)
            if r is None:
                continue
            if r.score is not None:
                scores_list.append((r.score, weight))
            signal = self._extract_signal(r)
            dim_label = heading.strip("【】")
            dimension_signals.append((dim_label, r.score, signal, key in errors))

        # ── 加权综合评分 ──
        total_score: float | None = None
        if scores_list:
            total_weight = sum(w for _, w in scores_list)
            total_score = sum(s * w for s, w in scores_list) / total_weight if total_weight > 0 else None

        # ── 按固定顺序构建 sections ──
        sections: List[ReportSection] = []

        # 1) 【结论】
        conclusion = self._build_conclusion(name, code, total_score, dimension_signals)
        sections.append(ReportSection(heading="【结论】", content=conclusion))

        # 2~5) 四个维度章节
        for key, heading, weight in dimensions:
            r = reports.get(key)
            if r is None:
                continue
            parts: List[str] = []
            for sec in r.sections:
                if sec.content:
                    parts.append(sec.content)
            body = "\n\n".join(parts) if parts else "暂无数据。"
            if key in errors:
                body = f"[!] {body}"
            sections.append(ReportSection(heading=heading, content=body))

        # 6) 【操作建议】
        suggestions = self._build_suggestions(total_score, dimension_signals, errors)
        sections.append(ReportSection(heading="【操作建议】", content=suggestions))

        # 7) 【免责声明】
        sections.append(ReportSection(
            heading="【免责声明】",
            content="本报告仅供学习研究，所有分析结果不构成投资建议。股市有风险，投资需谨慎。过往表现不代表未来收益。"
        ))

        return SkillReport(
            skill_name=self.name,
            title=f"{name}({code}) 综合分析报告",
            sections=sections,
            summary="",
            score=None,     # 评分已写入【结论】章节，无需 format() 重复追加
            disclaimer="",  # 免责声明已作为独立章节
        )

    def _extract_signal(self, report: SkillReport) -> str:
        """从子报告中提取信号方向（bullish/bearish/neutral）。"""
        for sec in report.sections:
            if sec.signal:
                return sec.signal
        if report.score is not None:
            if report.score >= 60:
                return "bullish"
            elif report.score <= 40:
                return "bearish"
        return "neutral"

    def _build_conclusion(
        self, name: str, code: str, total_score: float | None,
        dimension_signals: list,
    ) -> str:
        """构造【结论】部分。"""
        parts: List[str] = []

        # 综合评分结论
        if total_score is not None:
            if total_score >= 65:
                grade = "偏积极"
                detail = "多数维度表现较好，整体信号偏正面。"
            elif total_score >= 40:
                grade = "中性"
                detail = "各维度多空交织，建议密切关注后续信号变化。"
            else:
                grade = "偏谨慎"
                detail = "多个维度提示风险或不确定性，需保持谨慎。"
            parts.append(f"{name}({code}) 综合评分 {total_score:.0f}/100，整体评估：{grade}。{detail}")
        else:
            parts.append(f"{name}({code}) 部分维度数据不足，无法给出综合评分。")

        # 各维度简述
        missing_dims: List[str] = []
        for entry in dimension_signals:
            label, score, signal, is_error = entry
            if score is not None:
                sig_text = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}.get(signal, "中性")
                parts.append(f"  {label}：{score:.0f}/100（{sig_text}）")
            else:
                parts.append(f"  {label}：数据不可用")
                missing_dims.append(label)

        # 降级提示
        if missing_dims:
            parts.append(f"  注意：以下维度数据不可用 → {', '.join(missing_dims)}，相应分析已跳过。")

        return "\n".join(parts)

    def _build_suggestions(
        self, total_score: float | None, dimension_signals: list, errors: dict,
    ) -> str:
        """构造【操作建议】（辅助判断，不构成确定性买卖建议）。"""
        parts: List[str] = ["以下为基于各维度信号的辅助判断，不构成具体买卖建议：\n"]

        # 按维度给出观察
        for entry in dimension_signals:
            label, score, signal, is_error = entry
            if score is None:
                parts.append(f"  · {label}：当前数据不可用，建议补充信息后再评估。")
                continue
            if signal == "bullish":
                parts.append(f"  · {label}信号偏多（{score:.0f}/100），可关注相关机会。")
            elif signal == "bearish":
                parts.append(f"  · {label}信号偏空（{score:.0f}/100），建议谨慎对待。")
            else:
                parts.append(f"  · {label}信号中性（{score:.0f}/100），方向尚不明确。")

        # 综合仓位/心态建议
        if total_score is not None:
            if total_score >= 65:
                parts.append("\n整体信号偏积极，但请注意：市场存在不确定性，任何投资决策都应基于自身风险承受能力。")
            elif total_score >= 40:
                parts.append("\n整体信号中性，建议以观望为主，等待更明确的方向信号后再做判断。")
            else:
                parts.append("\n整体信号偏谨慎，建议优先关注风险控制，不宜追高或重仓参与。")

        if any(e for _, _, _, e in dimension_signals):
            parts.append("\n[!] 部分维度数据缺失，以上判断仅基于可用维度，完整性受限。")

        parts.append("\n投资者应结合自身资金状况、风险偏好和市场环境独立决策。")
        return "\n".join(parts)
