# 股票分析助手（迭代 1 — 单 Agent 问答）

基于 ReAct Agent 模式的 A 股智能分析系统。输入股票代码或名称，即可查询实时行情、历史走势、CNN 模型预测、多股对比。

---

## 功能

- **股票搜索**：按名称或代码查找 A 股
- **实时行情**：最新价、涨跌幅、市盈率、市净率、总市值
- **历史走势**：日 K 线数据，含区间涨跌幅统计
- **涨跌预测**：CNN / MLP 模型预测下一时段方向与概率
- **多股对比**：横向对比关键指标
- **LLM 驱动**（可选）：配置 API Key 后启用 Agent 自主工具调度

---

## 快速开始

```bash
pip install -r requirements.txt
python app.py
```

浏览器访问 `http://127.0.0.1:5000`，在对话框中输入：

- `搜索平安银行`
- `查询 600519 的行情`
- `000001 近30天走势`
- `预测茅台涨跌`
- `对比 600519 和 000858`

---

## LLM 配置（可选）

不配置 API Key 时，系统使用内置规则引擎，所有功能正常可用。

如需启用 LLM 驱动的 Agent：

```powershell
$env:OPENAI_API_KEY="your-key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"    # 可选
$env:OPENAI_MODEL="gpt-4o-mini"                      # 可选
python app.py
```

---

## 项目结构

```text
Stock_prediction_system/
├─ app.py                    # Flask 入口
├─ core/
│  ├─ agent.py               # ReAct Agent 循环 + 规则降级
│  ├─ tools.py               # 工具集（搜索/行情/历史/预测/对比）
│  ├─ market_data.py         # 腾讯股票 API 适配层
│  ├─ model_service.py       # CNN/MLP 模型训练与预测
│  ├─ data_pipeline.py       # 数据预处理与窗口构造
│  └─ llm_service.py         # LLM 调用与解释服务
├─ templates/
│  └─ index.html             # Chat 对话界面
├─ dataset/
│  └─ tt.csv                 # 示例训练数据
├─ models/                   # 训练产出（自动生成）
└─ requirements.txt
```

---

## 迭代路线

| 迭代 | 内容 | 状态 |
|------|------|------|
| 1 | 单股票问答 Agent（行情 + 预测） | 已完成 |
| 2 | 工具系统 + RAG + 记忆 | 待开发 |
| 3 | Skill 系统（技术分析/基本面/选股） | 待开发 |
| 4 | 网关路由（意图分类 → 分发） | 待开发 |
| 5 | 多 Agent 协同 + Harness 管控 | 待开发 |

---

## 数据源

- 行情 / K 线：腾讯证券 API
- 股票列表：内置 A 股常用列表（可配置 `USE_AKSHARE=1` 启用 AKShare 全量列表）
- 预测模型：1D CNN（TensorFlow）或 MLP（sklearn 降级）
