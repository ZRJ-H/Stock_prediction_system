# CC Autonomous Roadmap

本文件是给 Claude Code / CC 使用的自动推进路线图。CC 进入项目后，应先阅读本文件，再开始执行。目标是让项目从当前“稳定可交付雏形”继续推进到“演示效果强、功能闭环完整、文档完备、代码可审查”的最终版本。

## 0. 执行原则

CC 必须遵守以下原则：

- 先读本文件，再读项目源码。
- 严禁读取 `.claude/`、`.pytest_cache/`、`__pycache__/`、`.cache/`、任意 `cache/` 目录。
- 严禁使用 `git reset --hard`。
- 严禁回滚用户已有改动，除非用户明确要求。
- 严禁删除用户文件或运行产物，除非用户明确要求。
- 严禁提交 API key、token、密钥、账号密码。
- 严禁让测试依赖真实外部网络。
- 严禁让 `/health` 触发重型初始化，例如加载 embedding 模型、构建 RAG 索引、请求 LLM。
- 每完成一个阶段，必须执行代码管理流程，并更新本文件的进度记录。

搜索文件时使用：

```powershell
rg --files -g '!**/.claude/**' -g '!**/.pytest_cache/**' -g '!**/__pycache__/**' -g '!**/.cache/**' -g '!**/cache/**'
```

## 1. 当前项目状态

当前项目已经完成两轮交付修补：

```text
已完成：
- session_id 安全校验
- /memory 非法 session_id 返回 400
- /chat 非法 session_id 返回 400
- /health 轻量化，不触发 RAG 初始化
- RAG 初始化失败有明确提示
- 行情/K线/新闻/RAG 失败有日志或降级提示
- README 模型训练命令已修正
- CLAUDE.md 已记录自动推进方案
- 测试数量已扩展到 46 个
```

当前建议下一步：

```text
优先做 E1：前端 ECharts 图表增强。
```

原因：

- 图表对演示效果提升最大。
- 风险低于 LLM 接入和模型重训。
- 能让项目更像真正的股票分析系统。

## 2. 总路线

后续路线按 5 个阶段推进：

```text
E1 前端图表增强
E2 综合分析报告结构化
E3 LLM 智能模式增强
E4 模型训练与回测升级
E5 最终交付整理
```

推荐严格按顺序执行，不要跳阶段。

如果时间很紧，最小完成路线是：

```text
E1 前端图表增强
E5 最终交付整理
```

## 3. 每阶段通用工作流

每个阶段都必须执行以下流程。

### 3.1 开始前

```powershell
git status --short
pytest -q
rg --files -g '!**/.claude/**' -g '!**/.pytest_cache/**' -g '!**/__pycache__/**' -g '!**/.cache/**' -g '!**/cache/**'
```

如果 `git status --short` 不为空：

- 判断改动是否和本阶段相关。
- 相关则继续，但必须先理解改动。
- 无关则不要碰。
- 不要回滚用户改动。

### 3.2 开发中

- 小步修改。
- 每个功能点都补测试。
- 对外部 API 使用 mock 测试。
- 不要为了“看起来高级”引入大框架。
- 不要破坏原有 6 条核心演示链路。

核心 6 条演示链路：

```text
搜索 贵州茅台
查询 600519 行情
分析 600519 技术指标
评估 600519 风险
综合分析 600519
什么是金叉死叉
```

### 3.3 阶段完成后

必须执行：

```powershell
pytest -q
git diff --check
git diff --stat
git diff
git status --short
```

然后更新本文件的 `## 10. 进度记录`。

### 3.4 代码管理

阶段完成且验证通过后，进行提交：

```powershell
git add <本阶段相关文件>
git commit -m "<type>: <summary>"
```

提交信息格式：

```text
feat: add stock chart api and frontend
feat: standardize analysis reports
feat: improve llm assistant mode
feat: add model training workflow
docs: finalize delivery guide
```

提交前必须确认：

```text
[ ] pytest -q 通过
[ ] git diff --check 无实质错误
[ ] git diff 内容只包含本阶段改动
[ ] README/文档同步更新
[ ] 本文件进度记录已更新
```

