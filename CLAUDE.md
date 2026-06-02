# Claude Code Project Guide

本文件是 Claude Code 进入本项目后的自动执行指南。目标是让项目尽快从“能跑”推进到“可演示、可交付、可审查”。Claude Code 应优先读取并遵循本文，不需要读取 `.claude/`、缓存目录或运行产物目录。

## 0. 项目目标

本项目是一个基于 Flask 的 A 股股票分析助手，包含：

- Web 聊天界面
- 股票搜索、行情、K 线、技术指标
- 技术分析、风险评估、新闻舆情、综合分析等 Skill
- 可选 LLM 工具调用
- 可选 RAG 投资知识库
- 可选 CNN/MLP 股票涨跌预测模型
- 用户 session 记忆和偏好保存

当前开发目标不是继续无限扩功能，而是尽快完成一个稳定版本：

```text
可运行 -> 可演示 -> 可测试 -> 可说明 -> 可交付
```

最终交付标准：

- `python app.py` 能启动 Web 服务。
- 核心 6 条演示链路可用。
- `pytest -q` 通过。
- README 能让别人按步骤运行。
- 安全和错误处理不出现明显硬伤。
- 模型、LLM、AKShare 不可用时系统仍能优雅降级。

## 1. 禁止读取和修改的内容

Claude Code 不应读取、依赖或修改以下内容：

- `.claude/`
- `.pytest_cache/`
- `__pycache__/`
- `.cache/`
- 任意 `cache/` 目录
- 运行生成的模型文件，除非明确是在训练/验证模型
- 用户未要求处理的无关文件

搜索文件时使用：

```powershell
rg --files -g '!**/.claude/**' -g '!**/.pytest_cache/**' -g '!**/__pycache__/**' -g '!**/.cache/**' -g '!**/cache/**'
```

## 2. 当前项目结构

重点文件：

```text
app.py                         Flask 入口，包含 /chat /memory /health
templates/index.html           前端聊天界面
core/agent.py                  意图识别、LLM/规则双模式调度
core/tools.py                  工具注册和工具执行
core/market_data.py            腾讯行情/K线、股票搜索
core/indicators.py             技术指标
core/model_service.py          CNN/MLP 模型服务
core/data_pipeline.py          训练/推理数据处理
core/memory.py                 session 记忆和用户偏好
core/rag_service.py            投资知识库 RAG
core/news.py                   新闻舆情
core/fundamentals.py           基本面/AKShare
core/screener.py               选股引擎
core/skills/                   技术、风险、新闻、综合分析等 Skill
tests/test_core.py             当前最小回归测试
README.md                      项目说明
requirements.txt               依赖
```

当前重点不是大改架构，而是补齐稳定性、安全、测试和交付说明。

## 3. 核心演示链路

必须优先保证以下 6 条链路能跑通：

```text
1. 搜索股票
   输入：搜索 贵州茅台
   预期：返回 600519 / 贵州茅台 等搜索结果

2. 实时行情
   输入：查询 600519 行情
   预期：返回最新价、涨跌幅、成交量等字段；若网络失败，返回明确错误提示

3. 技术分析
   输入：分析 600519 技术指标
   预期：返回均线、MACD、RSI、BOLL/KDJ 或综合技术评分

4. 风险评估
   输入：评估 600519 风险
   预期：返回波动率、回撤、风险等级、仓位/止损建议

5. 综合分析
   输入：综合分析 600519
   预期：整合技术面、基本面、风险、新闻/舆情，缺数据时优雅降级

6. 投资知识
   输入：什么是金叉死叉
   预期：RAG 可用时返回知识库内容；不可用时返回明确初始化/依赖提示
```

其他功能，如全 A 选股、CNN 预测、LLM function calling、AKShare 财报，是加分项，不应阻塞核心交付。

## 4. 开发路线

### 阶段 A：安全和稳定性收口

优先级最高。先做这些，不要先加新功能。

1. 修复 `session_id` 路径风险
   - 在 `core/memory.py` 增加 session_id 校验。
   - 只允许字母、数字、下划线、短横线。
   - 推荐长度限制：`1 <= len(session_id) <= 80`。
   - 禁止 `/`、`\`、`.`、空白字符。
   - 保存/读取偏好时，校验最终路径必须仍在 `data/memory` 下。
   - `/memory` API 对非法 session 返回 400。

2. 改造 `/health`
   - `/health` 不应触发 RAG 模型加载或索引构建。
   - 只做轻量检查：
     - Flask 状态
     - 模型文件是否存在
     - LLM API key 是否配置
     - RAG 索引文件是否存在
   - RAG 的真正初始化只在知识检索时懒加载。

3. 外部数据源错误提示
   - 腾讯行情/K线失败时，返回“网络不可用/数据源无响应/股票代码不存在”等明确提示。
   - AKShare 未启用时，返回“未启用 AKShare，设置 USE_AKSHARE=1 后可用”。
   - 不要把所有异常静默吞掉。至少记录日志。

4. 预测模型降级
   - 模型不存在时，`predict_stock` 不应显得像系统坏了。
   - 返回：
     - “模型尚未训练”
     - “当前可使用技术指标/趋势作为辅助判断”
     - “可运行训练脚本生成模型”
   - 如果时间不够，不要强行把 CNN 做成核心功能。

### 阶段 B：最小测试闭环

目标是保证核心链路不被后续修改破坏。

必须新增测试：

1. Flask API
   - `/chat` 空 query 返回提示
   - `/memory` 缺少 session_id 返回 400
   - `/memory` 非法 session_id 返回 400
   - `/health` 快速返回，不触发 RAG 初始化

2. Memory
   - 合法 session_id 能保存偏好
   - 非法 session_id 被拒绝
   - 不同 session_id 偏好隔离

3. Tools
   - mock `get_realtime_quote`
   - mock `get_daily_kline`
   - 技术分析/风险评估/预测降级能返回可读文本

4. RAG
   - 索引不存在时返回明确提示
   - 初始化失败时不抛异常到前端

测试要求：

```powershell
pytest -q
```

必须通过后才能算完成当前阶段。

### 阶段 C：演示主线打磨

固定 6 条演示输入，把输出做得清晰、稳定。

建议统一输出格式：

```text
【结论】
...

