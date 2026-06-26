# 项目评审历程 (Review History)

---

## Review #1 — 2026-05-27（ChatGPT 深度代码审查）

> **评审来源**：将完整项目代码（除 `__pycache__`/缓存文件外）提交 ChatGPT 做系统性 review。  
> **评审范围**：迭代3 Skill系统重构完成后的全项目（app.py、core/ 下 14 个模块、templates/index.html）  
> **评审后提交**：`01f15a1` — 基础安全修复轮（6 项修复 + 20 个回归测试）

---

### 一、ChatGPT 审查原始结论（引用）

> 我按 review 方式看了一轮，避开了 `__pycache__`/缓存文件；没有改代码。整体判断：PROJECT_ASSESSMENT.md 对项目定位基本准确，但对"迭代3 SkillGateway 已成为主链路""RAG 使用 FAISS""模型可信度"这几处有偏乐观或文档超前的问题。

> **当前状态评估**：这是一个结构已经拉开的原型：行情、指标、新闻、RAG、记忆、Skill 报告、规则/LLM 双模式都有了。作为课程项目、个人 demo、投研助手雏形，完成度不错；作为"可依赖的股票预测系统"，还缺三块：可信数据与回测、前端可视化、工程安全与稳定性。

> **建议路线**：短期先做"可稳妥演示版"——修 XSS、隐藏 traceback、补 logging、把 update_preference 全链路改为使用当前 session_id；中期做"好用版"——接 DeepSeek/Ollama，前端 ECharts 展示 K 线/均线/MACD/RSI，SkillReport 返回结构化 JSON；长期做"可信投研版"——重建训练数据集、时间序列切分和滚动回测、候选池扩到 200+ 或全 A、选股并发化。

---

### 二、逐项详细记录

---

#### 问题 1：前端 XSS 风险 — `innerHTML` 直接拼接用户输入

- **级别**：高
- **文件**：[templates/index.html](templates/index.html)
- **具体位置**：`addMsg()` 函数（第 166-174 行）、`addLoading()` 函数（第 177-185 行）
- **ChatGPT 审查原文**：

> *templates/index.html (line 169) 用 innerHTML 直接拼接用户输入和后端回复。用户输入 `<img onerror=...>` 这类内容会被当 HTML 执行。建议改成 textContent 或创建 DOM 节点后赋文本。*

- **根因分析**：

  `addMsg` 函数将 `role` 和 `text` 参数通过模板字符串插入 HTML，再通过 `innerHTML` 写入 DOM。`text` 来自用户输入（直接打字）和后端 `/chat` 回复（经 Agent → 工具链返回）。虽然当前后端返回的是纯文本（工具输出的格式化字符串），但存在两个攻击面：
  1. 用户在自己输入框中输入 `<img src=x onerror=alert(1)>`，会立即在自己浏览器执行（自 XSS，虽无实际危害但说明不安全）
  2. 如果后端某条数据链路（如新闻标题、行情数据字段）中包含未经转义的 HTML，会被浏览器解析执行

  `addLoading` 函数虽然没有用户数据注入，但同样使用 `innerHTML` 拼接静态 HTML，是不良实践，容易被复制粘贴扩散。

- **修复方式**：

  `addMsg`：用 `document.createElement` 创建 avatar 和 bubble 元素，用 `textContent` 赋值文本内容，用 `appendChild` 组装 DOM 树。用户输入/后端回复不论内容如何，始终被当纯文本渲染。

  `addLoading`：同样改为 `createElement` + `textContent` + `appendChild` 模式，消除所有 `innerHTML` 使用。

- **修复前代码**：
  ```javascript
  function addMsg(role, text) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    div.innerHTML = `<div class="avatar">${role === 'user' ? '我' : 'AI'}</div>
                     <div class="bubble">${text}</div>`;
    chat.appendChild(div);
  }
  ```

- **修复后代码**：
  ```javascript
  function addMsg(role, text) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = role === 'user' ? '我' : 'AI';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;
    div.appendChild(role === 'user' ? bubble : avatar);
    div.appendChild(role === 'user' ? avatar : bubble);
    chat.appendChild(div);
  }
  ```

---

#### 问题 2：后端 traceback 泄露到前端 + `debug=True` 写死

- **级别**：高
- **文件**：[app.py](app.py)
- **具体位置**：`/chat` 路由异常处理（第 64-66 行）、`__main__` 启动（第 150 行）
- **ChatGPT 审查原文**：

> *app.py (line 66) 在 /chat 异常时返回 traceback.format_exc()，同时 app.py (line 150) 默认 debug=True。这对本地开发方便，但一旦演示或部署会泄露路径、栈、模块结构。建议改为服务端 logging，前端只返回通用错误。*

- **根因分析**：

  `traceback.format_exc()` 返回的是 Python 完整调用栈，包含：
  - 服务器文件系统绝对路径（如 `D:\MyProject\socket_predict\...`）
  - 模块导入链（暴露项目结构和依赖）
  - 第三方库内部状态（如 `requests`、`flask` 版本信息）
  - 可能包含 API 调用参数（如股票代码、查询文本）

  这些信息对调试有用，但任何能访问 `/chat` 的人都看到，就构成信息泄露。攻击者可以用这些信息推断 Python 版本、库版本、系统路径，为后续定向攻击提供情报。

  `debug=True` 写死则意味着即使部署到生产环境，Flask 调试器（含交互式调试控制台）也会开启，这是严重安全隐患。