提交后必须确认：

```powershell
git status --short
```

预期为空。

## 4. E1：前端 ECharts 图表增强

### 4.1 目标

让系统具备可视化股票走势能力，提升演示观感。

### 4.2 功能要求

新增后端接口：

```text
GET /api/stock/<code>/history?days=90
```

返回 JSON：

```json
{
  "code": "600519",
  "days": 90,
  "items": [
    {
      "date": "2026-01-01",
      "open": 100.0,
      "high": 105.0,
      "low": 98.0,
      "close": 102.0,
      "volume": 12345
    }
  ]
}
```

异常/无数据返回：

```json
{
  "error": "K线数据暂不可用"
}
```

HTTP 状态码建议：

```text
正常：200
非法股票代码：400
无数据/数据源失败：503 或 200 + error
```

推荐使用 503 表示数据源不可用。

### 4.3 前端要求

修改 `templates/index.html`：

- 增加图表区域。
- 使用 ECharts 展示：
  - 收盘价走势
  - MA5
  - MA20
  - 成交量
- 图表区域不要阻塞聊天。
- 如果图表数据失败，显示简短提示。
- 聊天回复仍使用 `textContent`，不要改成不安全 HTML 渲染。

触发图表的输入：

```text
查询 600519 行情
分析 600519 技术指标
600519 近90天走势
```

前端可以用正则从用户输入中提取 6 位股票代码，然后调用图表接口。

### 4.4 测试要求

必须新增或更新测试：

```text
[ ] GET /api/stock/600519/history 返回 200 和 items
[ ] 非法 code 返回 400
[ ] K线数据为空时返回明确错误
```

测试必须 mock `core.market_data.get_daily_kline`，不要访问真实腾讯 API。

### 4.5 README 要求

README 增加：

- 图表功能说明
- 图表接口说明
- 演示命令

### 4.6 验收标准

```text
[ ] /api/stock/<code>/history 可用
[ ] 前端有图表区域
[ ] 图表失败不影响聊天
[ ] 测试覆盖 API 成功/失败/非法参数
[ ] pytest -q 通过
[ ] git diff --check 无实质错误
[ ] README 已更新
[ ] 本文件进度记录已更新
```

推荐提交：

```text
feat: add stock history chart
```

## 5. E2：综合分析报告结构化

### 5.1 目标

让综合分析输出更像正式投研报告，结构稳定、易读、可演示。

### 5.2 输出结构

综合分析推荐统一为：

```text
【结论】
...

【技术面】
...

【基本面】
...

【风险】
...

【舆情】
...

【操作建议】
...

【免责声明】
数据仅供学习研究，不构成投资建议。
```

### 5.3 功能要求

- `ComprehensiveSkill` 必须容忍单个模块失败。
- 技术面失败不影响基本面。
- 新闻失败不影响风险分析。
- 每个失败模块输出明确降级提示。
- 不输出确定性买卖建议。

### 5.4 测试要求

必须覆盖：

```text
[ ] 综合分析正常输出包含固定章节
[ ] mock 某个子模块失败时，综合分析仍返回
[ ] 输出包含免责声明
```

### 5.5 验收标准

```text
[ ] 综合分析结构稳定
[ ] 子模块失败可降级
[ ] 测试通过
[ ] README 示例更新
[ ] 本文件进度记录已更新
```

推荐提交：

```text
feat: standardize analysis reports
```

## 6. E3：LLM 智能模式增强

### 6.1 目标

让配置了 OpenAI-compatible API 后的系统具备更自然的智能调度能力，同时保证 LLM 不可用时规则模式正常。

### 6.2 配置方式

README 必须说明：

```powershell
$env:OPENAI_API_KEY="your-key"
$env:OPENAI_BASE_URL="https://api.deepseek.com/v1"
$env:OPENAI_MODEL="deepseek-chat"
```

兼容：

```text
OpenAI
DeepSeek
通义千问
Ollama OpenAI-compatible endpoint
```

### 6.3 行为要求