【关键数据】
...

【分析】
...

【风险提示】
数据仅供参考，不构成投资建议。
```

对于缺失数据：

```text
该数据源当前不可用，因此本次分析跳过该维度。
```

不要因为某一个维度失败导致综合分析整体失败。

### 阶段 D：文档和交付

README 必须包含：

- 项目简介
- 环境安装
- 启动方式
- 可选环境变量
- 核心演示问题
- 模型训练说明，如果有
- RAG 知识库说明
- 常见问题
- 投资免责声明

推荐 README 的演示部分写死这些命令/问题：

```text
搜索 贵州茅台
查询 600519 行情
分析 600519 技术指标
评估 600519 风险
综合分析 600519
什么是金叉死叉
```

## 5. 代码管理规则

每次开始工作前：

```powershell
git status --short
rg --files -g '!**/.claude/**' -g '!**/.pytest_cache/**' -g '!**/__pycache__/**' -g '!**/.cache/**' -g '!**/cache/**'
```

不要撤销用户已有改动。发现脏工作区时：

- 只处理本任务相关文件。
- 不使用 `git reset --hard`。
- 不使用 `git checkout --` 回滚文件，除非用户明确要求。
- 不删除运行产物，除非用户明确要求。

每完成一个阶段后：

```powershell
pytest -q
git diff --stat
git diff
```

如果需要提交，提交信息使用：

```text
fix: harden session and health checks
test: add api and memory regressions
docs: add delivery guide and demo script
```

## 6. 审查清单

每次改完代码后，按下面顺序审查。

### 安全

- `session_id` 是否经过校验？
- 文件路径是否可能被用户输入控制？
- Flask debug 是否默认关闭？
- 前端是否会渲染未转义 HTML？当前应使用 `textContent`。
- API key 是否只从环境变量读取？

### 稳定性

- 外部接口失败是否有明确提示？
- 网络超时是否设置？
- RAG 是否会阻塞 `/health`？
- 模型不存在时是否能降级？
- 综合分析是否能容忍部分模块失败？

### 测试

- 是否覆盖新增逻辑？
- 是否 mock 外部网络？
- 是否避免测试写入真实 `data/memory`？
- `pytest -q` 是否通过？

### 用户体验

- 输出是否是中文？
- 是否给出结论和风险提示？
- 错误提示是否能让用户知道下一步？
- 演示问题是否都能跑？

### 交付

- README 是否同步？
- requirements 是否准确？
- 生成文件是否被 `.gitignore` 正确处理？

## 7. Claude Code 执行提示词

Claude Code 可以把下面这段作为工作提示词执行：

```text
你是本项目的自动开发和审查代理。请先阅读 CLAUDE.md，并严格避开 .claude、缓存目录和运行产物目录。

你的目标是把项目尽快推进到可演示、可测试、可交付状态。

优先级：
1. 修复 session_id 安全和路径风险。
2. 改造 /health，使其不触发 RAG 初始化。
3. 优化外部数据源和模型不可用时的降级提示。
4. 补充 Flask API、memory、tools、RAG 的最小测试。
5. 跑 pytest -q。
6. 更新 README 的运行说明和演示脚本。
7. 更新 CLAUDE.md 的进度记录区，说明完成了什么、剩余什么。

