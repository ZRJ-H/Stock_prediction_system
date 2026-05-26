"""
Skill 基类与统一接口
====================
定义 Skill 的标准接口和结构化报告格式。

每个 Skill 遵循统一模式：
  skill.execute(**params) → SkillReport → format() → 文本报告

工具编排差异：
  旧（tools.py）：Agent → 单工具 → 文本
  新（skills）：  Agent → Skill → 多工具编排 → 结构化报告 → 文本
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ReportSection:
    """报告的一个章节。"""
    heading: str
    content: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    signal: str = ""  # bullish / bearish / neutral


@dataclass
class SkillReport:
    """Skill 产出的结构化报告。

    Attributes:
        skill_name: Skill 名称
        title:      报告标题（含股票名/代码）
        sections:   有序章节列表
        summary:    综合结论
        score:      综合评分（0~100，仅部分 Skill 产出）
        disclaimer: 免责声明
    """
    skill_name: str
    title: str
    sections: List[ReportSection] = field(default_factory=list)
    summary: str = ""
    score: Optional[float] = None
    disclaimer: str = "[!] 以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。"

    def format(self) -> str:
        """将结构化报告格式化为可读文本。"""
        lines = [f"{'='*20} {self.title} {'='*20}\n"]
        for sec in self.sections:
            lines.append(f"--- {sec.heading} ---")
            if sec.signal:
                lines.append(f"  信号：{sec.signal}")
            lines.append(sec.content)
        if self.score is not None:
            lines.append(f"\n>> 综合评分：{self.score:.1f}/100")
        if self.summary:
            lines.append(f"\n【综合结论】\n{self.summary}")
        lines.append(f"\n{self.disclaimer}")
        return "\n".join(lines)


class BaseSkill(ABC):
    """Skill 抽象基类。

    子类必须实现：
      - name:        技能名称（如 "technical_analysis"）
      - description: 技能描述（帮助 LLM/路由层理解何时调用）
      - parameters:  输入参数 schema
      - execute():   执行逻辑
    """

    name: str = ""
    description: str = ""
    parameters: Dict[str, Dict[str, str]] = {}

    @abstractmethod
    def execute(self, **kwargs) -> SkillReport:
        """执行 Skill 逻辑并返回结构化报告。"""
        ...

    def to_tool_def(self):
        """转换为 ToolDef（兼容现有工具系统）。"""
        from core.tools import ToolDef
        return ToolDef(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            handler=self._handler,
        )

    def _handler(self, **kwargs) -> str:
        """适配器：将 Skill 报告转为字符串，兼容 ToolDef handler 接口。"""
        report = self.execute(**kwargs)
        return report.format()
