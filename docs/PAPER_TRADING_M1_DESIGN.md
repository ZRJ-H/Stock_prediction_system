# Paper Trading M1 审计与设计

## 状态与边界

- 当前阶段：M1 项目审查和设计
- 工作分支：`feature/paper-trading`
- 本阶段只产出设计文档，不实现数据库、交易引擎、API、前端、定时任务或 Excel 导出。
- 新功能只做自动模拟交易与技术演示，不接入真实券商交易接口，不下真实订单，不处理真实资金。

## 当前项目结构

当前项目是 Flask A 股股票分析助手，核心结构如下：

```text
Stock_prediction_system/
├── app.py                    # Flask 入口和 REST API
├── Dockerfile                # python:3.11-slim 轻量容器
├── requirements.txt          # 基础依赖，当前未包含 openpyxl
├── core/
│   ├── agent.py              # LLM/规则双模式调度
│   ├── blind_test.py         # 现有 SQLite 服务模式
│   ├── config.py             # .env 轻量加载
│   ├── market_data.py        # 腾讯行情和 K 线数据
│   ├── model_service.py      # CNN/MLP 模型训练与预测
│   ├── tools.py              # 工具注册和执行
│   └── skills/               # 技术/基本面/风险/新闻/综合分析 Skill
├── templates/index.html      # 单页原生 HTML/CSS/JS + ECharts
├── tests/test_core.py        # 核心回归/API/Skill 测试
├── tests/test_blind_test.py  # SQLite 盲测服务测试
└── scripts/                  # 离线盲测数据准备脚本
```

## 现有 Flask 路由风格

`app.py` 目前集中注册路由，成功响应使用 `jsonify(...)`，错误通常返回 `jsonify({"error": message}), status_code`。

可复用约定：

- 参数缺失或非法：`400`。
- 行情或 K 线不可用：`503` 或明确的业务错误。
- 内部异常：记录日志，前端只返回通用错误，不暴露堆栈。
- `/health` 必须保持轻量，不能加载 embedding、构建 RAG、请求 LLM，也不应触发纸上交易任务。

M3 增加纸上交易 API 时，应沿用 `/api/...` 路径和 `{"error": ...}` 错误格式。

## 可复用模块

| 模块 | 当前能力 | 纸上交易复用方式 |
|---|---|---|
| `core/market_data.py` | `get_realtime_quote`、`get_daily_kline` | 获取模拟成交价格和持仓市值；失败时跳过并记录原因 |
| `core/skills/technical.py` | 输出 `SkillReport.score`，0-100 技术评分 | M2 策略信号可优先使用该结构化分数 |
| `core/skills/comprehensive.py` | 汇总技术/基本面/风险/新闻并在文本中给综合评分 | 可作为报告文本来源；如需结构化分数，后续需单独抽取/改造 |
| `core/model_service.py` | 模型预测 label/confidence，当前主要面向 `600519` | 可作为辅助信号，不能直接泛化到所有股票 |
| `core/blind_test.py` | SQLite 连接、建表、轻量迁移、tmp_path 测试模式 | M2 新服务按此方式建立独立数据库 |
| `templates/index.html` | 单页模块化区域、fetch 请求、ECharts | M4 添加“模拟交易”模块，不重写前端框架 |
| `tests/test_core.py` / `tests/test_blind_test.py` | pytest、monkeypatch、tmp_path、Flask test_client | M2-M6 新增测试必须 mock 外部行情，隔离数据库 |
| `Dockerfile` | `python:3.11-slim` + `python app.py` | M5 增加依赖和运行说明，保持 Linux/Docker 可运行 |

## SQLite 使用方式审计

现有 SQLite 只在 `core/blind_test.py` 中使用，模式如下：

1. 数据库路径位于 `data/blind_test/blind_test.sqlite3`。
2. `_connect()` 内创建父目录。
3. 使用 `sqlite3.connect(...)`。
4. 设置 `conn.row_factory = sqlite3.Row`。
5. 执行 `PRAGMA foreign_keys = ON`。
6. 使用 `CREATE TABLE IF NOT EXISTS` 建表。
7. 通过 `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` 做增量迁移。
8. 测试使用 `tmp_path` 提供临时 sqlite 文件。

M2 应新增独立模拟交易数据库，不修改盲测数据库。建议默认路径：`data/paper_trading/paper_trading.sqlite3`，运行产物后续应加入忽略规则。

## M2 必需表设计方向

按需求至少建立以下表，M1 只定义方向，不创建表：

