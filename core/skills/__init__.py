"""
Skill 系统包
============
可组合的股票分析技能管线。

使用示例：
    from core.skills.gateway import SkillGateway
    from core.skills.technical import TechnicalSkill
"""

from core.skills.base import BaseSkill, SkillReport, ReportSection
from core.skills.gateway import SkillGateway, SKILL_REGISTRY, INTENT_SKILL_MAP

__all__ = [
    "BaseSkill",
    "SkillReport",
    "ReportSection",
    "SkillGateway",
    "SKILL_REGISTRY",
    "INTENT_SKILL_MAP",
]
