# Documentation Status

本文件是当前开发文档入口，用来规定 agent 默认读取范围和历史文档归档边界。如果文档之间出现冲突，以 `CLAUDE.md`、本文档和用户当前指令为准。

## 默认读取范围

新 agent 默认只读取：

1. `CLAUDE.md`：项目级规则、禁止事项和当前文档入口。
2. `README.md`：面向用户的项目说明。
3. `docs/current/**`：当前开发文档。

新 agent 默认禁止读取：

- `docs/archive/**`：历史路线图、旧评估、旧里程碑、答辩材料和复盘资料。只有用户明确要求“历史复盘”“查看归档”“读取旧文档”时才能读取。

## 当前开发文档

| 文档 | 用途 |
|---|---|
| `docs/current/DOCUMENTATION_STATUS.md` | 当前文档入口和读取规则 |
| `docs/current/PAPER_TRADING_M1_DESIGN.md` | `feature/paper-trading` 的 M1-M6 阶段计划 |
| `docs/current/PROGRESS.md` | 当前进度记录 |

## 当前开发线

当前活跃开发线是 `feature/paper-trading`：

| 阶段 | 状态 | 提交 | 标签 | 说明 |
|---|---|---|---|---|
| Paper Trading M1 | 已完成 | `0db8e5a` | `paper-trading-m1` | 项目审查和设计 |
| Paper Trading M2 | 已完成 | `937a938` | `paper-trading-m2` | 数据库与交易引擎 |
| Paper Trading M3 | 已完成 | 当前工作区 | `paper-trading-m3` | API 与 Excel 报表 |
| Paper Trading M4 | 待开始 | - | `paper-trading-m4` | 前端展示 |
| Paper Trading M5 | 待开始 | - | `paper-trading-m5` | 定时任务与 Docker |
| Paper Trading M6 | 待开始 | - | `paper-trading-m6` | 测试和文档 |

## 历史归档文档

以下文档已统一移动到 `docs/archive/`，保留作背景，不得作为当前任务优先级：

| 文档 | 状态 | 使用方式 |
|---|---|---|
| `docs/archive/CC_AUTONOMOUS_ROADMAP.md` | 历史归档 | 旧 E1-E7 自动推进路线，不再决定当前下一步 |
| `docs/archive/PROJECT_ASSESSMENT.md` | 历史归档 | 2026-05-27 旧评估，包含已过期分支、提交和路线建议 |
| `docs/archive/REVIEW_HISTORY.md` | 历史归档 + 里程碑详录 | 查历史问题根因和旧里程碑，不作为当前计划入口 |
| `docs/archive/DEMO_SCRIPT.md` | 演示归档 | 基础系统演示脚本；paper-trading 完成前不代表新功能演示 |
| `docs/archive/DEFENSE_PACKAGE.md` | 答辩归档 | 课程答辩材料，不作为开发路线 |
| `docs/archive/PROJECT_TECHNICAL_EXPLAINER.md` | 技术说明归档 | 架构背景说明，不作为开发路线 |
| `docs/archive/AGENT_DEVELOPMENT_NOTES.md` | 经验归档 | Agent 开发经验，不作为功能路线 |
| `docs/archive/MLP_DEFENSE_NOTES.md` | 答辩归档 | MLP 答辩说明，不作为当前开发路线 |

## Agent 执行规则

1. 先读 `CLAUDE.md`。
2. 再读 `docs/current/DOCUMENTATION_STATUS.md`。
3. 任务和模拟交易有关时，读 `docs/current/PAPER_TRADING_M1_DESIGN.md`。
4. 记录进度时，写入 `docs/current/PROGRESS.md`。
5. 不读取 `docs/archive/**`，除非用户明确要求历史复盘或归档资料。
6. 若用户指定了阶段或文档，以用户当前指令优先。
