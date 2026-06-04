# 项目进度记录 (Progress Log)

> 本文件是项目历程的统一入口，面向交接、复盘和期末答辩。
> 详细问题审查、修复过程和每个里程碑的完整记录见 [REVIEW_HISTORY.md](../REVIEW_HISTORY.md)。
> Claude Code / Agent 自动推进路线和执行流水见 [CC_AUTONOMOUS_ROADMAP.md](../CC_AUTONOMOUS_ROADMAP.md)。

---

## 1. 文件职责

| 文件 | 定位 | 适合查看的内容 |
|------|------|----------------|
| `docs/PROGRESS.md` | 项目时间线总览 | 项目从安全修复到答辩包装的完整历程 |
| `REVIEW_HISTORY.md` | 详细审查归档 | 每个问题的根因、修复方式、测试补充和里程碑细节 |
| `CC_AUTONOMOUS_ROADMAP.md` | Agent 执行路线 | E1-E7 自动推进目标、验收标准和执行流水 |
| `docs/DEFENSE_PACKAGE.md` | 答辩总包 | 5 分钟演示流程、PPT 大纲、答辩问答 |
| `docs/PROJECT_TECHNICAL_EXPLAINER.md` | 技术说明 | 给未参与代码组员理解架构和模块 |
| `docs/AGENT_DEVELOPMENT_NOTES.md` | Agent 经验 | 答辩讲技术心得、工具调用和防幻觉策略 |

---

## 2. 项目历程总览

| 阶段 | 日期 | 提交/状态 | 测试状态 | 核心交付 |
|------|------|-----------|----------|----------|
| Review #1 安全审查 | 2026-05-27 | `01f15a1` | 20 passed | 修复 XSS、traceback 泄露、session 串号；建立基础回归测试 |
| 阶段 A/B/C/D 收口 | 2026-06-02 | `51ab352` -> `66d2866` | 20 -> 43 passed | session 安全、health 轻量化、错误日志、预测降级、演示主线 |
| 交付修补迭代 | 2026-06-02 | 已完成 | 46 passed | `/chat` session 校验、RAG 不可用提示、新闻/RAG 日志补强 |
| M1 / E1 前端图表 | 2026-06-02 | `2199eb6` | 50 passed | 新增历史 K 线 API 与 ECharts 走势图 |
| M2 / E2 综合报告 | 2026-06-02 | `7c8361a` | 54 passed | 综合分析固定 7 章节，子模块失败可降级 |
| M3 / E3 LLM 智能模式 | 2026-06-03 | `c36b81a` -> `aba2f1c` | 59 passed | OpenAI-compatible function calling、反编造 prompt、LLM 失败回退规则模式 |
| M4 / E4 模型训练 | 2026-06-03 | `b0405c0` | 65 passed | `train_model.py`、时间序列切分、训练报告、MLP fallback |
| M5 / E5 交付整理 | 2026-06-03 | `3d7db01` | 65 passed | `DEMO_SCRIPT.md`、README 最终审查、演示链路整理 |
| M6 / E6 训练报告展示 | 2026-06-03 | `dc3660c` | 67 passed | `/api/model/report` 与前端训练报告面板 |
| M7 / E7 部署增强 | 2026-06-03 | `924eef4` | 69 passed | Dockerfile、`.dockerignore`、基础/可选依赖拆分、容器 HOST/PORT |
| M8 规则体系整理 | 2026-06-03 | 待提交/已完成 | 69 passed | `CLAUDE.md` 瘦身、`docs/PROGRESS.md` 承接进度、progress-updater skill |
| LLM 本地配置入口 | 2026-06-04 | 未提交改动 | 69 passed | `.env.example`、`core/config.py`、启动前加载 `.env` |
| 前端 LLM 配置指南 | 2026-06-04 | 未提交改动 | 69 passed | 页面顶部“配置指南”，前端不接收、不保存 API Key |
| 答辩包装文档 | 2026-06-04 | 未提交改动 | 文档改动未跑 pytest | `DEFENSE_PACKAGE.md`、`PROJECT_TECHNICAL_EXPLAINER.md`、`AGENT_DEVELOPMENT_NOTES.md` |
| 项目历程整合 | 2026-06-04 | 当前文档改动 | 文档改动待检查 | 重写本文件为项目时间线统一入口 |

> 注：测试数以对应阶段记录为准。部分路线图执行记录中测试数存在先后不一致，当前项目背景与最新验证结果以 `pytest -q: 69 passed` 为准。

---

## 3. 项目演进主线