| 表 | 职责 |
|---|---|
| `paper_accounts` | 单账户现金、初始资金、已实现盈亏、策略版本、创建/更新时间 |
| `paper_positions` | 股票持仓数量、平均成本、最新价格、市值、浮动盈亏 |
| `paper_orders` | 每次 BUY/SELL/HOLD 或 skipped 记录，包含原因、信号、价格、数量、手续费、滑点、状态 |
| `paper_daily_equity` | 每日现金、持仓市值、总资产、收益率、最大回撤计算基础 |
| `paper_task_runs` | 每次自动运行记录，含交易日、股票代码、策略版本、状态和跳过原因 |

关键约束：同一交易日、股票代码、策略版本不能重复执行；数据获取失败时记录 `skipped` 和具体原因，不能虚构价格。

## 策略与配置设计

M2 应将策略阈值和仓位比例放在配置文件中，业务代码只读取配置，不硬编码阈值。建议新增类似：

```text
config/paper_trading.json
```

初始配置方向：

- 初始资金：`100000`
- 固定股票列表：可配置
- 手续费率：可配置
- 滑点率：可配置
- 最大仓位：可配置
- 信号阈值：可配置
- 信号对应仓位比例：可配置

需求中的信号规则应作为默认配置：

| 分数区间 | 信号 | 操作比例 |
|---|---|---|
| `score >= 75` | 强买入 | 使用可用资金的 30% |
| `60 <= score < 75` | 买入 | 使用可用资金的 15% |
| `45 < score < 60` | 持有 | 不操作 |
| `30 < score <= 45` | 卖出 | 卖出当前持仓的 50% |
| `score <= 30` | 强卖出 | 卖出全部持仓 |

## 新增模块规划

| 阶段 | 建议新增/修改 | 范围 |
|---|---|---|
| M1 | `docs/PAPER_TRADING_M1_DESIGN.md` | 审计与设计文档 |
| M2 | `core/paper_config.py`、`core/paper_trading.py`、`config/paper_trading.json`、`tests/test_paper_trading.py` | 配置、SQLite、交易引擎 |
| M3 | `app.py`、`core/paper_report.py`、`requirements.txt`、`tests/test_paper_api.py`、`tests/test_paper_report.py` | API 与 Excel 报表 |
| M4 | `templates/index.html`、必要测试 | 前端展示和交互 |
| M5 | `scripts/run_daily_paper_trade.py`、`Dockerfile`、部署文档 | 定时脚本与 Docker/Linux 运行 |
| M6 | `README.md`、补充测试和文档 | 完整测试、说明和演示流程 |

如果单阶段预计超过 15 个文件，应先暂停并说明拆分原因。

## API 设计方向

M3 应新增以下接口，路径按需求保持：

```text
GET  /api/paper/account
GET  /api/paper/positions
GET  /api/paper/orders
GET  /api/paper/equity
POST /api/paper/run
GET  /api/paper/report.xlsx
```

`POST /api/paper/run` 应支持：

- 指定股票
- 指定日期
- `dry_run` 模式
- 防止重复执行

API 必须保证：

1. 不触发真实下单。
2. 取不到行情时返回或记录 skipped。
3. 重复运行时不重复交易。
4. 只返回模拟交易数据。

## Excel 报表设计方向

M3 使用 `pandas` + `openpyxl` 导出多工作表 Excel。当前 `requirements.txt` 还没有 `openpyxl`，需在 M3 或 M5 补充依赖并验证 Docker 可用。

报表至少包含：

1. 账户概览
2. 当前持仓
3. 交易明细
4. 每日净值
5. 运行日志

元数据应包含：

- 生成时间
- 策略版本
- 模拟开始时间
- 数据区间
- “仅为模拟交易与技术演示，不构成投资建议。”

Flask 下载建议使用 `send_file`，文件流使用 `BytesIO` 或安全临时文件，不能让用户控制任意文件路径。

## 前端设计方向

M4 在 `templates/index.html` 新增“模拟交易”模块，展示：

1. 初始资金
2. 当前现金
3. 持仓市值
4. 总资产
5. 总收益率
6. 最大回撤
7. 当前持仓
8. 最近交易记录
9. 净值曲线
10. 最后运行时间
11. 一键运行按钮
12. 导出 Excel 按钮

页面必须明确标注：

```text
仅为模拟交易与技术演示，不构成投资建议。
```

前端沿用现有原生 JS + fetch 风格，不引入新前端框架，不重写聊天界面。

## 自动运行设计方向

M5 新增：

```text
scripts/run_daily_paper_trade.py
```

要求：

1. 可被 Linux cron 或容器定时任务调用。
2. 支持命令行参数。
3. 输出结构化日志。
4. 重复执行不会重复交易。
5. 单只股票失败不能中断其他股票。
6. 返回正确进程退出码。