- 无 API key：规则模式。
- 有 API key：LLM 模式。
- LLM 请求失败：自动降级规则模式。
- LLM 不得编造行情。
- LLM 必须先调用工具再分析。
- LLM 回复必须包含风险提示。

### 6.4 测试要求

不真实请求外部 API。必须 mock：

```text
LLMExplainer.chat()
```

测试：

```text
[ ] 无 key 使用规则模式
[ ] 有 key 进入 LLM 模式
[ ] LLM 返回 None 时降级规则模式
[ ] 工具调用结果能进入最终回复
```

### 6.5 验收标准

```text
[ ] LLM 配置文档清楚
[ ] LLM 失败自动降级
[ ] 不泄露 API key
[ ] pytest -q 通过
[ ] 本文件进度记录已更新
```

推荐提交：

```text
feat: improve llm assistant mode
```

## 7. E4：模型训练与回测升级

### 7.1 目标

让“股票预测”从简易演示升级为更可信的训练/评估流程。

### 7.2 新增脚本

新增：

```text
train_model.py
```

支持：

```powershell
python train_model.py --data dataset/tt.csv --model-dir models
```

### 7.3 训练要求

- 不使用随机切分作为主评估方式。
- 使用时间序列切分：

```text
前 70% 训练
中间 15% 验证
最后 15% 测试
```

- 输出回测/测试报告。

推荐报告：

```json
{
  "backend": "tensorflow_cnn",
  "sample_count": 1000,
  "accuracy": 0.58,
  "baseline_accuracy": 0.52,
  "test_start": "...",
  "test_end": "...",
  "window_size": 60
}
```

### 7.4 模型输出要求

预测结果必须谨慎：

```text
模型倾向：上涨
置信度：62%
说明：仅基于历史价格特征，不构成投资建议。
```

禁止：

```text
明天一定上涨
建议全仓买入
```

### 7.5 测试要求

```text
[ ] train_model.py 参数解析测试
[ ] 时间序列切分测试
[ ] 报告字段测试
[ ] 无 TensorFlow 时 MLP 降级测试
```

### 7.6 验收标准

```text
[ ] train_model.py 可运行
[ ] 生成 meta/report
[ ] README 模型说明更新
[ ] pytest -q 通过
[ ] 本文件进度记录已更新
```

推荐提交：

```text
feat: add model training workflow
```

## 8. E5：最终交付整理

### 8.1 目标

准备最终展示、答辩、提交。

### 8.2 新增 DEMO_SCRIPT.md

新增文件：

```text
DEMO_SCRIPT.md
```

内容：

```text
1. 环境安装
2. 启动服务
3. 打开页面
4. 演示 6 条核心命令
5. 展示图表
6. 展示综合分析
7. 展示 RAG 知识问答
8. 展示 LLM/模型不可用时的降级
9. 说明免责声明
```

### 8.3 README 最终整理

README 必须包含：

```text
项目简介
技术架构
核心功能
启动方式
演示命令
图表功能
LLM 配置
模型训练
测试方式
常见问题
免责声明
后续展望
```

### 8.4 最终验收

```powershell
pytest -q
git status --short
```

手动验证：

```text
搜索 贵州茅台
查询 600519 行情
分析 600519 技术指标
评估 600519 风险
综合分析 600519
什么是金叉死叉
```

### 8.5 推荐提交

```text
docs: finalize project delivery guide
```

## 9. 给 CC 的完整执行提示词

CC 可以直接使用下面的提示词：

```text
请读取 CC_AUTONOMOUS_ROADMAP.md，并严格按其中路线执行。

当前优先阶段是 E1：前端 ECharts 图表增强。不要先做 LLM、模型训练或最终文档，除非 E1 已完成并提交。

执行要求：
1. 开始前运行 git status --short 和 pytest -q。
2. 避开 .claude、缓存目录和运行产物目录。
3. 实现 GET /api/stock/<code>/history?days=90。
4. 前端 templates/index.html 增加图表区域，用 ECharts 展示收盘价、MA5、MA20、成交量。
5. 图表接口失败时前端显示降级提示，不影响聊天。
6. 增加 API 测试，mock K线数据源，不访问真实网络。
7. 更新 README。
8. 运行 pytest -q、git diff --check、git diff --stat、git diff。
9. 更新 CC_AUTONOMOUS_ROADMAP.md 的进度记录。
10. 验证通过后提交，推荐提交信息：feat: add stock history chart。

完成后输出：
- 修改了哪些文件
- 新增了哪些功能
- 测试结果
- git 提交 hash
- 剩余风险
- 下一阶段建议
```

