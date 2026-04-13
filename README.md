# 股票预测系统（核心功能开发版）

本项目基于深度学习与大模型解释，实现了一个可运行的股票走势预测闭环：

- 上传股票历史 `CSV` 数据
- 模型输出下一时段“涨/跌”预测与概率
- 大模型（或本地回退）生成解释文本与风险提示

---

## 1. 功能说明

当前已完成“核心功能开发”阶段的主要内容：

- 数据预处理：列校验、归一化、时间窗口构造
- 预测模块：训练/加载/推理统一接口
- 大模型解释：提示词封装 + API调用 + 无Key回退
- Web界面：文件上传、预测结果展示、解释文本展示

---

## 2. 环境要求

- Python 3.9+
- Windows / Linux / macOS 均可

安装依赖：

```bash
pip install -r requirements.txt
```

> 说明：如果本地已安装 TensorFlow，系统优先使用 CNN 模型；若未安装，将自动回退为 `sklearn` 的 MLP 模型以保证流程可运行。

---

## 3. 快速开始

在项目目录 `cnn_stock` 下执行：

```bash
python app.py
```

启动后访问：

`http://127.0.0.1:5000`

首次启动会自动加载已有模型，若模型不存在则会基于 `dataset/tt.csv` 进行初始化训练。

---

## 4. 大模型配置（可选）

如果你要启用真实大模型 API，可设置以下环境变量：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`（可选，默认 `https://api.openai.com/v1`）
- `OPENAI_MODEL`（可选，默认 `gpt-4o-mini`）

Windows PowerShell 示例：

```powershell
$env:OPENAI_API_KEY="你的key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4o-mini"
python app.py
```

若未配置或调用失败，系统会自动使用本地解释文案，不影响演示。

---

## 5. 输入数据格式

上传 CSV 至少应包含以下列（区分大小写）：

- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `label`

其中：

- `label > 0` 视为“涨”
- `label <= 0` 视为“跌”

数据行数建议不少于 100 行。

---

## 6. 项目结构

```text
cnn_stock/
├─ app.py                    # Flask 入口
├─ core/
│  ├─ data_pipeline.py       # 数据预处理与窗口构造
│  ├─ model_service.py       # 训练/加载/预测服务
│  └─ llm_service.py         # 大模型解释服务
├─ templates/
│  └─ index.html             # 前端页面
├─ dataset/
│  └─ tt.csv                 # 基础训练数据
├─ models/                   # 训练后自动生成
└─ requirements.txt
```

---

## 7. 后续可扩展方向

- 接入 K 线图与预测点可视化（第3月目标）
- 增加历史预测记录与管理接口
- 引入更丰富的技术指标特征（如 MACD、RSI）
- 优化模型训练与推理速度

