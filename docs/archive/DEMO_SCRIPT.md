# Demo Script — 股票预测智能分析系统

> 项目简介：基于 Flask 的 A 股智能分析对话系统，支持自然语言查询行情、技术分析、风险评估、新闻舆情、CNN 模型预测和 RAG 知识检索。双模式运行（LLM 智能模式 / 规则引擎降级）。

---

## 1. 环境准备

```bash
# 基础依赖（必装）
pip install -r requirements.txt

# 可选依赖
pip install -r requirements-optional.txt

# 若使用 Ollama 本地 LLM（免费）
ollama pull qwen2.5:7b
```

---

## 2. 后端启动

```bash
cd Stock_prediction_system
python app.py
# 输出示例：
#  * Running on http://127.0.0.1:5000
```

访问 `http://127.0.0.1:5000/health` 确认服务正常（布尔值随环境变化，字段存在即可）：

```json
{
  "status": "ok",
  "model_loaded": false,
  "llm_available": false,
  "llm_base_url": null,
  "llm_model": null,
  "rag_ready": false
}
```

> `model_loaded`、`rag_ready` 在训练模型/构建知识库后变为 `true`；`llm_available` 在配置 `OPENAI_API_KEY` 后变为 `true`。

---

## 3. Docker 部署演示

```bash
docker build -t stock-prediction-system .
docker run --rm -p 5000:5000 stock-prediction-system
```

访问 `http://127.0.0.1:5000`。容器默认安装基础依赖，不包含 TensorFlow、AKShare、sentence-transformers 等可选重依赖；相关功能会按项目降级策略处理。

---

## 4. 前端访问

浏览器打开 `http://127.0.0.1:5000`，进入聊天界面。

---

## 5. 核心演示 — 6 条命令链路

在聊天输入框中依次输入以下内容：

### 4.1 搜索股票

```
搜索 贵州茅台
```

**预期**：返回 `600519 / 贵州茅台` 搜索结果。

**降级**：如腾讯 API 不可用，显示"未找到与「贵州茅台」匹配的股票"。

---

### 4.2 实时行情

```
查询 600519 行情
```

**预期**：返回最新价、涨跌幅、成交量、PE/PB、总市值等字段。

**同时**：页面下方自动展示 ECharts 走势图（收盘价 + MA5/MA20 + 成交量）。若 CDN 不可用，图表区显示降级提示，不影响聊天。

---

### 4.3 技术分析

```
分析 600519 技术指标评
```

**预期**：返回 MA/MACD/RSI/BOLL/KDJ + 综合评分(0-100) + 操作建议。

---

### 4.4 风险评估

```
评估 600519 风险
```

**预期**：返回波动率、最大回撤、VaR、风险等级(0-3) + 仓位与止损建议。

---

### 4.5 综合分析

```
综合分析 600519
```

**预期**：返回固定章节报告：

```
【结论】→ 【技术面】→ 【基本面】→ 【风险】→ 【舆情】→ 【操作建议】→ 【免责声明】
```

部分维度数据不可用时，对应章节显示"该数据源当前不可用，本次分析跳过该维度"。

---

### 4.6 知识检索

```
什么是金叉死叉
```

**预期**：RAG 知识库检索结果。

**降级**：如未安装 `sentence-transformers` 或知识库无内容，返回"知识库尚未初始化或当前不可用"。

---

## 6. 图表功能演示 (E1)

输入包含 6 位股票代码的内容时，ECharts 图表自动加载：

```
查询 600519 行情
分析 600519 技术指标
600519 近90天走势
```

图表功能：
- 收盘价折线 + MA5/MA20 虚线
- 成交量柱状图
- 鼠标缩放、十字光标
- 数据失败时显示错误提示，关闭后聊天正常

---

## 7. LLM 智能模式演示 (E3)

### 6.1 启用 LLM

```powershell
# DeepSeek（推荐）
$env:OPENAI_API_KEY="sk-your-key"
$env:OPENAI_BASE_URL="https://api.deepseek.com/v1"
$env:OPENAI_MODEL="deepseek-chat"

# 或 Ollama（本地免费）
$env:OPENAI_API_KEY="ollama"
$env:OPENAI_BASE_URL="http://localhost:11434/v1"
$env:OPENAI_MODEL="qwen2.5:7b"
```

设置后重启 `python app.py`，访问 `/health` 确认 `llm_available: true`。

### 6.2 验证 LLM 模式

在聊天界面输入：

```
帮我查一下平安银行最近走势，再分析一下技术面
```