项目最初是一个股票预测与问答雏形，逐步演进为“工具驱动的 A 股智能分析 Agent”。整体路线可以概括为：

```text
基础股票问答
  -> 安全审查与稳定性修复
  -> 工具系统 + RAG + 记忆 + Skill 报告
  -> 前端 ECharts 可视化
  -> 综合分析结构化
  -> LLM function calling 智能调度
  -> 模型训练 CLI 与训练报告
  -> Docker 部署与配置入口
  -> 答辩包装与项目历程归档
```

核心变化不是简单增加功能，而是逐步把项目从“单点 demo”整理成“可演示、可降级、可测试、可交接”的课程项目。

---

## 4. 项目包装定位

期末答辩建议不要把项目包装成“承诺收益的股票预测系统”，而要包装成：

> 面向 A 股场景的可控 AI 分析 Agent：LLM + RAG + 机器学习 + Harness。

这个定位更符合“人工智能创新实现”课程要求，也更符合项目真实实现。项目里的 AI 使用不是简单调用大模型聊天，而是由四类能力组合完成：

| AI 能力 | 项目实现 | 答辩讲法 |
|---------|----------|----------|
| LLM Agent | OpenAI-compatible function calling | 负责自然语言理解、工具选择和结果总结 |
| RAG 知识库 | Markdown 知识库 + embedding + NumPy 相似度检索 | 回答投资知识问题，减少自由生成的不确定性 |
| 机器学习模型 | CNN/MLP 双后端涨跌二分类 | 展示历史序列建模、训练报告和时间序列切分 |
| 规则基线 | 13 类关键词意图识别 | 无 API Key 时仍可稳定演示和降级 |

同时，项目用 harness 思路保证 AI 链路可验证。这里的 harness 不是单个独立文件，而是一组验收机制：

- 固定 6 条核心演示命令：搜索、行情、技术指标、风险、综合分析、RAG。
- `pytest -q: 69 passed` 覆盖核心路由和边界。
- mock LLM、行情、RAG、模型报告等外部依赖，测试不依赖真实外网。
- `/health` 轻量检查模型、LLM、RAG 状态，不触发重型初始化。
- `git diff --check` 做交付前格式检查。
- 失败路径纳入验收：LLM 失败回退规则模式、RAG 不可用返回提示、模型未训练有 fallback 或引导。

推荐答辩表述：

> 我们最终交付的不是一个承诺收益的股票预测器，而是一个可控、可验证、可降级的 A 股智能分析 Agent。它把 LLM、RAG、机器学习模型和规则基线整合到同一个工具调度框架中，并通过 harness 保证关键 AI 链路可复现。

---

## 5. 各阶段摘要

### Review #1：安全审查与基础修复

日期：2026-05-27

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 的 `Review #1`。

本阶段通过一次系统性代码审查发现高风险问题：

- 前端 `innerHTML` 拼接存在 XSS 风险。
- Flask `/chat` 异常返回 traceback，可能泄露路径和模块结构。
- `debug=True` 写死，不适合演示或部署。
- 用户偏好写死到 `default`，不同 session 会互相污染。
- 训练评估存在随机切分和全量归一化导致的未来信息泄漏风险。
- SkillGateway、RAG/FAISS 等文档表述与实现不完全一致。

完成结果：

- 前端消息渲染改为 `createElement` + `textContent`。
- 后端异常改为服务端日志，前端只返回通用错误。
- Flask debug 改为由 `FLASK_DEBUG` 控制。
- 偏好记忆按 session 隔离。
- 新增 20 个回归测试。

阶段意义：

> 项目从“功能完整但未经审查的原型”提升为“能通过基础安全审查的稳妥演示版”。

---

### 阶段 A/B/C/D：交付前收口

日期：2026-06-02

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 与旧版 `docs/PROGRESS.md`。

本阶段目标是把项目推进到可交付状态。

阶段 A：安全与稳定性收口

- `core/memory.py` 新增 session_id 校验与安全路径处理。
- `/health` 不再触发 RAGService 重型初始化。
- `market_data.py`、`tools.py` 异常增加 warning 日志。
- 预测模块增加均线交叉 fallback 与 CNN/MLP 双后端。

阶段 B：测试闭环

- `tests/test_core.py` 从 20 项扩展到 43 项。

阶段 C：演示主线

- 规则模式下 6 条核心链路可跑通：
  - `搜索 贵州茅台`
  - `查询 600519 行情`
  - `分析 600519 技术指标`
  - `评估 600519 风险`
  - `综合分析 600519`
  - `什么是金叉死叉`

