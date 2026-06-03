# 股票预测智能分析系统 (Stock Prediction System)

基于 Flask 的 A 股智能分析对话系统，提供 Web 聊天界面。支持自然语言查询实时行情、技术指标、基本面、新闻舆情、CNN 模型预测和量化选股推荐。

**双模式运行**：有 LLM 时智能调用工具，无 LLM 时基于规则引擎也能工作。

---

## 快速开始

```bash
pip install flask numpy pandas requests scikit-learn sentence-transformers
python app.py
# 访问 http://127.0.0.1:5000
```

**可选依赖**：`tensorflow`（CNN 模型）、`akshare`（更多数据源），设置 `USE_AKSHARE=1` 启用。

## LLM 配置（可选）

不配置 API Key 时，系统使用内置规则引擎（关键词匹配 + 直接工具调度）。配置任一 OpenAI-compatible API 后，系统启用 LLM 智能模式（function calling + 最多 8 轮工具迭代）。

### DeepSeek（推荐，性价比高）

```powershell
$env:OPENAI_API_KEY="sk-your-deepseek-key"
$env:OPENAI_BASE_URL="https://api.deepseek.com/v1"
$env:OPENAI_MODEL="deepseek-chat"
```

### OpenAI

```powershell
$env:OPENAI_API_KEY="sk-your-openai-key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4o-mini"
```

### 通义千问（阿里云 DashScope）

```powershell
$env:OPENAI_API_KEY="sk-your-qwen-key"
$env:OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:OPENAI_MODEL="qwen-plus"
```

### Ollama（本地部署，免费）

```bash
# 先启动 Ollama 并拉取模型
ollama pull qwen2.5:7b

# Linux/macOS
export OPENAI_API_KEY="ollama"          # 必填但可为任意值
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_MODEL="qwen2.5:7b"
```

```powershell
# Windows PowerShell
$env:OPENAI_API_KEY="ollama"
$env:OPENAI_BASE_URL="http://localhost:11434/v1"
$env:OPENAI_MODEL="qwen2.5:7b"
```

### 运行模式说明

| 条件 | 模式 | 行为 |
|------|------|------|
| 未配置 API Key | 规则模式 | 13 种意图关键词匹配 + 直接工具调度 |
| 已配置 API Key | LLM 模式 | function calling + 最多 8 轮工具迭代 |
| LLM 请求失败 | 自动降级 | 回退到规则模式，不影响用户使用 |
| 工具调用失败 | 优雅降级 | LLM 告知用户"该数据暂不可用" |

**LLM 安全约束**：LLM 模式下，系统 prompt 明确禁止编造行情数据。所有价格、涨跌幅、财务指标必须通过工具调用获取真实数据，无法获取时如实告知用户。

## 系统架构

```
templates/index.html (前端 Chat UI)
        │
    app.py (Flask: /chat, /memory, /health)
        │
    core/agent.py (对话调度层)
        ├── LLM 模式：OpenAI function calling + 最多8轮工具迭代
        └── 规则模式：13种意图关键词匹配 + 直接路由
        │
        ├── core/skills/ (迭代3：Skill 技能系统)
        │   ├── TechnicalSkill       — 技术分析报告 (评分0-100)
        │   ├── FundamentalSkill     — 基本面评估 (估值评级)
        │   ├── RiskSkill            — 风险评估 (波动率/回撤/仓位)
        │   ├── ScreeningSkill       — 选股推荐 (5策略Top5)
        │   ├── NewsSkill            — 新闻舆情 (关键词+情感分析)
        │   ├── ComprehensiveSkill   — 四维度综合分析
        │   └── gateway.py           — Skill 注册与路由
        │
        ├── core/tools.py (18个工具：12基础+5Skill+1偏好)
        ├── core/llm_service.py (OpenAI兼容协议，零SDK依赖)
        ├── core/market_data.py (腾讯免费API：行情+K线)
        ├── core/indicators.py (纯NumPy：MA/MACD/RSI/BOLL/KDJ/形态)
        ├── core/model_service.py (CNN/MLP双后端预测)
        ├── core/rag_service.py (NumPy向量检索知识库)
        ├── core/memory.py (会话记忆+偏好持久化)
        ├── core/fundamentals.py (AKShare财报)
        ├── core/news.py (腾讯/东方财富新闻)
        └── core/screener.py (5策略量化选股引擎)
```

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端聊天页面 |
| POST | `/chat` | 对话 `{query, session_id}` -> `{reply}` |
| GET | `/memory?session_id=xxx` | 读取用户偏好 |
| POST | `/memory` | 更新偏好 `{session_id, key, value}` |
| GET | `/health` | 健康检查 (模型/LLM/RAG) |
| GET | `/api/stock/<code>/history?days=90` | 历史K线 `{code, days, items[{date,open,high,low,close,volume}]}` |