- **修复方式**：

  1. 引入 `logging` 模块，在模块顶部配置 `logging.basicConfig`
  2. `/chat` 异常处理改为 `logger.exception("处理请求时出错，query=%s", query[:200])`，仅在前端返回通用错误消息 `"抱歉，处理您的请求时出现了内部错误，请稍后重试。"`
  3. `debug` 改为读取 `FLASK_DEBUG` 环境变量：仅在显式设置 `FLASK_DEBUG=1` 时开启

- **修复前代码**：
  ```python
  try:
      reply = agent.run(query, session_id=session_id)
  except Exception:
      reply = f"处理请求时出错:\n{traceback.format_exc()}"
  ```
  ```python
  app.run(host="127.0.0.1", port=5000, debug=True)
  ```

- **修复后代码**：
  ```python
  try:
      reply = agent.run(query, session_id=session_id)
  except Exception:
      logger.exception("处理请求时出错，query=%s", query[:200])
      reply = "抱歉，处理您的请求时出现了内部错误，请稍后重试。"
  ```
  ```python
  is_debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
  app.run(host="127.0.0.1", port=5000, debug=is_debug)
  ```

---

#### 问题 3：偏好记忆写死 `"default"`，不绑定用户会话

- **级别**：高
- **文件**：[core/agent.py](core/agent.py) + [core/tools.py](core/tools.py)
- **具体位置**：
  - `agent.py` 第 380 行：`return update_preference("default", "watchlist", code)`
  - `tools.py` 第 298 行：`return update_preference("default", key, value)`
  - `agent.py` 第 236 行：`_dispatch(query, code, keyword, intent)` — 缺少 `session_id` 参数
- **ChatGPT 审查原文**：

> *Agent 规则模式关注股票时写死到 "default"：core/agent.py (line 380)，工具层也写死 "default"：core/tools.py (line 298)。结果是聊天里"关注 600519"不会写入该用户自己的偏好文件，还会污染 data/memory/default.json。*

- **根因分析**：

  系统的会话架构如下：
  - 前端 `localStorage` 生成 UUID，每次请求携带 `session_id`
  - `app.py` 的 `/chat` 接收 `session_id` 并传给 `agent.run(query, session_id=session_id)`
  - `core/memory.py` 按 `session_id` 读写 `data/memory/{session_id}.json`（完全支持按用户隔离）

  但 `agent.py` 的 `_dispatch()` 函数没有 `session_id` 参数，`_run_rule()` 调用它时也没有传入。当规则模式匹配到 `preference` 意图（用户说"关注 600519"），`_dispatch` 内部调用 `update_preference("default", "watchlist", code)` —— 写死 `"default"`。

  `tools.py` 的 `_tool_update_preference()` 同样写死 `"default"`。当 LLM 模式时，LLM 调用 `update_preference` 工具，由 `run_tool` 路由到该函数，同样污染 `default.json`。

  **影响**：
  - 用户 A 在浏览器说"关注 000001"→ 写入 `data/memory/default.json`
  - 用户 B 在另一个浏览器说"关注 600519"→ 覆盖 `data/memory/default.json`
  - 任何用户查询偏好时都读取同一份 `default.json`
  - 用户各自的 `{uuid}.json` 永远不会被更新

- **修复方式**：

  1. `_dispatch` 函数签名加 `session_id: str = ""` 参数
  2. `_run_rule` 调用 `_dispatch` 时传入 `session_id`
  3. `_run_rule` 开头调用 `set_current_session(session_id)` 注入全局状态
  4. `_run_llm` 开头同样调用 `set_current_session(session_id)`
  5. `tools.py` 新增 `_current_session_id` 模块变量 + `set_current_session()` 函数
  6. `_tool_update_preference` 从 `_current_session_id` 读取会话 ID，兜底 `"default"`

  **修复后链路**：
  ```
  用户A浏览器 → /chat {session_id: "uuid-a"} → agent.run("关注 000001", "uuid-a")
    → set_current_session("uuid-a")
    → _dispatch(..., session_id="uuid-a")
      → update_preference("uuid-a", "watchlist", "000001")
        → 写入 data/memory/uuid-a.json ✓
  ```

---

#### 问题 4：模型评估方式不适合时间序列

- **级别**：中高
- **文件**：[core/model_service.py](core/model_service.py) + [core/data_pipeline.py](core/data_pipeline.py)
- **具体位置**：
  - `model_service.py` 第 171 行：`train_test_split(x, y, test_size=0.2, random_state=42, stratify=y)`
  - `data_pipeline.py` 第 123 行：`scaler = MinMaxFeatureScaler.fit(df, feature_columns)` — 先对全量数据 fit，再切分
- **ChatGPT 审查原文**：

> *训练用随机 train_test_split：core/model_service.py (line 171)，归一化在全量数据上先 fit：core/data_pipeline.py (line 123)。这会让未来数据影响训练流程评估，时间序列上容易高估准确率。PROJECT_ASSESSMENT.md 里"模型需重训/回测"的判断是对的，而且应该提到这是进入可信投研工具前的硬门槛。*

- **根因分析**：

  股票数据是严格的时间序列，今天的价格不能"知道"明天的价格。但当前训练流程有两处违反这个原则：

  **问题 A — 随机切分**：`train_test_split(stratify=y, random_state=42)` 将全部样本随机打乱后按 80/20 切分。结果是：2025年12月的数据可能出现在训练集，2025年1月的数据出现在测试集。模型用"未来"数据训练来预测"过去"，在测试集上会得到虚高的准确率。

  **问题 B — 全量归一化**：`MinMaxFeatureScaler.fit(df, feature_columns)` 在整个数据集上计算 min/max，然后再 `transform`。测试集的极值会影响归一化参数，属于数据泄露。

  正确的做法：
  - 按时间排序后，前 80% 的日期作为训练集，后 20% 作为测试集
  - scaler 仅在训练集上 fit，然后对测试集 transform

  这两处问题意味着当前 MLP 模型报告的准确率不具参考价值，需要重新训练后才能作为可信信号。