阶段 D：文档与交付

- README 增加演示命令表和 FAQ。

验证结果：

- `pytest -q: 43 passed`

---

### 交付修补迭代：接口边界与降级提示

日期：2026-06-02

本阶段修补交付前的细节问题：

- README 模型训练命令修正。
- `/chat` 对非法非空 session_id 返回 400。
- RAG 初始化失败时返回明确提示。
- 新闻模块静默降级改为记录 warning。
- RAGService 初始化异常分支记录 warning。
- 增加 chat session 校验和 RAG 不可用提示测试。

验证结果：

- `pytest -q: 46 passed`

阶段意义：

> 让错误更可见、接口边界更清楚、演示时的异常更容易解释。

---

### M1 / E1：前端 ECharts 图表增强

日期：2026-06-02

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 的 `里程碑 M1`、[CC_AUTONOMOUS_ROADMAP.md](../CC_AUTONOMOUS_ROADMAP.md) 记录 002。

核心交付：

- 新增 `GET /api/stock/<code>/history?days=90`。
- 股票代码必须是 6 位数字，非法返回 400。
- K 线无数据返回 503 与明确错误。
- 前端集成 ECharts。
- 输入包含 6 位代码时自动展示收盘价、MA5、MA20 和成交量。
- 图表失败只显示降级提示，不影响聊天。

测试补充：

- API 正常返回。
- 非法代码返回 400。
- 无 K 线返回 503。
- days 参数正确传递。

验证结果：

- `pytest -q: 50 passed`

阶段意义：

> 项目从纯聊天文本展示升级为“聊天 + 图表”的可视化分析工具，演示观感明显增强。

---

### M2 / E2：综合分析报告结构化

日期：2026-06-02

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 的 `里程碑 M2`、[CC_AUTONOMOUS_ROADMAP.md](../CC_AUTONOMOUS_ROADMAP.md) 记录 003。

核心交付：

- 重构 `ComprehensiveSkill`。
- 综合分析固定输出 7 个章节：
  - 【结论】
  - 【技术面】
  - 【基本面】
  - 【风险】
  - 【舆情】
  - 【操作建议】
  - 【免责声明】
- 子模块独立 try/except，某一维度失败不影响其他维度。
- 操作建议避免确定性买卖指令。
- 免责声明作为独立章节。

测试补充：

- 固定章节存在且顺序正确。
- 子模块失败仍能输出完整报告。
- 免责声明在操作建议之后。
- 不出现“建议买入/卖出”等确定性指令。

验证结果：

- `pytest -q: 54 passed`

阶段意义：

> 综合分析从“拼接式输出”升级为“结构化投研报告样式”，更适合展示和答辩。

---

### M3 / E3：LLM 智能模式增强

日期：2026-06-03

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 的 `里程碑 M3`、[CC_AUTONOMOUS_ROADMAP.md](../CC_AUTONOMOUS_ROADMAP.md) 记录 004。

核心交付：

- 强化 `core/agent.py` 的 System Prompt。
- 明确要求 LLM 不得编造行情、价格、涨跌幅、成交量、财务指标。
- LLM 必须先调用工具获取数据，再进行分析。
- 工具失败时要说明数据不可用。
- `/health` 增加 `llm_base_url` 和 `llm_model`。
- README 增加 DeepSeek、OpenAI、通义千问、Ollama 配置示例。

测试补充：

- LLM 失败自动回退规则模式。
- mock 工具调用流程，验证工具结果进入第二轮 messages。
- 无 API Key 时不进入 LLM 模式。
- `/health` LLM 元信息字段正确。

验证结果：

- `pytest -q: 59 passed`

阶段意义：

> LLM 被定位为“工具调度器”，而不是“股票数据生成器”，这是项目防止幻觉的关键设计。

---

### M4 / E4：模型训练与回测升级

日期：2026-06-03

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 的 `里程碑 M4`、[CC_AUTONOMOUS_ROADMAP.md](../CC_AUTONOMOUS_ROADMAP.md) 记录 005。

核心交付：

- 新增 `train_model.py` CLI。
- 支持 `--data`、`--model-dir`、`--epochs`、`--batch-size`。
- 新增时间序列切分：70% 训练、15% 验证、15% 测试。
- Scaler 仅在训练段 fit，避免未来信息泄漏。
- 训练报告包含：
  - backend
  - sample_count
  - window_size
  - train/val/test accuracy
  - baseline_accuracy
  - 日期区间
  - model_files
