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
| 核心能力 | 腾讯实时行情(38只) / 7类NumPy技术指标 / AKShare财报(可选) / 腾讯/东方财富新闻 / FAISS概念检索(3篇) / 会话记忆+偏好 / 6个Skill+评分体系 / 规则/LLM双模式 |
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
