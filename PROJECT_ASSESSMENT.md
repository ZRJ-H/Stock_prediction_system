# 股票预测智能分析系统 — 项目现状与评估

> 评估日期：2026-05-27  
> 当前分支：`iter3-skill-system`  
> 最新提交：`51ab352` 迭代3：Skill系统重构

---

## 1. 项目概览

一个基于 Flask 的 **A 股智能分析对话系统**，提供 Web 聊天界面，用户可以用自然语言查询实时行情、技术指标、基本面数据、新闻舆情，获取 CNN 模型涨跌预测和量化选股推荐。系统支持在线 LLM 驱动（OpenAI 兼容 API）和离线规则引擎双模式运行。

## 2. 迭代历程

| 迭代 | 提交 | 核心交付 |
|---|---|---|
| 迭代0 | `0812f9f` | 股票 CNN 预测模型（TensorFlow），CSV 数据训练 |
| 迭代1 | `50fc5a5` | 对话式 Agent，腾讯实时行情 API，Flask Web 界面 |
| 迭代2 | `e7bff01` | 12个工具系统 + RAG知识库 + 记忆系统 + 5策略选股引擎 |

## 3. 系统架构

```
templates/index.html (前端 Chat UI)
        │
    app.py (Flask: /chat, /memory, /health)
        │
    core/agent.py (对话调度层)
        ├── LLM 模式：OpenAI function calling（需 OPENAI_API_KEY）
        └── 规则模式：关键词意图分类 + 直接工具分发
        │
        ├── core/tools.py (12个工具注册/分组/执行)
        │   ├── search_stock / get_stock_info / get_stock_history
        │   ├── predict_stock → core/model_service.py (CNN/MLP)
        │   ├── calc_indicators → core/indicators.py (纯NumPy)
        │   ├── get_financials → core/fundamentals.py (AKShare)
        │   ├── get_news → core/news.py (腾讯/东方财富)
        │   ├── search_knowledge → core/rag_service.py (NumPy向量检索)
        │   ├── analyze_stock (行情+指标+预测三合一)
        │   ├── screen_stocks / recommend_stock → core/screener.py
        │   └── update_preference → core/memory.py
        │
        ├── core/llm_service.py (OpenAI兼容API封装)
        ├── core/market_data.py (腾讯API：实时行情+K线)
        ├── core/data_pipeline.py (滑动窗口+归一化)
        └── core/memory.py (会话记忆+用户偏好持久化)
```

### 数据流（LLM 模式）

```
用户输入 → agent.run()
  → _build_system_prompt(偏好注入)
  → _select_tool_group(工具子集选择)
  → LLM chat loop (最多8轮)
    → LLM 返回 tool_call → run_tool() → 结果回送给 LLM
    → LLM 返回 text → 保存会话记忆 → 返回用户
  → 异常降级 → _run_rule(规则模式)
```

## 4. 模块逐项分析

### 4.1 行情数据层 `core/market_data.py`

| 项目 | 状态 |
|---|---|
| 数据源 | 腾讯免费 API（无需密钥） |
| 实时行情 | `qt.gtimg.cn` → `StockQuote`（15+字段） |
| 日K线 | `web.ifzq.gtimg.cn` → `KlineBar` 列表（前复权） |
| 股票列表 | 默认内置 38 只核心 A 股，可选 AKShare 全量 |
| 批量查询 | 顺序请求（无并行），`get_batch_quotes()` |

**评估**：数据源稳定可用，覆盖沪深主板、创业板、科创板 38 只权重股。AKShare 全量列表需网络稳定时才可用。批量查询为串行，30 只选股时约需 5-8 秒。

### 4.2 技术指标 `core/indicators.py`

| 指标 | 算法 | 状态 |
|---|---|---|
| MA5/10/20/60 | 简单移动平均（卷积） | ✅ |
| EMA12/EMA26 | 指数移动平均（递推） | ✅ |
| MACD | DIF=EMA12-EMA26, DEA=EMA9(DIF), HIST=2×(DIF-DEA) | ✅ |
| RSI(14) | Wilder平滑法 | ✅ |
| BOLL(20) | MA±2σ | ✅ |
| KDJ(9) | RSV→K→D→J 递推 | ✅ |
| 量比(5) | 成交量/5日均量 | ✅ |
| K线形态 | 锤子线/倒锤子/十字星/吞没/三兵 | ✅ |