## 使用示例

**基础查询：**
```
"搜索平安银行"           -> 股票代码搜索
"查询 600519 的行情"     -> 实时行情
"000001 近60天走势"      -> 历史K线 + 区间涨跌幅
"预测 600519 涨跌"       -> CNN/MLP 模型预测
"对比 600519 和 000001"  -> 多股对比表格
```

**Skill 技能 (迭代3)：**
```
"技术分析贵州茅台"        -> 均线/MACD/RSI/BOLL/KDJ/形态 + 综合评分 + 操作建议
"基本面分析 000001"       -> PE/PB估值区间 + ROE/毛利率/营收 + 估值评级
"评估 600519 的风险"     -> 波动率/最大回撤/VaR + 风险等级 + 仓位止损建议
"茅台最近有什么新闻"      -> 新闻列表 + 关键词提取 + 情感倾向
"综合分析贵州茅台"        -> 固定章节报告：【结论】【技术面】【基本面】【风险】【舆情】【操作建议】【免责声明】
"推荐一只短线股"          -> 5策略选股 Top5 + 推荐理由
```

**知识检索 & 偏好：**
```
"什么是金叉死叉"          -> RAG 知识库检索
"关注 600519"             -> 加入自选列表
```

## 图表功能 (E1)

前端集成了 ECharts 走势图，输入包含 6 位股票代码的内容时自动展示：

- **收盘价**走势曲线
- **MA5** / **MA20** 移动平均线（虚线）
- **成交量**柱状图
- 支持鼠标缩放、十字光标、数据提示

图表区域位于状态栏下方，不影响聊天消息流。数据加载失败时显示简短错误提示，关闭后聊天仍正常工作。

**触发图表的输入示例：**

```
查询 600519 行情
分析 600519 技术指标
600519 近90天走势
评估 600519 风险
```

> ECharts 通过 CDN 加载（jsDelivr），首次使用需网络连接。如 CDN 不可用，图表区域显示降级提示，不影响聊天。

## 项目结构

```text
Stock_prediction_system/
├── app.py                      # Flask 入口
├── train_model.py              # 模型训练 CLI
├── core/
│   ├── agent.py                # Agent 调度层 (LLM/规则双模式)
│   ├── tools.py                # 工具注册/分组/执行 (18个)
│   ├── market_data.py          # 腾讯 API 适配 (行情+K线+搜索)
│   ├── indicators.py           # NumPy 技术指标 (7类+K线形态)
│   ├── model_service.py        # CNN/MLP 模型预测
│   ├── data_pipeline.py        # 滑动窗口+归一化
│   ├── llm_service.py          # OpenAI 兼容 API (function calling)
│   ├── rag_service.py          # NumPy 向量检索知识库
│   ├── memory.py               # 会话记忆+用户偏好
│   ├── fundamentals.py         # AKShare 财报数据
│   ├── news.py                 # 腾讯/东方财富新闻
│   ├── screener.py             # 5策略量化选股引擎
│   └── skills/                 # [迭代3] Skill 技能系统
│       ├── base.py             # Skill 基类+结构化报告
│       ├── technical.py        # 技术分析 Skill
│       ├── fundamental.py      # 基本面分析 Skill
│       ├── risk.py             # 风险评估 Skill
│       ├── screening.py        # 选股推荐 Skill
│       ├── news.py             # 新闻舆情 Skill
│       ├── comprehensive.py    # 综合分析 Skill
│       └── gateway.py          # Skill 注册表+路由
├── templates/
│   └── index.html              # Chat 界面
├── models/                     # 训练模型 (自动生成)
│   ├── stock_mlp.joblib        # MLP 降级模型
│   ├── scaler.json             # 归一化参数
│   └── meta.json               # 模型元信息
├── data/
│   ├── knowledge/*.md          # RAG 知识库文档
│   ├── knowledge_index.json    # 预计算向量索引
│   └── memory/*.json           # 用户偏好 (按session_id)
└── dataset/
    └── tt.csv                  # 示例训练数据
```

## 技术栈

| 层 | 技术 |
|----|------|
| Web | Flask |
| 前端 | 原生 HTML/CSS/JS |
| 深度学习 | TensorFlow CNN / sklearn MLP (降级) |
| 数值计算 | NumPy |
| 向量检索 | sentence-transformers + NumPy（可切 FAISS） |
| 数据源 | 腾讯免费 API / AKShare (可选) |
| LLM | OpenAI 兼容协议 |

## 核心演示命令

启动系统后，在聊天界面输入以下6条命令，验证核心链路：