- **修复方式**：

  本轮仅做文档化（记录到 PROJECT_ASSESSMENT.md），未改模型训练代码。原因：当前 MLP 模型训练数据来源已不明（推测来自旧 CSV 文件），在拉取新真实数据重建训练集时，一并改为时间序列切分才是正确时机。

- **PROJECT_ASSESSMENT.md 新增说明**：

  > **⚠️ 评估方式问题**：当前训练使用 `train_test_split(random_state=42, stratify=y)` 做随机切分，归一化在全量数据上先 `fit`。这对时间序列存在两处隐患：(1) 随机切分导致未来数据泄露到训练集，高估预测准确率；(2) 全量 fit 让归一化参数"看到"测试集未来的极值。进入可信阶段前必须改为时间序列切分（前80%训练/后20%测试）+ 仅在训练集上 fit scaler。

---

#### 问题 5：SkillGateway 文档与实现不一致

- **级别**：中
- **文件**：[PROJECT_ASSESSMENT.md](PROJECT_ASSESSMENT.md) + [core/agent.py](core/agent.py) + [core/skills/gateway.py](core/skills/gateway.py)
- **ChatGPT 审查原文**：

> *评估文档写"query → SkillGateway"：PROJECT_ASSESSMENT.md (line 241)，但实际 core/agent.py (line 310) 起是直接 import 各个 Skill 执行，SkillGateway 目前更像旁路/备用封装。这不是坏事，但文档需要降一档表述，或下一步真的把规则路由收敛到 Gateway。*

- **根因分析**：

  迭代3实现了 `SkillGateway`（`core/skills/gateway.py`），包含：
  - `SKILL_REGISTRY`：6 个 Skill 实例的全局注册表
  - `INTENT_SKILL_MAP`：意图名 → Skill 名的映射
  - `route(intent, **kwargs)`：按意图路由到对应 Skill
  - `get_all_tool_defs()`：将全部 Skill 转为 ToolDef 列表

  但在 `agent.py` 的规则模式中，`_dispatch()` 函数实际走的是：
  ```python
  if intent == "indicators":
      from core.skills.technical import TechnicalSkill
      return TechnicalSkill().execute(code).format()
  ```
  每个意图直接 `import` 对应 Skill 类并调用，没有经过 `SkillGateway.route()`。

  Gateway 目前的作用仅限于：
  - `get_all_tool_defs()` 供 LLM 模式使用（将 Skill 作为工具暴露给 LLM）
  - 作为注册表索引存在

  文档之前写成 "用户查询 → SkillGateway → Skill管线" 暗示 Gateway 是主调度枢纽，与代码实际不符。

- **修复方式**：

  PROJECT_ASSESSMENT.md 中将 Skill 调度流程图从：
  ```
  新：query → SkillGateway → SkillPipeline → 多工具编排 → 结构化报告
  ```
  修正为：
  ```
  新：query → _classify_intent → _dispatch → Skill（直接 import）→ 结构化报告
  ```
  并添加注释说明 Gateway 当前为辅助封装，不是主调度路径。

---

#### 问题 6：RAG 文档/依赖写成 FAISS，实际用 NumPy 实现

- **级别**：中
- **文件**：core/rag_service.py, requirements.txt, PROJECT_ASSESSMENT.md
- **ChatGPT 审查原文**：

> *core/rag_service.py (line 2) 写"基于 FAISS"，requirements.txt 也有 faiss-cpu，但实现是 NumPy 点积检索，没有使用 FAISS。小知识库这样完全可以，但建议文档改成"向量检索，当前 NumPy 实现；规模扩大后可切 FAISS"，避免误导。*

- **根因分析**：

  `rag_service.py` 的检索实现实际上是：
  ```python
  similarity = np.dot(query_vec, doc_vecs.T)  # 点积 = 余弦相似度（已归一化）
  ```

  完全基于 NumPy 的矩阵点积，没有 `import faiss`，没有创建 FAISS Index，`requirements.txt` 中的 `faiss-cpu` 从未被使用。

  FAISS 的优势在数据量大时体现：百万级向量时用 IVF/HNSW 索引可以亚毫秒级检索。当前知识库仅 ~30 个文本块、384 维向量，NumPy 点积完全够用（<1ms）。但如果后续扩展到数百篇文档→数千块，就需要真正切换到 FAISS。

- **修复方式**：

  PROJECT_ASSESSMENT.md 4.7 节将 RAG 描述从：
  > 检索方式：余弦相似度（归一化点积）
  改为：
  > 检索方式：余弦相似度（NumPy 归一化点积实现）
  并补充说明：
  > 虽然 requirements.txt 列了 faiss-cpu，当前实现为 NumPy 点积检索，并未真正使用 FAISS。小知识库（~30 块）下 NumPy 足够；规模扩大后可改为 FAISS IndexFlatIP 加速。



---

### 三、测试补充（本轮新增）

ChatGPT 审查指出的另一个问题是"缺少测试"（原评估列为低优问题 #9）。本轮创建了 `tests/test_core.py`，包含 **20 个回归测试用例**，覆盖：