## 10. 进度记录

CC 每完成一个阶段，必须在这里追加一条记录。不要覆盖旧记录。

记录格式：

```text
日期：
执行人：
阶段：
本次目标：
已完成：
- 
验证结果：
- pytest -q:
- git diff --check:
- git status --short:
代码管理：
- commit:
剩余风险：
下一步：
涉及文件：
```

### 记录 001

日期：2026-06-02
执行人：Codex
阶段：路线规划
本次目标：创建 CC 自动执行路线图
已完成：
- 新增 `CC_AUTONOMOUS_ROADMAP.md`
- 明确 E1-E5 阶段路线
- 明确每阶段验收标准
- 明确每阶段代码管理流程
- 明确进度记录模板
- 写入可直接给 CC 使用的完整执行提示词
验证结果：
- pytest -q: 未运行，本次仅新增路线文档
- git diff --check: 未运行
- git status --short: 未运行
代码管理：
- commit: 待提交
剩余风险：
- 尚未执行 E1 图表阶段
下一步：
- 让 CC 按本文件执行 E1：前端 ECharts 图表增强
涉及文件：
- CC_AUTONOMOUS_ROADMAP.md

### 记录 002

日期：2026-06-02
执行人：Claude Code (DeepSeek V4 Pro)
阶段：E1 — 前端 ECharts 图表增强
本次目标：新增股票历史K线 API + 前端 ECharts 走势图（收盘价/MA5/MA20/成交量）
已完成：
- 后端 API：GET /api/stock/<code>/history?days=90，支持代码校验（6位数字）、天数范围限制（1-365）、无数据返回 503
- 前端图表：ECharts 走势图面板（默认隐藏），自动从用户输入提取 6 位股票代码并加载图表
- 图表功能：收盘价折线 + MA5/MA20 虚线 + 成交量柱状图 + 十字光标 + 内滚轮缩放
- 降级设计：图表数据失败时显示错误提示（不阻塞聊天），关闭图表后聊天仍正常
- 测试覆盖：4 项新测试（正常返回/非法代码/无数据503/days参数传递），全部 mock 网络
- README 更新：API 路由表 + 图表功能说明 + 触发示例 + CDN 依赖说明
- 前端仍使用 textContent 渲染聊天消息，图表为独立 ECharts 实例，不引入 HTML 注入风险
验证结果：
- pytest -q: 50 passed in 1.31s
- git diff --check: 无实质错误（仅有 LF/CRLF 换行符警告）
- git status --short: M README.md, M app.py, M templates/index.html, M tests/test_core.py, ?? CC_AUTONOMOUS_ROADMAP.md
- 6 条核心演示链路未受影响
代码管理：
- commit: 待提交（推荐信息：feat: add stock history chart and frontend ECharts）
剩余风险：
- ECharts 依赖 jsDelivr CDN，离线环境下图表不显示（已做降级提示）。如需离线可用，可下载 echarts.min.js 到 static/ 目录
- 图表仅展示了收盘价/均线/成交量，未包含 K 线蜡烛图（后续可扩展）
下一步：
- 推荐按路线图进入 E2：综合分析报告结构化
涉及文件：
- app.py（+37 行：stock_history 路由）
- templates/index.html（+183 行：ECharts CDN + CSS + HTML 面板 + JS 逻辑）
- tests/test_core.py（+66 行：4 项 API 测试）
- README.md（+23 行：API 路由 + 图表功能章节）
- CC_AUTONOMOUS_ROADMAP.md（进度记录）