- TensorFlow 不可用时自动使用 sklearn MLP fallback。

测试补充：

- 时间序列切分顺序。
- 三个数据集互不相交。
- CLI 默认参数和自定义参数。
- 训练报告字段完整。
- 小样本切分为空时抛出 ValueError。

验证结果：

- `pytest -q: 65 passed`

阶段意义：

> 模型预测从“已有模型调用”升级为“训练、评估、报告、展示前置”的闭环，并修正了时间序列评估中的未来泄漏风险。

---

### M5 / E5：最终交付整理

日期：2026-06-03

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 的 `里程碑 M5`、[CC_AUTONOMOUS_ROADMAP.md](../CC_AUTONOMOUS_ROADMAP.md) 记录 006。

核心交付：

- 新增 `DEMO_SCRIPT.md`。
- 演示脚本覆盖：
  - 环境准备
  - 服务启动
  - 前端访问
  - 6 条核心命令
  - 图表功能
  - LLM 模式
  - 模型训练
  - FAQ 降级
  - 测试验证
  - 免责声明
- README 最终审查，补充 `train_model.py` 和模型训练说明。

验证结果：

- `pytest -q: 65 passed`

阶段意义：

> 项目开始从“开发完成”转向“可演示、可交接、可验收”。

---

### M6 / E6：模型训练报告产品化展示

日期：2026-06-03

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 的 `里程碑 M6`、[CC_AUTONOMOUS_ROADMAP.md](../CC_AUTONOMOUS_ROADMAP.md) 记录 007。

核心交付：

- 新增 `GET /api/model/report`。
- 报告存在时返回完整训练报告。
- 报告不存在或损坏时返回 `available=false` 和引导提示。
- 前端新增训练报告面板。
- 页面加载时自动读取训练报告。
- 展示后端、样本数、窗口大小、训练/验证/测试准确率、基线准确率和日期区间。
- 面板不影响聊天和图表。

测试补充：

- 报告存在时返回 `available=true`。
- 报告不存在时返回 `available=false` 和引导文案。

验证结果：

- `pytest -q: 67 passed`

阶段意义：

> 模型训练结果不再只存在于命令行和 JSON 文件里，而是进入 Web 界面，形成更完整的产品体验。

---

### M7 / E7：部署交付增强

日期：2026-06-03

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 的 `里程碑 M7`、[CC_AUTONOMOUS_ROADMAP.md](../CC_AUTONOMOUS_ROADMAP.md) 记录 008。

核心交付：

- `requirements.txt` 轻量化，只保留基础运行/测试依赖。
- 新增 `requirements-optional.txt`，放置 TensorFlow、AKShare、sentence-transformers、faiss-cpu 等重依赖。
- 新增 `Dockerfile`。
- 新增 `.dockerignore`，排除 Git、缓存、模型权重、训练报告、RAG 索引等运行产物。
- `app.py` 支持通过 `HOST` 和 `PORT` 环境变量控制监听地址。
- README 和 `DEMO_SCRIPT.md` 增加 Docker 部署说明。

验证结果：

- `pytest -q: 69 passed`

已知风险：

- Docker 镜像未在当前环境实际 build 验证。
- 容器默认不安装 TensorFlow/RAG/AKShare 重依赖，相关能力依赖降级策略或扩展安装。

阶段意义：

> 项目具备了基础部署说明和依赖边界，便于提交、展示和后续扩展。

---

### M8：规则体系与项目流程整理

日期：2026-06-03

详细来源：[REVIEW_HISTORY.md](../REVIEW_HISTORY.md) 的 `里程碑 M8`。

核心交付：

- `CLAUDE.md` 瘦身，只保留长期项目规则。
- 临时路线、历史流水和执行提示从 `CLAUDE.md` 中移出。
- `docs/PROGRESS.md` 承接日常阶段记录。
- 新增 `.claude/skills/progress-updater/SKILL.md`，定义进度追加模板。
- `.gitignore` 放行 `.claude/skills/**/SKILL.md`，方便提交项目级流程定义。

验证结果：

- 最新背景记录为 `pytest -q: 69 passed`

阶段意义：

> 项目不只整理代码，也整理了 Agent 协作规则、进度记录位置和长期维护方式。

---

### 2026-06-04：LLM 本地配置入口

核心交付：

- 新增 `.env.example`。
- 新增 `core/config.py`，实现轻量 `.env` 解析，不引入第三方依赖。
- `app.py` 在初始化 `StockAgent` 前加载本地 `.env`。
- README 补充本地配置文件入口。
- 测试补充 `.env` 读取与环境变量优先级。