| 测试用例 | 数量 | 覆盖内容 |
|----------|------|----------|
| `test_intent_classification` | 14 | 13 种意图 + 1 个兜底，参数化验证关键词→意图映射准确性 |
| `test_extract_code` | 3 | 代码提取：有代码/无代码/中文名场景 |
| `test_extract_keyword` | 4 | 关键词提取：完整名/含代码/停用词/无股名 |
| `test_resolve_code` | 3 | 代码解析：唯一匹配/精确匹配/模糊匹配多结果 |
| `test_preferences_isolated_by_session` | 1 | 核心回归：两个不同 session_id 的偏好互不污染 |
| `test_preferences_invalid_key` | 1 | 无效 key 错误提示 |
| `test_preferences_invalid_code` | 1 | 无效代码格式校验 |

**运行结果**：`20 passed in 0.56s`



---

### 四、评审时项目快照

| 维度 | 状态 |
|------|------|
| 分支 | `iter3-skill-system` |
| 提交 | `51ab352`（评审前）/ `01f15a1`（评审修复后） |
| 迭代进度 | 1（单Agent）/ 2（工具+RAG+记忆）/ 3（Skill系统）均已完成 |
| 核心能力 | 腾讯实时行情(38只) / 7类NumPy技术指标 / AKShare财报(可选) / 腾讯/东方财富新闻 / NumPy向量检索(3篇) / 会话记忆+偏好 / 6个Skill+评分体系 / 规则/LLM双模式 |
| 工具数 | 18（12基础 + 5 Skill + 1偏好） |
| 意图数 | 13 种 |
| LLM 状态 | 离线（OPENAI_API_KEY 未配置） |
| 测试覆盖 | 0 → 20 个回归测试 |
| 安全状态 | 审查前存在 XSS、traceback泄露、session串号 3 个高危问题 |



### 五、后续建议（ChatGPT 审查 + 自行补充）

#### 短期（稳妥演示版）— 本轮已完成

- [x] 修 XSS（innerHTML → textContent + DOM）
- [x] 隐藏 traceback（logging.exception + 通用错误消息）
- [x] session 贯通（偏好全链路绑定 session_id）
- [x] 添加回归测试（20 个）

#### 中期（好用版）

1. 接入 OpenAI 兼容 LLM（DeepSeek / Ollama / 通义千问）
2. 前端 ECharts 展示 K 线图、均线叠加、MACD/RSI 副图
3. SkillReport 不只是纯文本 `format()`，增加结构化 JSON 输出
4. 候选池从 38 只扩大到全 A 或行业精选 200+

#### 长期（可信投研版）

1. 真实行情重建训练数据集（2015 至今，200+ 只股票日K线）
2. 时间序列切分 + 滚动回测 + 夏普比率 + 最大回撤
3. 选股并发化（`ThreadPoolExecutor`，30 只 15s → 2s）
4. 模型预测降级为"辅助信号"，直到有稳定回测指标

---

> **总结**：本轮审查系统性地暴露了 3 个高危安全/数据正确性问题 + 2 个文档准确性偏差 + 1 个模型评估方法缺陷。所有问题已在本轮修复（代码改 4 个文件 + 文档改 1 个文件 + 新增测试），项目从一个"功能完整但未经审查的原型"提升到"可通过基础安全审查的稳妥演示版"。

---

## 里程碑 M1 — 2026-06-02（E1：前端 ECharts 图表增强）

> **提交**：`2199eb6` — feat: add stock history chart and frontend ECharts  
> **分支**：`iter3-skill-system`  
> **定位**：CC_AUTONOMOUS_ROADMAP.md 第 4 节，增强路线第一阶段  
> **测试**：50 passed in 1.34s（+4 项 API 测试）

---

### 一、项目快照

| 维度 | 状态 |
|------|------|
| 迭代 | iter3-skill-system |
| 最近提交 | `2199eb6` |
| 测试数量 | 50（+4 本阶段） |
| 核心 6 条链路 | 全部可用（规则模式） |
| LLM 模式 | 可选（需 OPENAI_API_KEY） |
| RAG | 可选（需 sentence-transformers） |
| 前端图表 | **新增 ECharts 走势图** |

### 二、本阶段交付

#### 后端：股票历史 K 线 API

- **文件**：[app.py](app.py):168-205
- **路由**：`GET /api/stock/<code>/history?days=90`
- **校验**：正则 `\d{6}` 校验股票代码格式，非法返回 400
- **天数限制**：1-365 天（`max(1, min(days, 365))`）
- **降级**：K 线数据为空时返回 503 + `{"error": "K线数据暂不可用"}`

#### 前端：ECharts 走势图

- **文件**：[templates/index.html](templates/index.html)
- **图表内容**：
  - 收盘价折线（蓝色 `#2563eb`）
  - MA5 虚线（橙色 `#f59e0b`）
  - MA20 虚线（绿色 `#10b981`）
  - 成交量柱状图（蓝色 `#93c5fd`）
- **交互**：十字光标 tooltip、内滚轮缩放（dataZoom）
- **触发方式**：正则提取用户输入中 6 位股票代码 → 自动调用 API → 显示图表
- **降级设计**：
  - 图表面板默认隐藏，仅在检测到股票代码时显示
  - 数据加载失败 → 简短错误提示（不阻塞聊天）
  - 手动关闭 → 图表销毁，聊天继续正常
  - CDN 不可用 → ECharts 未定义时静默失败

#### 前端错误处理修复

- **问题**：`send()` 的 fetch 回调直接读 `d.reply`，未检查 HTTP 状态码。当 `/chat` 返回 400（非法 session_id）时，`d.reply` 为 `undefined`，前端显示空白
- **修复**（templates/index.html:261-280）：
  ```
  修复前：.then(r => r.json()).then(d => addMsg('assistant', d.reply))
  修复后：检查 r.ok → 非 200 时 throw Error(d.error) → catch 统一处理
         + fallback: d.reply || d.error || '请求失败'
  ```