设计原则：脚本直接调用服务层，不通过浏览器；测试中 mock 行情，不依赖真实网络。

## 分阶段实施步骤

### M1 项目审查和设计

- 阅读 README、目录结构、Flask 路由、行情接口、预测模块、SQLite 模式和 Dockerfile。
- 输出本设计文档。
- 运行现有测试。
- 执行 `git diff --stat` 和 `git status`。
- 提交：`M1: audit current architecture`。
- 打标签：`paper-trading-m1`。
- 推送分支和标签。

### M2 数据库与交易引擎

- 新增配置加载和默认策略配置。
- 新增 `PaperTradingService`。
- 建立 5 张必需表。
- 实现账户初始化、买入、卖出、持仓、市值、盈亏、每日净值、重复运行拦截。
- 新增服务层测试：资金不足、持仓不足、买入现金/持仓、卖出盈亏、手续费滑点、重复任务、无行情跳过。
- 运行测试后提交：`M2: add paper trading database and engine`。
- 打标签：`paper-trading-m2`。

### M3 API 与报表

- 在 `app.py` 增加 `/api/paper/...` 路由。
- 新增 Excel 报表服务。
- 增加 `openpyxl` 依赖。
- 测试 API 和 Excel 生成/读取。
- 运行测试后提交：`M3: add paper trading APIs and reports`。
- 打标签：`paper-trading-m3`。

### M4 前端展示

- 在 `templates/index.html` 增加模拟交易模块。
- 展示账户、持仓、订单、净值曲线、最后运行时间。
- 增加一键运行和 Excel 导出按钮。
- 明确展示免责声明。
- 运行测试和页面加载验证后提交：`M4: add paper trading frontend`。
- 打标签：`paper-trading-m4`。

### M5 定时任务与 Docker

- 新增 `scripts/run_daily_paper_trade.py`。
- 增加 CLI 参数和结构化日志。
- 更新 Docker/cron 文档或 Dockerfile。
- 验证容器可构建、脚本可运行、重复执行不重复交易。
- 运行测试后提交：`M5: add scheduled execution and deployment`。
- 打标签：`paper-trading-m5`。

### M6 测试和文档

- 补齐全部测试和 README 说明。
- 输出 API 示例、本地/Docker/cron 命令、限制和演示步骤。
- 运行完整 `pytest -q`。
- 提交：`M6: add tests and documentation`。
- 打标签：`paper-trading-m6`。

## 测试策略

后续测试必须覆盖：

1. 资金不足不能买入。
2. 持仓不足不能卖出。
3. 买入后现金和持仓计算正确。
4. 卖出后盈亏计算正确。
5. 手续费和滑点计算正确。
6. 同一天重复任务被拦截。
7. 无行情数据时正确跳过。
8. Excel 报表可以正常生成和读取。
9. 现有核心测试仍然通过。

测试约束：

- 使用 `tmp_path` 隔离 SQLite。
- 使用 `monkeypatch` mock 行情和预测。
- 不依赖真实外部网络。
- 不删除、跳过或弱化既有测试。

## Docker 和阿里云部署设计方向

当前 Dockerfile 只启动 Web 服务：

```text
python app.py
```

M5 需要补充：

- `openpyxl` 依赖可安装。
- 数据库目录可挂载，例如 `/app/data/paper_trading`。
- 报表输出目录可挂载或按需内存生成。
- Linux cron 可调用：`python /app/scripts/run_daily_paper_trade.py ...`。
- 容器内任务不应依赖交互式 shell 环境变量，路径使用绝对路径。

## 风险与已知限制

1. 当前无真实认证系统，只能基于 session/config 做模拟账户隔离。
2. 腾讯行情可能失败，失败时必须 skipped，不能成交。
3. 模型预测主要面向 `600519`，不能假定适用于所有股票。
4. `ComprehensiveSkill` 当前综合分主要在文本中，结构化复用需后续设计。
5. 当前缺少 `openpyxl`，Excel 功能要在后续阶段补依赖。
6. Docker 当前是轻量 Flask 容器，定时任务需要 M5 明确运行方式。
7. 本功能不构成投资建议，任何收益和回撤只代表模拟计算。

## M1 完成标准

M1 视为完成需满足：

- 已在 `feature/paper-trading` 分支工作。
- 已新增本设计文档。
- 未实现 M2-M6 功能。
- 已运行现有测试。
- 已执行 `git diff --stat` 和 `git status`。
- 已提交 `M1: audit current architecture`。
- 已创建标签 `paper-trading-m1`。
- 已推送分支和标签到 origin。