安全边界：

- `.env` 已被 `.gitignore` 忽略。
- 不提交真实 API Key。
- 修改 `.env` 后需要重启 `python app.py`。

验证结果：

- `pytest -q: 69 passed`
- `git diff --check` 通过，仅 Windows CRLF 提示

阶段意义：

> LLM 配置从“只靠环境变量”升级为“本地 `.env` 模板 + 安全说明”，更适合普通组员和答辩环境使用。

---

### 2026-06-04：前端 LLM 配置指南

核心交付：

- 页面顶部 `LLM离线` 状态旁新增“配置指南”按钮。
- 指南面板展示 `.env.example` -> `.env` -> 重启服务的步骤。
- 前端只展示说明，不接收、不保存、不上传 API Key。
- README 补充页面配置指南说明。

验证结果：

- `pytest -q: 69 passed`
- `git diff --check` 通过，仅 Windows CRLF 提示

阶段意义：

> 降低 LLM 模式启用门槛，同时避免前端处理密钥造成安全风险。

---

### 2026-06-04：期末答辩包装

核心交付：

- 新增 `docs/DEFENSE_PACKAGE.md`：
  - 需求拆解
  - 5 分钟演示流程
  - PPT 页面大纲
  - 系统架构图、功能流程图、LLM/规则双模式图
  - 答辩问答
  - 免责声明
- 新增 `docs/PROJECT_TECHNICAL_EXPLAINER.md`：
  - 给未参与代码的组员讲清楚架构、模块、数据流、LLM/规则模式、RAG、模型训练、测试和部署。
- 新增 `docs/AGENT_DEVELOPMENT_NOTES.md`：
  - 给答辩主讲人总结规则模式、function calling、工具注册、降级、防幻觉和可测试性。

验证结果：

- 文档改动已运行 `git diff --check`，通过，仅 Windows CRLF 提示。
- 因未修改业务代码，未运行 pytest。

阶段意义：

> 项目从功能交付进入答辩呈现阶段，材料可直接分配给组员制作 PPT 和准备讲稿。

---

### 2026-06-04：项目历程整合

本次目标：

- 将 Review #1、阶段 A/B/C/D、M1-M8、06-04 配置与答辩包装整合进 `docs/PROGRESS.md`。
- 让 `PROGRESS.md` 成为项目时间线统一入口。
- 保留 `REVIEW_HISTORY.md` 和 `CC_AUTONOMOUS_ROADMAP.md` 作为详细归档，不重复粘贴所有审查细节。

本次原则：

- 只修改文档。
- 不修改业务代码。
- 不读取缓存目录。
- 不提交真实 API Key。

---

## 6. 当前项目状态

截至 2026-06-04，项目主要功能已经完成：

- Flask + 原生前端 Web 聊天界面。
- 股票搜索、实时行情、历史 K 线和 ECharts 走势图。
- 技术指标、风险评估、新闻舆情、基本面、综合分析报告。
- RAG 本地知识库。
- LLM function calling 在线模式。
- 规则引擎离线模式。
- 工具注册系统与 Skill 技能系统。
- CNN/MLP 双后端模型预测。
- `train_model.py` 模型训练 CLI 与训练报告。
- `/api/model/report` 训练报告展示。
- Docker 基础部署。
- `.env.example` 和本地 LLM 配置入口。
- 期末答辩包装文档。

当前测试背景：

- 最新已知验证结果：`pytest -q: 69 passed`
- 本次项目历程整合仅改文档，完成后只需运行 `git diff --check`

当前工程边界：

- `.env` 不提交。
- 真实 API Key 不提交。
- 外部行情、新闻、RAG embedding、LLM、TensorFlow 都可能因环境不同而不可用，但系统有降级策略。
- 股票预测结果仅供课程学习和研究展示，不构成投资建议。

---

## 7. 答辩可用总结

项目历程可以用下面这段话概括：

> 本项目从一个股票预测和问答原型开始，先通过代码审查修复了 XSS、traceback 泄露、session 串号等安全问题，再逐步补齐工具系统、RAG 知识库、会话记忆、Skill 结构化报告、前端 ECharts 图表、LLM function calling、模型训练 CLI、训练报告展示和 Docker 部署。最后通过 `.env` 配置入口和答辩文档包装，把项目整理成一个可演示、可降级、可测试、可交接的 A 股智能分析助手。系统强调工具取数和风险提示，所有预测与分析仅供学习研究，不构成投资建议。