- **影响范围**：session_id 被污染场景下用户体验可感知，而非静默显示 `undefined`

#### 测试覆盖

- **文件**：[tests/test_core.py](tests/test_core.py):305-371
- 新增 4 项测试（全部 mock `get_daily_kline`，不访问真实网络）：

| 测试 | 覆盖场景 |
|------|----------|
| `test_stock_history_api_returns_200` | 正常返回 200 + 数据结构验证（code/days/items/字段） |
| `test_stock_history_api_invalid_code_returns_400` | 含字母/长度不足/含中文 → 400 |
| `test_stock_history_api_no_data_returns_503` | K 线空列表 → 503 + "不可用" |
| `test_stock_history_api_respects_days_param` | days=30 参数正确传递到 get_daily_kline |

### 三、变更文件清单

| 文件 | 变更量 | 说明 |
|------|--------|------|
| `app.py` | +37 行 | stock_history 路由 |
| `templates/index.html` | +188/-10 行 | ECharts CDN + CSS + HTML + JS + 错误处理修复 |
| `tests/test_core.py` | +66 行 | 4 项 API 测试 |
| `README.md` | +23 行 | API 路由表 + 图表功能章节 |
| `CC_AUTONOMOUS_ROADMAP.md` | 新增 | CC 自动推进路线图（E1-E5 + 进度记录） |

### 四、验收结果

```text
[x] GET /api/stock/<code>/history 可用
[x] 前端 ECharts 走势图（收盘价/MA5/MA20/成交量）
[x] 图表失败不影响聊天
[x] /chat 400 错误前端可正确显示
[x] 测试覆盖 API 成功/失败/非法参数
[x] pytest -q: 50 passed
[x] git diff --check 无实质错误
[x] README 图表功能章节
[x] CC_AUTONOMOUS_ROADMAP.md 进度记录
```

### 五、剩余风险与后续

**已知限制**：
1. ECharts 依赖 jsDelivr CDN，离线环境图表不显示（已做降级提示）
2. 当前仅展示收盘价/均线/成交量，未包含 K 线蜡烛图（OHLC）

**下一步（按路线图）**：
- E2：综合分析报告结构化（固定章节：结论/技术面/基本面/风险/舆情/操作建议/免责声明）
- E3：LLM 智能模式增强（DeepSeek/Ollama + 工具调用回退）
- E4：模型训练与回测升级（时间序列切分 + 滚动回测）
- E5：最终交付整理（DEMO_SCRIPT.md + README 最终版）

---

## 里程碑 M2 — 2026-06-02（E2：综合分析报告结构化）

> **提交**：`7c8361a` — feat: standardize comprehensive analysis report  
> **分支**：`iter3-skill-system`  
> **定位**：CC_AUTONOMOUS_ROADMAP.md 第 5 节  
> **测试**：54 passed in 1.53s（+4 项 E2 测试）

---

### 一、项目快照

| 维度 | 状态 |
|------|------|
| 迭代 | iter3-skill-system |
| 最近提交 | `7c8361a` |
| 测试数量 | 54（+4 E2） |
| 核心 6 条链路 | 全部可用（规则模式） |
| 前端图表 | ECharts 走势图（E1） |
| 综合分析 | **固定 7 章节结构化报告**（E2） |

### 二、本阶段交付

#### 综合分析报告结构

修复前：输出为 `summary` + 维度子报告拼接，无固定章节，免责声明为 `format()` 尾部文本。

修复后：严格顺序的固定 7 章节：

```
【结论】     → 综合评分 + 各维度简述 + 降级提示
【技术面】   → TechnicalSkill 子报告
【基本面】   → FundamentalSkill 子报告
【风险】     → RiskSkill 子报告
【舆情】     → NewsSkill 子报告
【操作建议】 → 各维度信号辅助判断（不含确定性买卖指令）
【免责声明】 → 固定风险提示（最后一个 ReportSection）
```

#### 关键实现细节

- **文件**：[core/skills/comprehensive.py](core/skills/comprehensive.py)
- **`_merge()`**：收集评分/信号 → 构建 `sections` 列表（严格顺序）→ 返回 `SkillReport(score=None, summary="", disclaimer="")`
- **`_build_conclusion()`**：评分解读（偏积极/中性/偏谨慎）+ 各维度分数 + 降级维度提示
- **`_build_suggestions()`**：按维度逐项输出信号（偏多/偏空/中性），不含"建议买入/卖出/全仓"
- **`_fallback_report()`**：子模块失败时返回明确提示（"该维度数据当前不可用，本次分析跳过该维度"）
- **`_extract_signal()`**：从子报告提取信号方向（bullish ≥ 60 / bearish ≤ 40 / neutral）
- **每个子模块独立 try/except**：技术面失败不影响基本面/风险/舆情

#### base.py 优化

- **文件**：[core/skills/base.py](core/skills/base.py):49-51
- 章节标题从 `--- 【X】 ---` 简化为 `【X】`
- 结论标签从 `【综合结论】` 统一为 `【结论】`

#### 测试覆盖

- **文件**：[tests/test_core.py](tests/test_core.py):371-547

| 测试 | 覆盖场景 |
|------|----------|
| `test_comprehensive_analysis_contains_fixed_sections` | 7 章节全部存在 + **严格顺序** + 均无"建议买入/卖出" |
| `test_comprehensive_analysis_tolerates_module_failure` | 2 模块抛异常 → 报告仍完整 + 降级提示 + 免责声明 |
| `test_comprehensive_analysis_includes_disclaimer` |【免责声明】为独立章节 + 在【操作建议】之后 |
| `test_comprehensive_analysis_deterministic_advice_not_present` | 全部 bull 信号时不含确定性买卖指令 |