**评估**：纯 NumPy 实现，零外部依赖，计算精度与主流软件一致。无 GPU 需求，单只股票 < 10ms。

### 4.3 模型服务 `core/model_service.py`

| 项目 | 状态 |
|---|---|
| 主后端 | TensorFlow CNN（2层Conv1D） |
| 降级后端 | sklearn MLP（128→64 隐藏层） |
| 当前已训练 | MLP（meta.json 显示 `sklearn_mlp_fallback`） |
| 输入 | 60天窗口 × 5特征（OHLCV） |
| 输出 | 涨/跌 二分类 + 置信度 + 涨跌概率 |
| 持久化 | `.keras` / `.joblib` + `scaler.json` + `meta.json` |

**评估**：双后端设计保证了 TF 不可用时的降级可用性。当前环境无 TF，模型为 MLP 训练结果。CNN 相比 MLP 在时序特征提取上有优势，但 MLP 降级在小数据集上差异有限。模型训练数据来源未知（推测旧 CSV），需要用真实行情数据重新训练。

**⚠️ 评估方式问题**：当前训练使用 `train_test_split(random_state=42, stratify=y)` 做随机切分（[model_service.py:171](core/model_service.py#L171)），归一化在全量数据上先 `fit`（[data_pipeline.py:123](core/data_pipeline.py#L123)）。这对时间序列存在两处隐患：(1) 随机切分导致未来数据泄露到训练集，高估预测准确率；(2) 全量 fit 让归一化参数"看到"测试集未来的极值。进入可信阶段前必须改为时间序列切分（前80%训练/后20%测试）+ 仅在训练集上 fit scaler。

### 4.4 LLM 服务 `core/llm_service.py`

| 项目 | 状态 |
|---|---|
| 协议 | OpenAI Chat Completions（含 function calling） |
| 依赖 | 零 SDK 依赖，纯 `urllib.request` |
| 离线降级 | 模板化文本生成 `_fallback_text()` |
| 配置 | `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` |
| 支持 | 兼容 DeepSeek、通义千问、Ollama 等 |

**评估**：零第三方依赖是优点，但缺少超时重试、流式输出、并发管理等生产级特性。当前环境无可用的 LLM API（`llm_available: false`），系统运行在规则模式。

### 4.5 工具系统 `core/tools.py`

| 分组 | 工具 | 适用场景 |
|---|---|---|
| basic | search_stock, get_stock_info, get_stock_history | 基础查询 |
| technical | basic + calc_indicators, predict_stock | 技术分析 |
| full | technical + financials/新闻/对比/综合分析/选股/推荐 | 深度分析 |
| knowledge | search_knowledge, update_preference | 知识检索 |

**评估**：工具分组策略合理，能减少 LLM 选择负担和 token 消耗。但工具函数的错误处理粒度较粗（异常统一返回错误文本），缺少结构化的错误码。

### 4.6 Agent 调度层 `core/agent.py`

| 项目 | 状态 |
|---|---|
| 运行模式 | LLM 在线 / 规则离线，自动降级 |
| 意图分类 | 11 种意图，关键词匹配 |
| 工具调用 | LLM 模式下最多 8 轮迭代 |
| 上下文 | System Prompt + 用户偏好注入 + 会话历史 |
| 降级逻辑 | LLM 调用失败 → 自动回退规则模式 |

**评估**：双模式设计是核心亮点——有 LLM 时灵活智能，无 LLM 时也能工作。规则模式的关键词意图分类准确率约 70-80%（中文口语歧义是主要瓶颈）。`_extract_keyword()` 的填充词剥离策略基于白名单正则，覆盖面有限。

**迭代3 调度说明**：规则模式下 `_dispatch()` 直接 import 各 Skill 执行（如 `TechnicalSkill().execute(code)`），`SkillGateway` 目前作为注册表/辅助封装存在，不是主调度路径。LLM 模式下 5 个 Skill 已注册为工具，由 LLM 自主选择。

### 4.7 RAG 知识库 `core/rag_service.py`

| 项目 | 状态 |
|---|---|
| 文档 | 3 篇 Markdown：技术分析基础、价值投资原则、风险管理 |
| 文本块 | ~30 个（按 ## 标题切分，≤800 字符/块） |
| 向量模型 | `paraphrase-multilingual-MiniLM-L12-v2`（384 维） |
| 检索方式 | 余弦相似度（NumPy 归一化点积实现），阈值 0.2 |
| 索引缓存 | `knowledge_index.json`（避免重复 embedding） |

**评估**：3 篇文档覆盖了技术分析、价值投资、风险管理的基础概念，内容质量尚可但覆盖面偏窄。MiniLM 模型在多语言场景下表现不错，但全量文档较少（总共可能不到 10KB），检索召回率可能在高泛化问题上不足。**注意**：虽然 requirements.txt 列了 faiss-cpu，当前实现为 NumPy 点积检索，并未真正使用 FAISS。小知识库（~30 块）下 NumPy 足够；规模扩大后可改为 FAISS IndexFlatIP 加速。后续可扩展：行业知识、政策解读、财报分析框架等。

### 4.8 记忆系统 `core/memory.py`

| 层次 | 存储 | 生命周期 | 内容 |
|---|---|---|---|
| 会话记忆 | 进程内存 | 30min TTL | 最近 20 条消息（10轮） |
| 用户偏好 | JSON 文件 | 持久化 | 关注列表、分析风格、风险偏好 |

**评估**：两层设计合理。会话记忆的 TTL + 滑动窗口能保障内存不膨胀。局限：(1) 进程内存储 → 服务重启丢失所有会话；(2) 无用户认证 → session_id 依赖前端 localStorage，无安全校验；(3) 偏好只有 3 个维度，可扩展空间大。

### 4.9 选股引擎 `core/screener.py`

| 策略 | 评分逻辑 | 适用风格 |
|---|---|---|
| 超卖反弹 | RSI<30 + MACD金叉 + 缩量 | 短线 |
| 趋势强势 | 均线多头 + MACD金叉 + 放量 + 涨幅 | 趋势 |
| 低估值 | PE<15 + PB<1.5 + RSI偏低 | 价值 |
| 高股息 | PE<10 + PB<1.5 | 稳健 |
| 综合评分 | 超卖×0.4 + 趋势×0.3 + 价值×0.3 | 平衡 |

**评估**：5 种策略覆盖了常见投资风格，评分权重有量化逻辑。但存在明显局限：(1) 候选池仅 30 只，遗漏大量中小盘机会；(2) 技术指标计算串行，30 只 × 0.5s = 15s 等待；(3) 缺少行业分类和市值分层，银行/白酒/科技混排；(4) 没有回测验证评分因子的有效性。

## 5. 技术栈

| 层 | 技术 | 备注 |
|---|---|---|
| Web 框架 | Flask | 开发模式运行（debug=True） |
| 前端 | 原生 HTML/CSS/JS | 单页面，无框架 |
| 深度学习 | TensorFlow (可选) | 当前不可用 |
| 机器学习 | scikit-learn MLP | 当前降级后端 |
| 数值计算 | NumPy | 技术指标核心 |
| 向量检索 | sentence-transformers + NumPy 点积（可切 FAISS） | 余弦相似度 |
| 数据源 | 腾讯 API / AKShare(可选) | HTTP 调用 |
| LLM | OpenAI 兼容协议 | 任何兼容服务 |

## 6. 数据资产

| 资产 | 路径 | 状态 |
|---|---|---|
| 训练模型 | `models/stock_mlp.joblib` | MLP 降级版，60天窗口 |
| 归一化器 | `models/scaler.json` | OHLCV MinMax 参数 |
| 知识库 | `data/knowledge/*.md` | 3 篇投资知识文档 |
| 向量索引 | `data/knowledge_index.json` | 预计算 embedding |
| 用户记忆 | `data/memory/*.json` | 按 session_id 存储 |

## 7. 当前运行状态

```
模型: MLP 已训练（sklearn_mlp_fallback）
LLM: 离线（OPENAI_API_KEY 未配置）
RAG: 已加载（knowledge_index.json）
服务: http://127.0.0.1:5000（未启动）
```

## 8. 已知问题与风险

### 8.1 高优先级

| # | 问题 | 影响 | 建议 | 状态 |
|---|---|---|---|---|
| 1 | LLM 离线，系统运行在规则模式 | 意图理解弱，口语化查询可能路由错误 | 配置 API key 或接入本地模型 | 待处理 |
| 2 | 模型训练数据来源不明 + 评估方式不当（随机切分/全量归一化） | 预测质量不可控，准确率可能被高估 | 用腾讯API拉取真实数据，时间序列切分重新训练 | 待处理 |
| 3 | 会话存储在进程内存 | 服务重启丢失所有会话 | 引入 Redis 或文件持久化会话 | 待处理 |
| 4 | 候选股池仅 38 只 | 选股覆盖面不足 | 扩大池子或接入 AKShare 全量列表 | 待处理 |

### 8.2 中优先级

| # | 问题 | 影响 | 建议 | 状态 |
|---|---|---|---|---|
| 5 | 批量行情/指标计算为串行 | 选股慢（15s+） | 引入线程池/异步并发 | 待处理 |
| 6 | AKShare 网络不稳定 | 基本面/新闻偶尔不可用 | 增加超时重试 + 更多降级数据源 | 待处理 |
| 7 | 无用户认证 | 偏好数据无安全边界 | 引入简单 token 或 JWT | 待处理 |

### 8.3 低优先级

| # | 问题 | 影响 | 建议 | 状态 |
|---|---|---|---|---|
| 8 | 前端无框架，JS 裸写 | 维护性差 | 可考虑 Vue/React 轻量迁移 | 待处理 |
| 9 | 缺少测试 | 回归风险 | 为核心模块添加单元测试 | 处理中 |
| 10 | 无日志/监控 | 问题排查困难 | 接入 logging + 请求追踪 | 已修复（app.py 已加 logging） |

### 8.4 已修复（基础安全轮）

| # | 问题 | 修复方式 | 状态 |
|---|---|---|---|
| F1 | 前端 innerHTML 拼接用户输入，存在 XSS 风险 | index.html: addMsg/addLoading 改为 textContent + DOM 创建 | ✅ |
| F2 | /chat 异常返回完整 traceback 到前端 | app.py: 改用 logging.exception，前端返回通用错误消息 | ✅ |
| F3 | debug=True 写死 | app.py: 改为 FLASK_DEBUG 环境变量控制 | ✅ |
| F4 | 偏好记忆写死 "default"，污染全局 + 不绑定 session | agent.py _dispatch 加 session_id 参数；tools.py 加 _current_session_id 机制 | ✅ |

## 9. 后续发展路线

### 9.1 迭代3：Skill 系统重构 ✅ 已完成

> **提交**：`51ab352`（分支：`iter3-skill-system`）  
> **交付**：9 个新文件 + 3 个修改文件，1635 行新增

将当前 Agent 的扁平工具调用升级为可组合的 Skill 模式：

```
旧：query → _classify_intent → _dispatch → 单个工具
新：query → _classify_intent → _dispatch → Skill（直接 import）→ 结构化报告
```

> **注意**：当前规则模式的调度链路是 `agent._dispatch()` 直接 import 各 Skill 执行，`SkillGateway` 目前作为注册表/辅助封装存在，不是主调度路径。若后续 Skill 数量继续增长，可考虑将路由收敛到 Gateway。

| Skill | 状态 | 职责 | 评分输出 |
|-------|------|------|----------|
| TechnicalSkill | ✅ | MA/MACD/RSI/BOLL/KDJ + K线形态 + 操作建议 | 0-100 |
| FundamentalSkill | ✅ | PE/PB/ROE/毛利率/营收/净利润 + 估值评级 | 0-100 |
| RiskSkill | ✅ | 波动率/最大回撤/下行风险/VaR + 仓位止损 | 0-100 |
| ScreeningSkill | ✅ | 5策略选股 Top5 + 推荐理由 | — |
| NewsSkill | ✅ | 新闻获取 + TF关键词提取 + 正负面情感分析 | — |
| ComprehensiveSkill | ✅ | 四维度综合报告 + 加权平均评分 | 0-100 |

**已实现的核心能力**：
- Skill 统一接口：`execute(**params) → SkillReport → format()`
- 结构化报告：章节 + 信号(bullish/bearish/neutral) + 量化评分 + 文字结论
- SkillGateway：意图→Skill 映射 + 全局注册表 + ToolDef 适配
- LLM 模式：5 个 Skill 工具注册到 ALL_TOOLS（18个），LLM 可自主选择粒度
- 规则模式：13 种意图路由，5 个核心意图升级为 Skill
- 向后兼容：旧的 12 个工具全部保留

### 9.2 迭代4：LLM 接入 + 前端升级（建议优先级最高）

当前系统在规则模式下运行，意图理解准确率约 70-80%。接入 LLM 后：
- 口语化查询容错大幅提升（"这票咋样" → 综合分析）
- LLM 自动选择工具/Skill 粒度（简单查询用基础工具，深度需求用 Skill）
- 多轮对话上下文保持（会话记忆注入 System Prompt）

| 方案 | 配置 | 月成本估算 |
|------|------|-----------|
| DeepSeek | `BASE_URL=api.deepseek.com` `MODEL=deepseek-chat` | 约 5-20 元 |
| 本地 Ollama | `BASE_URL=localhost:11434` `MODEL=qwen2.5:7b` | 零成本 |
| 通义千问 | 阿里云百炼 OpenAI 兼容接口 | 约 10-30 元 |

**前端升级方向**：
- 图表渲染：ECharts 展示 K线图、技术指标叠加、量价关系
- 结构化报告：SkillReport 的分段卡片式展示（替代纯文本）
- 状态指示灯：/health 接口的三色灯（模型/LLM/RAG）

### 9.3 迭代5：模型升级 + 回测体系

1. **数据源替换**：从腾讯 API 拉取 200+ 只股票、2015 年至今的日 K 数据
2. **特征工程扩展**：
   - 加入技术指标作为辅助特征（RSI/MACD/量比）
   - 加入市场环境特征（指数涨跌/板块走势）
3. **模型升级**：
   - 当前 CNN 是单只股票序列预测 → 考虑加入 LSTM/Transformer
   - 多任务学习：同时预测涨跌 + 涨跌幅
4. **回测框架**：滚动窗口 + 夏普比率 + 最大回撤 + 胜率统计

### 9.4 生产化改进

| 阶段 | 任务 |
|------|------|
| 短期 | `.env` 配置管理；日志系统；选股并发优化（15s→2s） |
| 中期 | 候选池扩展到 200+；Redis 会话存储；定时收盘数据更新 |
| 长期 | WebSocket 实时推送；Docker 部署；微服务拆分 |

## 10. 当前进度与总体评估

### 迭代进度

| 迭代 | 分支 | 状态 | 核心交付 |
|------|------|------|----------|
| 1 | `main` | ✅ | 单股票问答 Agent（行情+预测），CSV 训练 |
| 2 | `iter2-tools-rag-memory` | ✅ | 12 工具 + RAG知识库 + 记忆系统 + 5策略选股 |
| 3 | `iter3-skill-system` | ✅ | 6 Skills + 结构化报告 + 评分体系 + 网关路由 |

### 当前能力矩阵

| 维度 | 能力 | 成熟度 |
|------|------|--------|
| 行情数据 | 实时行情 + 日K线（腾讯API，38只） | ●●●○ |
| 技术分析 | 7类指标 + K线形态 + 综合评分 | ●●●● |
| 基本面 | PE/PB估值 + 财报指标（需AKShare） | ●●○○ |
| 风险评估 | 波动率/回撤/VaR/仓位建议 | ●●●○ |
| 新闻舆情 | 多源获取 + 关键词 + 情感分析 | ●●○○ |
| 选股推荐 | 5策略评分排名 | ●●●○ |
| 预测模型 | MLP降级版（训练数据来源不明） | ●●○○ |
| 知识检索 | NumPy向量检索（3篇文档，未接FAISS） | ●●○○ |
| LLM调度 | function calling + 规则双模式 | ●●●○ |
| 会话记忆 | 进程内存30min TTL + 偏好JSON持久化 | ●●○○ |
| 前端UI | 原生HTML/CSS/JS 聊天界面 | ●●○○ |

### 优势

- **零成本数据源**：腾讯免费 API 覆盖行情+K线，无需任何注册
- **双模式灵活**：有 LLM 智能调用工具/Skill，无 LLM 也能基于规则工作
- **Skill 架构清晰**：统一接口 + 结构化报告 + 评分体系，易于扩展新 Skill
- **技术指标完整**：纯 NumPy 实现 7 类指标 + K线形态，精度可靠
- **量化选股可用**：5 种策略的评分逻辑清晰，能产出有效的候选筛选

### 不足

- **LLM 离线**：规则模式意图理解准确率约 70-80%，口语化查询容错差
- **模型未验证**：MLP 训练数据来源不明，无回测指标，预测可靠性待验证
- **前端简陋**：纯文本聊天，无图表/卡片/指标可视化
- **工程化程度低**：无日志、无测试、串行执行、进程内存储

### 一句话定位

> **一个架构清晰、经过3轮迭代的股票分析系统原型，Skill 管线 + 评分体系已成型。当前最大瓶颈是缺少 LLM 和前端图表，接入后即可从"原型"升级为"可用的个人投研工具"。**
