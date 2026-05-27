# 项目评审历程 (Review History)

---

## Review #1 — 2026-05-27（ChatGPT 评审 + 修复）

> 评审范围：迭代3 Skill系统重构完成后的全项目审查  
> 评审后提交：基础安全修复轮（本 commit）

### 发现的问题与修复

| # | 级别 | 问题 | 修复 |
|---|------|------|------|
| 1 | 高 | 前端 `innerHTML` 拼接用户输入/后端回复，存在 XSS 风险 | `index.html`: `addMsg`/`addLoading` 改为 `textContent` + DOM 创建 |
| 2 | 高 | `/chat` 异常时 `traceback.format_exc()` 返回完整堆栈到前端；`debug=True` 写死 | `app.py`: 改用 `logging.exception`，前端返回通用错误；`debug` 由 `FLASK_DEBUG` 环境变量控制 |
| 3 | 高 | 偏好记忆写死 `"default"`，不绑定当前 `session_id`，污染 `data/memory/default.json` | `agent.py`: `_dispatch` 加 `session_id` 参数；`tools.py`: 加 `_current_session_id` 全局变量，agent 调用前注入 |
| 4 | 中高 | 模型评估不适合时间序列：`train_test_split` 随机切分 + 全量数据 `fit` scaler | 文档化到 `PROJECT_ASSESSMENT.md` 4.3 和 8.1，标注为硬门槛 |
| 5 | 中 | `SkillGateway` 文档描述为"新主链路"，但实际主链路是 `agent._dispatch()` 直接 import Skill | `PROJECT_ASSESSMENT.md`: 降档表述，注明 Gateway 当前为辅助封装 |
| 6 | 中 | RAG 文档/依赖写 FAISS，实际实现为 NumPy 点积检索 | `PROJECT_ASSESSMENT.md` 4.7: 修正描述，注明小规模下 NumPy 足够 |

### 评审时项目状态

- **分支**：`iter3-skill-system`
- **迭代进度**：1/2/3 均已完成
- **核心能力**：行情/指标/新闻/RAG/记忆/Skill报告/规则+LLM双模式
- **关键短板**：LLM 离线、前端纯文本无图表、预测模型评估方式不当

### 建议路线

1. **短期（稳妥演示版）** → 已完成：修 XSS、隐藏 traceback、日志、session 贯通
2. **中期（好用版）** → 接 DeepSeek/Ollama；前端 ECharts 图表；SkillReport 结构化 JSON
3. **长期（可信投研版）** → 时间序列切分+滚动回测；候选池扩到 200+；选股并发化
