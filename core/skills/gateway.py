"""
Skill 网关（SkillGateway）
==========================
技能调度中枢，负责：
  1. Skill 注册与管理
  2. 意图 → Skill 映射（替代 agent.py 中的 _classify_intent + _dispatch）
  3. 统一执行入口 + 错误处理

与 agent.py 的协作：
  - LLM 模式：Skill 作为工具暴露给 LLM，由 LLM 决定调用哪个
  - 规则模式：SkillGateway 直接根据意图路由，内部可编排多个子 Skill
"""

from __future__ import annotations

from typing import Dict, Optional

from core.skills.base import BaseSkill, SkillReport
from core.skills.technical import TechnicalSkill
from core.skills.fundamental import FundamentalSkill
from core.skills.risk import RiskSkill
from core.skills.screening import ScreeningSkill
from core.skills.news import NewsSkill
from core.skills.comprehensive import ComprehensiveSkill


# ── 全局 Skill 注册表 ──
SKILL_REGISTRY: Dict[str, BaseSkill] = {
    "technical_analysis": TechnicalSkill(),
    "fundamental_analysis": FundamentalSkill(),
    "risk_assessment": RiskSkill(),
    "screening": ScreeningSkill(),
    "news_sentiment": NewsSkill(),
    "comprehensive_analysis": ComprehensiveSkill(),
}

# 意图关键词 → Skill 映射（用于规则模式路由）
INTENT_SKILL_MAP: Dict[str, str] = {
    # 技术分析类
    "indicators": "technical_analysis",
    "history": "technical_analysis",
    "predict": "technical_analysis",
    # 基本面类
    "financials": "fundamental_analysis",
    # 风险评估类
    "risk": "risk_assessment",
    # 新闻舆情
    "news": "news_sentiment",
    # 选股推荐
    "recommend": "screening",
    "screen": "screening",
    # 综合
    "analyze": "comprehensive_analysis",
    "default": "comprehensive_analysis",
}


class SkillGateway:
    """Skill 调度网关。

    使用示例：
        gw = SkillGateway()
        report = gw.route("indicators", code="600519")
        print(report.format())
    """

    def __init__(self):
        self.skills = SKILL_REGISTRY

    def get_skill(self, name: str) -> Optional[BaseSkill]:
        """按名称获取 Skill 实例。"""
        return self.skills.get(name)

    def route(self, intent: str, **kwargs) -> SkillReport:
        """根据意图路由到对应 Skill 并执行。

        Args:
            intent: 意图标识（见 INTENT_SKILL_MAP 的 keys）
            **kwargs: 传递给 Skill.execute() 的参数

        Returns:
            SkillReport
        """
        skill_name = INTENT_SKILL_MAP.get(intent, "comprehensive_analysis")
        skill = self.get_skill(skill_name)
        if skill is None:
            return SkillReport(
                skill_name="error",
                title="错误",
                summary=f"未找到与意图「{intent}」对应的技能。",
            )
        try:
            return skill.execute(**kwargs)
        except Exception as e:
            return SkillReport(
                skill_name=skill_name,
                title="Skill 执行错误",
                summary=f"执行 {skill_name} 时出错：{e}",
            )

    def get_all_tool_defs(self):
        """将全部 Skill 转换为 ToolDef 列表（用于 LLM function calling）。"""
        tools = []
        for skill in self.skills.values():
            tools.append(skill.to_tool_def())
        return tools
