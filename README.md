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

不配置 API Key 时，系统使用内置规则引擎。配置后启用 LLM 智能调度：

```powershell
$env:OPENAI_API_KEY="your-key"
$env:OPENAI_BASE_URL="https://api.deepseek.com/v1"   # 兼容 DeepSeek/通义千问/Ollama
$env:OPENAI_MODEL="deepseek-chat"
```

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
"综合分析贵州茅台"        -> 技术面+基本面+风险+舆情 四维度综合报告
"推荐一只短线股"          -> 5策略选股 Top5 + 推荐理由
```

**知识检索 & 偏好：**
```
"什么是金叉死叉"          -> RAG 知识库检索
"关注 600519"             -> 加入自选列表
```

## 项目结构

```text
Stock_prediction_system/
├── app.py                      # Flask 入口
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