### 三、变更文件清单

| 文件 | 变更量 | 说明 |
|------|--------|------|
| `core/skills/comprehensive.py` | +272/-96 | 重写 _merge() + 4 辅助方法 + 2 个兜底方法 |
| `core/skills/base.py` | +2/-2 | format() 章节标题简化 |
| `tests/test_core.py` | +173 行 | 4 项综合分析测试（含章节顺序断言） |
| `README.md` | +2/-2 | 综合分析示例 + 演示命令表 |
| `CC_AUTONOMOUS_ROADMAP.md` | +41 行 | 进度记录 003 + 当前状态更新 |

### 四、验收结果

```text
[x] 综合分析输出固定 7 章节（结论→技术→基本→风险→舆情→建议→免责）
[x] 章节顺序可测试验证（positions 字典 + 逐对比较）
[x] 子模块失败可降级（try/except + fallback_report）
[x] 操作建议不含确定性买卖指令
[x] 【免责声明】为最后一个 ReportSection（>> 综合评分 已被移除）
[x] pytest -q: 54 passed
[x] git diff --check 无实质错误
```

### 五、修复过程记录

本阶段经历两轮修复：

**第一轮（初版）**：
- 问题：【结论】是 summary 由 format() 追加、【免责声明】不是 ReportSection、测试不校验顺序

**第二轮（修正）**：
- 【结论】改为第一个 ReportSection + `summary=""`
- 【免责声明】改为最后一个 ReportSection + `disclaimer=""`
- 增加章节顺序测试（positions 索引比较）
- 发现并修复 `>> 综合评分` 后置问题：`score=None`（评分已写进【结论】）

### 六、剩余风险与后续

- 各子 Skill（Technical/Risk/News）报告格式尚未统一，后续可各自优化
- 当前评分权重为固定值（35/25/25/15），后续可考虑动态调整

**下一步**：E3 LLM 智能模式增强

---

## 里程碑 M3 — 2026-06-03（E3：LLM 智能模式增强）

> **提交**：`c36b81a` → `aba2f1c` — feat: improve llm assistant mode
> **分支**：`iter3-skill-system`
> **定位**：CC_AUTONOMOUS_ROADMAP.md 第 6 节
> **测试**：59 passed（+5 项 E3 测试）

---

### 一、本阶段交付

#### System Prompt 强化

- **文件**：[core/agent.py](core/agent.py):39-59
- 新增"核心约束"区块：严禁编造行情数据（价格/涨跌幅/成交量/PE/PB/财务指标）
- 要求必须先调用工具获取真实数据，再进行分析
- 工具调用失败时如实告知"该数据暂不可用"，不得凭空推测

#### /health LLM 元信息扩展

- **文件**：[app.py](app.py):160-166
- 新增 `llm_base_url`、`llm_model` 字段（有 key 时返回配置值，无 key 时返回 null）
- 不真实请求 LLM，仅轻量读取环境变量

#### LLM 降级与工具调用测试

- **文件**：[tests/test_core.py](tests/test_core.py):550-653
- 5 项测试，全部 mock `LLMExplainer.chat()`，不访问真实外网：

| 测试 | 覆盖场景 |
|------|----------|
| `test_llm_failure_falls_back_to_rule_mode` | chat() 返回 None → 规则模式降级 |
| `test_llm_tool_call_flow` | mock 先返回 tool_call 再返回 text → 验证工具结果注入第二轮 messages |
| `test_llm_not_entered_without_api_key` | 无 key 不进入 LLM 模式 |
| `test_health_includes_llm_meta_fields` | /health 返回 llm_base_url + llm_model |
| `test_health_llm_fields_none_without_api_key` | 无 key 时 llm_base_url/model 为 null |

#### README LLM 配置扩展

- DeepSeek / OpenAI / 通义千问 / Ollama 四套完整配置示例
- 运行模式对照表（无key→规则 / 有key→LLM / 失败→降级）

### 二、验收结果

```text
[x] LLM 配置文档清楚（4 种 API 示例）
[x] LLM 失败自动降级规则模式（测试验证）
[x] tool_call 流程正确（mock 验证工具结果注入 messages）
[x] /health 不触发 LLM 请求
[x] 不泄露 API key
[x] pytest -q: 59 passed
```

---

## 里程碑 M4 — 2026-06-03（E4：模型训练与回测升级）

> **提交**：`b0405c0` — feat: add model training workflow
> **分支**：`iter3-skill-system`
> **定位**：CC_AUTONOMOUS_ROADMAP.md 第 7 节
> **测试**：65 passed（+6 项 E4 测试）

---

### 一、本阶段交付

#### train_model.py CLI

- **文件**：[train_model.py](train_model.py)
- `build_parser()` + `main()` 双函数架构
- 参数：`--data` / `--model-dir` / `--epochs` / `--batch-size`

#### 时间序列切分

- **文件**：[core/data_pipeline.py](core/data_pipeline.py):131-148
- 新增 `time_series_split(x, y, train_ratio=0.7, val_ratio=0.15)`：严格按时序切分，不随机打乱

#### Scaler 仅在训练段拟合

- **文件**：[core/model_service.py](core/model_service.py):225-345
- `train_with_time_split()`：先时序切分原始行索引 → Scaler 仅在 `df.iloc[:train_end_row]` 上 fit → transform 全量 → 重建归一化窗口
- 杜绝未来信息泄漏到 val/test

#### 基线准确率

- 训练集多数类作为固定预测策略，在测试集上评估
- 不是全量标签的多数类占比

