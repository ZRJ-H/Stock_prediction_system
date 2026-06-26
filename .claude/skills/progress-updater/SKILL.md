---
name: progress-updater
description: Use this skill after completing code changes, debugging, refactoring, configuration changes, or experiment steps to update docs/current/PROGRESS.md.
---

# Progress Updater Skill

## Purpose

当 Claude Code 完成一个阶段或里程碑后，自动更新 `docs/current/PROGRESS.md` 追加进度记录。

## Trigger

用户说"记录进度""更新进度""update progress""阶段完成"时触发。Claude Code 在每阶段提交后也应主动触发。

## Action

1. 读取 `docs/current/PROGRESS.md` 确认当前最新记录。
2. 按模板追加新条目到文件末尾。
3. 不要覆盖或修改已有记录。

## Template

```markdown
---

## [阶段名称]（[状态]）

日期：YYYY-MM-DD
执行人：Claude Code
本次目标：[一句话]

已完成：
- [要点1]
- [要点2]

验证结果：
- pytest -q: N passed
- git diff --check: [clean / 具体问题]

剩余风险：
- [如有]

涉及文件：
- [文件1]
- [文件2]
```

## Rules

- 保持简洁，每条不超过 3 行展开。
- 不记录 token、API key、账号等敏感信息。
- 如果本阶段已记录在 `docs/archive/REVIEW_HISTORY.md`（里程碑级）或 `docs/archive/CC_AUTONOMOUS_ROADMAP.md`（路线图级），`docs/current/PROGRESS.md` 只需简短引用，不重复复制。