**预期**：LLM 自动调用 `search_stock` → `get_stock_history` → `calc_indicators`，多轮工具调用后汇总给出结论。

### 6.3 降级验证

不设置 `OPENAI_API_KEY`（或设错），系统自动使用规则引擎，功能正常。

---

## 8. 模型训练演示 (E4/E6)

### 7.1 查看帮助

```bash
python train_model.py --help
```

### 7.2 准备真实日线并开始训练

```bash
python scripts/prepare_blind_test_data.py --start 2015-01-01
python train_model.py --data data/blind_test/600519_daily.csv --model-dir models/blind_test --backend mlp --symbol 600519 --stock-name 贵州茅台 --data-source "AKShare / 东方财富" --adjust qfq
```

**输出示例**：

```
训练完成。报告已保存到 models\blind_test\training_report.json
{
  "backend": "sklearn_mlp_fallback",
  "sample_count": 940,
  "window_size": 60,
  "train_accuracy": 0.61,
  "val_accuracy": 0.58,
  "test_accuracy": 0.55,
  "baseline_accuracy": 0.52,
  ...
}
```

### 7.3 查看训练报告

```bash
# Windows
type models\blind_test\training_report.json

# Linux/macOS
cat models/blind_test/training_report.json
```

### 7.4 验证预测功能

训练完成后，在聊天界面输入：

```
预测 600519 涨跌
```

**预期**：返回 CNN/MLP 模型预测结果（非"简易版"）。

---

## 9. 历史盲测挑战

页面顶部展开“历史盲测挑战”面板：

互动演示顺序：

1. 随机抽取或指定一个隔离测试区间交易日。
2. 可直接判断，也可点击“查看 AI 情报”获取行情摘要、行情观察、事件摘要和不确定性。
3. 选择“我猜涨”或“我猜跌”，提交后答案不可修改。
4. 页面公开 MLP 行情模型的预测。
5. 点击“揭晓结果”，比较用户、MLP和昨日方向基线，并展示积分与连胜。

> AI 情报助手不提供涨跌答案，只整理提前保存的东方财富真实新闻和历史行情。
> 后端只允许 `发布时间 < 目标日 09:30` 的资讯进入提示词，并在挑战期间隔离
> 普通聊天中的股票查询，防止从其他入口获得答案。

1. 点击“随机抽取”，或在 `2024-09-26 ~ 2026-06-08` 内选择交易日后点击“指定日期”。
2. 系统只展示目标日前60个交易日，模型先给出方向与置信度。
3. 点击“揭晓结果”，图表补充目标日并显示实际涨跌幅。
4. 观察个人、全局成绩及昨日方向基线。
5. “重置个人成绩”会开启新一轮个人统计，全局历史保留。

答辩讲法：

> 普通预测无法现场验证。本系统使用真实历史日线并严格隔离测试区间，
> 让模型先预测、再揭晓真实行情。当前测试准确率为47.79%，
> 该功能用于审计模型能力，而不是包装模型必然有效。

CSV、模型和训练报告已随项目保存，答辩现场无需联网。

---

## 10. 常见问题与降级说明

### Q: 无网络时行情/K线失败怎么办？

系统使用腾讯免费 API，网络不可用时行情/K线/预测等依赖实时数据的功能返回降级提示。本地页面、规则引擎分流、已构建的 RAG 知识检索不受影响。

### Q: 无 LLM API Key 怎么办？

不配置 key 即可，系统自动使用内置规则引擎。13 种意图关键词匹配 + 直接工具调度，功能完整。

### Q: 无 TensorFlow 怎么办？

不装 TF 即可，训练和预测自动降级为 sklearn MLP。准确率可能略低于 CNN，但功能不受影响。

### Q: 无 sentence-transformers 怎么办？

不装即可，RAG 知识检索返回"知识库尚未初始化"，不影响其他功能。

### Q: RAG 知识库如何构建？

在 `data/knowledge/` 下放置 `.md` 文件（投资知识文档），首次知识检索时自动构建向量索引。

### Q: 模型预测为什么显示"简易版"？

运行上面的真实日线训练命令即可。训练后预测输出包含 MLP 置信度。

---

## 11. 测试验证

```bash
pytest -q
# 预期：87 passed
```

---

## 11. 免责声明

本系统仅供学习和研究使用。所有分析结果（包括技术指标、风险评估、模型预测、LLM 解读）均不构成投资建议。预测模型仅基于历史价格特征，不包含基本面、宏观、情绪等因子，回测结果不代表未来表现。股市有风险，投资需谨慎。