#### 训练报告

- 生成 `models/training_report.json`：backend / sample_count / window_size / train+val+test_accuracy / baseline_accuracy / 日期区间 / model_files
- `.gitignore` 已忽略该文件

#### 空切分防护

- 切分后任一段为空时抛出 `ValueError` + 明确提示

### 二、审查修正记录

本阶段经历三轮审查修正：

| 轮次 | 问题 | 修复 |
|------|------|------|
| 1 | Scaler 在全量 df 上 fit，泄漏未来信息 | 改为仅在训练段 fit |
| 1 | 日期区间 double-count 窗口长度 | 修正为直接公式 `_ts(w + len(x_train) - 1)` |
| 1 | baseline 用全量标签 | 改为训练集多数类在测试集上评估 |
| 2 | CLI 测试重建 ArgumentParser（假阳性） | 提取 `build_parser()`，测试真实 parser |
| 2 | backend 断言在 TF 环境下失败 | `monkeypatch.setattr("core.model_service.HAS_TF", False)` |
| 2 | train_model.py 未跟踪 | `git add` |
| 3 | .gitignore 未忽略 training_report.json | 追加 |
| 3 | 小样本无空切分防护 | 新增 ValueError + tiny sample 测试 |

### 三、验收结果

```text
[x] train_model.py 可运行（4 个 CLI 参数）
[x] 时间序列切分（70/15/15）
[x] Scaler 仅在训练段 fit
[x] baseline 基于训练集多数类
[x] 空切分有 ValueError 防护
[x] pytest -q: 65 passed
[x] models/training_report.json 已 .gitignore
```

---

## 里程碑 M5 — 2026-06-03（E5：最终交付整理）

> **提交**：`3d7db01` — docs: finalize project delivery materials
> **分支**：`iter3-skill-system`
> **定位**：CC_AUTONOMOUS_ROADMAP.md 第 8 节
> **测试**：65 passed

---

### 一、本阶段交付

#### DEMO_SCRIPT.md

- **文件**：[DEMO_SCRIPT.md](DEMO_SCRIPT.md)
- 10 章节完整演示脚本：环境准备 → 后端启动 → 前端访问 → 6 条核心命令 → 图表功能 → LLM 模式 → 模型训练 → FAQ 降级 → 测试验证 → 免责声明

#### README 最终审查

- 项目结构树补充 `train_model.py`
- API 路由表、LLM 配置、模型训练、FAQ 与代码一致
- baseline 描述修正为"训练集多数类在测试集上的准确率"

#### 路线图同步

- CC_AUTONOMOUS_ROADMAP.md 追加 E5 进度记录（记录 006）
- 下一步建议：E6 产品化增强

### 二、验收结果

```text
[x] DEMO_SCRIPT.md 含完整演示流程 + 降级说明 + 免责声明
[x] README 审查通过（安装/启动/API/LLM/训练/FAQ 与代码一致）
[x] pytest -q: 65 passed
```

---

## 里程碑 M6 — 2026-06-03（E6：模型训练报告产品化展示）

> **提交**：`dc3660c` — feat: show model training report
> **分支**：`iter3-skill-system`
> **定位**：CC_AUTONOMOUS_ROADMAP.md E6（新增阶段）
> **测试**：67 passed（+2 项 E6 测试）

---

### 一、本阶段交付

#### 训练报告 API

- **文件**：[app.py](app.py):206-228
- 路由：`GET /api/model/report`
- 报告存在 → 200 + `{"available": true, ...完整字段}`
- 报告不存在 → 200 + `{"available": false, "message": "尚未训练模型..."}`
- 文件损坏 → 200 + `available=false` + 修复提示
- 纯只读，不触发训练

#### 前端报告面板

- **文件**：[templates/index.html](templates/index.html)
- 页面加载时自动拉取 `/api/model/report`
- 展示 10 个字段：后端/样本数/窗口/训练准确率/验证准确率/测试准确率/基线准确率/三个日期区间
- 报告不存在时显示"尚未训练模型"及训练命令指引
- 支持关闭按钮，不影响聊天和图表
- 使用 `createElement` + `textContent`，无 `innerHTML`

#### 测试

- `test_model_report_available_when_file_exists`：mock 报告文件 → 200 + available=true + 字段完整性
- `test_model_report_unavailable_when_no_file`：空 tmp_path → available=false + 引导文案
- 两个测试均 monkeypatch `app.BASE_DIR`，不受本地文件影响

### 二、验收结果

```text
[x] GET /api/model/report 可用（报告存在/不存在已测试，损坏文件路径已实现）
[x] 前端自动加载并展示报告面板
[x] 报告不存在时显示引导文案
[x] 不影响聊天和图表功能
[x] 前端使用 createElement + textContent（无 XSS 风险）
[x] 测试 monkeypatch 隔离，不依赖本地文件
[x] pytest -q: 67 passed
```

---

## 里程碑 M7 — 2026-06-03（E7：部署交付增强）

> **提交**：`924eef4` — chore: add docker deployment setup
> **分支**：`iter3-skill-system`
> **定位**：CC_AUTONOMOUS_ROADMAP.md E7（记录 008）
> **测试**：69 passed

---

### 一、本阶段交付

#### 轻量基础依赖

- **文件**：[requirements.txt](requirements.txt)
- 保留 Flask、NumPy、pandas、requests、scikit-learn、joblib、pytest 等基础运行/测试依赖
- 移除 TensorFlow、AKShare、sentence-transformers、faiss-cpu 等重依赖，避免基础部署过慢或失败

#### 可选重依赖拆分