| # | 输入 | 预期输出 |
|---|------|----------|
| 1 | `搜索 贵州茅台` | 返回 `600519 / 贵州茅台` |
| 2 | `查询 600519 行情` | 返回最新价、涨跌幅、PE/PB 等字段 |
| 3 | `分析 600519 技术指标` | 返回 MA/MACD/RSI/BOLL/KDJ + 综合评分 |
| 4 | `评估 600519 风险` | 返回波动率/回撤/风险等级/仓位止损建议 |
| 5 | `综合分析 600519` | 固定章节：结论/技术面/基本面/风险/舆情/操作建议/免责声明 |
| 6 | `什么是金叉死叉` | 返回 RAG 知识库检索内容 |

> 如 RAG 知识库未初始化，链路 6 会返回"知识库中未找到相关内容"（优雅降级）。

## 模型训练（可选）

### 命令行训练

```bash
python train_model.py --data dataset/tt.csv --model-dir models
```

可选参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--data` | `dataset/tt.csv` | 训练数据 CSV 路径 |
| `--model-dir` | `models` | 模型输出目录 |
| `--epochs` | `12` | CNN 训练轮数（MLP 忽略） |
| `--batch-size` | `32` | CNN 批次大小（MLP 忽略） |

### 训练切分策略

使用**时间序列切分**（不打乱数据）：

```text
前 70% → 训练集
中 15% → 验证集（CNN 使用，MLP 忽略）
后 15% → 测试集
```

随机打乱的 `train_test_split` 会泄漏未来信息到训练集，时间序列切分更接近真实交易场景。

### 训练报告

训练完成后生成 `models/training_report.json`：

```json
{
  "backend": "sklearn_mlp_fallback",
  "sample_count": 940,
  "window_size": 60,
  "train_accuracy": 0.6234,
  "val_accuracy": 0.5812,
  "test_accuracy": 0.5532,
  "baseline_accuracy": 0.5213,
  "train_start": "2024-01-01",
  "train_end": "2025-06-15",
  "val_start": "2025-06-16",
  "val_end": "2025-09-01",
  "test_start": "2025-09-02",
  "test_end": "2025-12-31",
  "model_files": ["stock_mlp.joblib", "scaler.json", "meta.json"]
}
```

- `baseline_accuracy`：以训练集多数类作为固定预测，在测试集上的准确率；模型需显著超过此值才有意义
- `model_files`：生成的模型文件列表

### 模型局限

- 仅基于历史 OHLCV 价格特征，不包含基本面、宏观、情绪等因子
- 时间序列切分保证不泄漏未来信息，但准确率通常低于随机切分
- CNN/MLP 均为简单架构，不构成投资策略；回测结果不代表未来表现
- 预测输出为「涨/跌」二分类 + 置信度，不是确定性买卖信号

如已安装 TensorFlow，将优先训练 CNN；如 TensorFlow 不可用，将自动降级为 sklearn MLP。模型文件生成到 `models/` 目录：`stock_cnn.keras`（或 `stock_mlp.joblib`）+ `scaler.json` + `meta.json` + `training_report.json`。

## 常见问题

**Q: 启动后聊天界面显示异常？**
A: 确保 `templates/index.html` 存在，且浏览器控制台无 JavaScript 报错。

**Q: 行情/K线数据获取失败？**
A: 系统使用腾讯免费 API，无需注册。检查网络是否能访问 `qt.gtimg.cn` 和 `web.ifzq.gtimg.cn`。

**Q: 如何启用 LLM 智能模式？**
A: 配置 `OPENAI_API_KEY` 环境变量，兼容 OpenAI、DeepSeek、通义千问、Ollama 等。

**Q: 如何启用 AKShare 全量数据？**
A: `pip install akshare`，设置环境变量 `USE_AKSHARE=1`。

**Q: 模型预测为什么显示"简易版"？**
A: 尚未训练模型时，系统自动降级为均线交叉判断。运行上面的训练命令即可。

**Q: RAG 知识库如何构建？**
A: 在 `data/knowledge/` 下放置 `.md` 文件，首次知识检索时自动构建索引。也可以启动后首次询问投资知识触发构建。

## 候选股池

内置 38 只大市值/高流动性 A 股，覆盖沪深主板、创业板、科创板。  
设置 `USE_AKSHARE=1` 可启用全 A 股列表 (~5000只)。

## 迭代路线

| 迭代 | 分支 | 核心交付 |
|------|------|----------|
| 1 | `main` | 单股票问答 Agent (行情+预测)，CSV 数据训练 |
| 2 | `iter2-tools-rag-memory` | 12 工具系统 + RAG 知识库 + 记忆系统 + 选股引擎 |
| 3 | `iter3-skill-system` | Skill 技能系统 (6 Skills + 结构化报告 + 评分体系) |

## 免责声明

本系统仅供学习和研究使用，所有分析结果不构成投资建议。股市有风险，投资需谨慎。