工作规则：
- 不读取 .claude 和缓存目录。
- 不回滚用户未要求回滚的改动。
- 尽量小步提交，每一步都能解释。
- 所有新增风险点必须有测试或明确说明。
- 最终回答要包含：改了什么、验证结果、剩余风险、下一步建议。
```

## 8. 自主推进规则

Claude Code 不需要每一步都询问用户。可以自主执行：

- 阅读非禁止目录下源码
- 修改项目源码
- 新增测试
- 运行 `pytest -q`
- 更新 README
- 更新本文件进度记录

遇到以下情况才需要暂停询问：

- 需要安装新依赖
- 需要联网下载模型或数据
- 需要删除文件
- 需要重置 Git 历史
- 需要改变项目核心方向，例如从 Flask 改成 FastAPI

## 9. 推荐任务拆分

### Task 1：Session 安全

修改：

- `core/memory.py`
- `app.py`
- `tests/test_core.py` 或新增 `tests/test_api.py`

目标：

- 非法 session_id 被拒绝。
- 合法 session_id 正常工作。
- 不允许路径穿越。

验收：

```powershell
pytest -q
```

### Task 2：Health 轻量化

修改：

- `app.py`
- 必要时 `core/rag_service.py`
- 新增/更新测试

目标：

- `/health` 不加载 sentence-transformers。
- `/health` 不构建 RAG index。
- 返回 `rag_ready` 或 `rag_index_exists`。

验收：

```powershell
pytest -q
```

### Task 3：错误提示和日志

修改：

- `core/market_data.py`
- `core/tools.py`
- `core/rag_service.py`
- `core/news.py`
- `core/fundamentals.py`

目标：

- 外部失败可定位。
- 前端显示可读提示。
- 不把异常堆栈暴露给用户。

验收：

```powershell
pytest -q
```

### Task 4：预测降级

修改：

- `core/tools.py`
- `core/model_service.py`
- README

目标：

- 无模型时返回友好提示。
- 不要求 TensorFlow 必须可用。
- 如果有训练脚本，则写清楚训练命令。

验收：

```powershell
pytest -q
```

### Task 5：README 和演示脚本

修改：

- `README.md`

目标：

- 新用户按 README 能启动。
- 明确核心 6 条演示输入。
- 明确可选依赖和降级行为。

验收：

```powershell
pytest -q
```

## 10. 进度记录

Claude Code 每次完成工作后，应更新本节。格式如下：

```text
日期：
执行人：
本次目标：
已完成：
验证结果：
剩余问题：
下一步：
涉及文件：
```

### 2026-06-02 — Claude Code 迭代3收口

日期：2026-06-02
执行人：Claude Code (Claude Opus 4.7)
本次目标：按 CLAUDE.md 路线图补齐 A/B/C/D 四阶段，推进到可交付状态
已完成：

阶段 A（安全与稳定性收口）：
- [A1] Session 安全：memory.py 新增 validate_session_id() + _safe_memory_path()，校验长度/字符集/路径穿越；app.py /memory 端点对非法 session 返回 400
- [A2] Health 轻量化：/health 不再实例化 RAGService，仅检查 INDEX_PATH 文件是否存在，避免加载 sentence-transformers
- [A3] 错误日志：market_data.py 行情/K线异常记录 warning 日志；tools.py 模型预测降级记录日志
- [A4] 预测降级：此前已完成（均线交叉 fallback + MLP/CNN 双后端）

阶段 B（测试闭环）：
- tests/test_core.py 从 20 个扩展到 43 个：
  - 新增 session_id 校验 11 项（合法/空/路径穿越/XSS/命令注入/超长/保存拦截/偏好拒绝）
  - 新增 Flask API 测试 7 项（/chat 空/正常, /memory GET/POST 缺参/非法, /health 状态/轻量）
  - 新增 RAG 降级测试 2 项（未初始化提示、初始化失败不抛异常）
- 43 tests passed, 1.71s

阶段 C（演示主线）：6 条核心链路均可在无 LLM/无模型场景下跑通（规则引擎 + 降级）

阶段 D（文档与交付）：
- README.md 新增：核心演示命令表（6条）、模型训练说明、常见问题 FAQ

验证结果：
- pytest -q: 43 passed in 1.71s
- session_id 安全：非法输入全部被 400 拒绝
- /health: 无 RAG 初始化，轻量级文件检查
- 6 条核心链路：规则模式均可跑通

剩余问题：
- (建议下一步) 接入 LLM：配置 OPENAI_API_KEY 让系统从规则模式升级为智能模式
- (建议下一步) 前端图表：ECharts 展示 K线/均线/MACD/RSI
- (后续) 模型升级：真实行情数据 + 滚动回测重新训练

下一步：
- (可选) git push + 接入 LLM 测试智能模式
- (可选) 前端 ECharts 可视化

涉及文件：
- core/memory.py（session_id 校验 + 安全路径）
- app.py（/memory 校验 + /health 轻量化）
- core/market_data.py（错误日志）
- core/tools.py（模型降级日志）
- tests/test_core.py（+23 项测试）
- README.md（演示命令 + FAQ）
- CLAUDE.md（进度更新）

## 11. 最终完成标准

当满足以下条件时，可以认为项目 coding 基本完成：

```text
[x] pytest -q 全部通过
[x] /chat 空输入和正常输入都表现正确
[x] /memory 对非法 session_id 返回 400
[x] /health 不触发 RAG 初始化
[x] 六条核心演示链路可用或有明确降级提示
[x] 模型不存在时预测功能不报错
[x] README 包含运行、演示、可选依赖、免责声明
[x] 本文件进度记录已更新
```

完成后，最后一次审查应输出：

```text
1. 已完成内容
2. 验证命令和结果
3. 剩余风险
4. 后续可选增强
```