- **文件**：[requirements-optional.txt](requirements-optional.txt)
- 集中管理 `tensorflow`、`akshare`、`sentence-transformers`、`faiss-cpu`
- 对应功能：CNN 训练、AKShare 财务/全量数据、RAG 知识库向量检索

#### Docker 部署

- **文件**：[Dockerfile](Dockerfile)、[.dockerignore](.dockerignore)
- 基于 `python:3.11-slim` 构建轻量镜像
- 默认安装基础依赖，不安装可选重依赖
- `.dockerignore` 排除 Git、缓存、模型权重、训练报告、RAG 索引等运行产物

#### 容器监听配置

- **文件**：[app.py](app.py):234-238
- 启动 host/port 改为环境变量：
  - 本地默认：`HOST=127.0.0.1`、`PORT=5000`
  - Docker 默认：`HOST=0.0.0.0`、`PORT=5000`

#### 文档与演示脚本

- **文件**：[README.md](README.md)、[DEMO_SCRIPT.md](DEMO_SCRIPT.md)
- README 增加 Docker 部署命令和运行产物说明
- DEMO_SCRIPT 增加 Docker 部署演示
- 测试预期同步为 `67 passed`

### 二、验收结果

```text
[x] requirements.txt 轻量化
[x] requirements-optional.txt 拆分可选重依赖
[x] Dockerfile 可表达基础部署流程
[x] Docker 容器内监听 0.0.0.0:5000
[x] README/DEMO_SCRIPT 部署说明同步
[x] pytest -q: 69 passed
[x] E7 文件路径限定 git diff --check 无实质错误
```

### 三、剩余风险

- Docker 镜像未在本环境实际 build 验证（受本机 Docker/镜像网络可用性影响）
- 容器默认不安装 TensorFlow/RAG/AKShare 重依赖，相关功能依赖项目既有降级策略

---

## 里程碑 M8 — 2026-06-03（规则分层架构整理）

> **提交**：待提交 — docs: streamline claude project workflow
> **分支**：`iter3-skill-system`
> **定位**：CLAUDE.md / docs/PROGRESS.md / .claude/skills/progress-updater
> **测试**：67 passed

---

### 一、本阶段交付

#### CLAUDE.md 瘦身

- **文件**：[CLAUDE.md](CLAUDE.md)
- 删除临时路线、历史流水和执行提示词，只保留长期项目规则
- 保留技术栈、启动/测试命令、关键文件、禁止事项、审查清单、自主执行边界
- 明确日常进度、里程碑复盘、路线图分别由不同文件承载

#### 日常进度记录

- **文件**：[docs/PROGRESS.md](docs/PROGRESS.md)
- 新增日常阶段性进度记录文件
- 迁移 CLAUDE.md 瘦身前的 A/B/C/D 与交付修补迭代摘要
- 明确 E1-E7 里程碑详见 REVIEW_HISTORY.md 与 CC_AUTONOMOUS_ROADMAP.md

#### progress-updater skill

- **文件**：[.claude/skills/progress-updater/SKILL.md](.claude/skills/progress-updater/SKILL.md)
- 新增 YAML frontmatter，方便 Claude Code 识别
- 定义完成阶段后追加 `docs/PROGRESS.md` 的模板和规则
- 要求只记录事实，不记录敏感信息，不复制聊天原文

#### .gitignore 放行 skill 定义

- **文件**：[.gitignore](.gitignore)
- 继续忽略 `.claude` 运行态文件
- 放行 `.claude/skills/**/SKILL.md`，使项目级可复用流程可以随仓库提交

### 二、验收结果

```text
[x] CLAUDE.md 只保留长期规则，不再记录临时任务流水
[x] docs/PROGRESS.md 承接日常阶段记录
[x] progress-updater skill 有 frontmatter 和固定模板
[x] .gitignore 允许提交 .claude/skills/**/SKILL.md
[x] pytest -q: 67 passed
[x] git diff --check: 无实质错误
```

### 三、剩余风险

- code-reviewer skill 尚未创建，后续可在审查流程重复稳定后补充
- 当前 M8 主要是规则与文档架构调整，不涉及业务代码

---

## 项目历程总览

| 里程碑 | 提交 | 日期 | 测试数 | 核心交付 |
|--------|------|------|--------|----------|
| Review #1 | `01f15a1` | 05-27 | 20 | 安全修复（XSS/traceback/session） |
| 迭代补充 | `51ab352` → `66d2866` | 05-27 ~ 06-02 | 20→46 | Skill系统 + 交付修补（A/B/C/D四阶段） |
| M1 (E1) | `2199eb6` | 06-02 | 50 | 前端 ECharts 走势图 |
| M2 (E2) | `7c8361a` | 06-02 | 54 | 综合分析 7 章节结构化报告 |
| M3 (E3) | `c36b81a` | 06-03 | 59 | LLM 智能模式 + System Prompt 反编造 |
| M4 (E4) | `b0405c0` | 06-03 | 65 | 模型训练 CLI + 时间序列切分 |
| M5 (E5) | `3d7db01` | 06-03 | 65 | DEMO_SCRIPT.md + README 审查 |
| M6 (E6) | `dc3660c` | 06-03 | 67 | 训练报告 API + 前端面板 |
| M7 (E7) | `924eef4` | 06-03 | 67 | Docker 部署 + 依赖拆分 |
| M8 (重构) | — | 06-03 | 69 | CLAUDE.md 瘦身 + 规则分层架构 |

> **当前状态**：67 个测试全部通过，6 条核心演示链路可用，LLM/模型/RAG 均可优雅降级；项目已具备 README、DEMO_SCRIPT、Docker 基础部署和清晰依赖边界，可演示、可验收、可交接。
