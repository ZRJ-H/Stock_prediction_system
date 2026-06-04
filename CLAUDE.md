# Claude Code Project Guide

基于 Flask 的 A 股股票分析助手。Web 聊天界面 + 行情/技术指标/基本面/新闻/CNN预测/RAG知识库 + LLM/规则双模式。

## 技术栈

| 层 | 技术 |
|----|------|
| Web | Flask |
| 前端 | 原生 HTML/CSS/JS + ECharts (CDN) |
| 深度学习 | TensorFlow CNN / sklearn MLP (降级) |
| 向量检索 | sentence-transformers + NumPy |
| 数据源 | 腾讯免费 API / AKShare (可选) |
| LLM | OpenAI 兼容协议 (零 SDK 依赖) |

## 启动与测试

```powershell
# 启动
python app.py                    # http://127.0.0.1:5000

# 测试
pytest -q                        # 预期 69 passed

# 模型训练
python train_model.py --data dataset/tt.csv --model-dir models

# 搜索文件（排除缓存和运行产物；但允许搜索 .claude/skills）
rg --files -g '!**/.claude/**' -g '!**/.pytest_cache/**' -g '!**/__pycache__/**' -g '!**/.cache/**' -g '!**/cache/**'
rg --files .claude/skills
```

## 关键文件

```text
app.py / train_model.py          — Flask 入口 / 训练 CLI
templates/index.html             — 前端 Chat UI
core/agent.py                    — 意图识别、LLM/规则双模式调度
core/tools.py                    — 18 个工具注册/分组/执行
core/market_data.py              — 腾讯行情/K线/搜索
core/indicators.py               — NumPy 技术指标 (MA/MACD/RSI/BOLL/KDJ)
core/model_service.py            — CNN/MLP 模型训练与预测
core/data_pipeline.py            — 滑动窗口 + 归一化 + 时序切分
core/llm_service.py              — OpenAI 兼容协议 (urllib, 零 SDK)
core/rag_service.py              — NumPy 向量检索知识库
core/memory.py                   — session 记忆 + 偏好持久化
core/skills/                     — 6 个 Skill (技术/基本面/风险/选股/新闻/综合)
tests/test_core.py               — 回归测试
```

## 禁止事项

**禁止读取：** `.claude/`（除 `.claude/skills/*/SKILL.md`）、`__pycache__/`、`.pytest_cache/`、`.cache/`、`cache/`、运行产物

**禁止操作：** `git reset --hard`、`git checkout --`（回滚文件）、删除用户文件或运行产物

**禁止提交：** API key、token、密钥、账号密码

**禁止行为：**
- 依赖真实外部网络完成测试（必须 mock）
- `/health` 加载 embedding 模型或构建 RAG 索引或请求 LLM
- 把异常堆栈暴露给前端用户
- 编造行情数据（LLM 必须通过工具获取真实数据）

## 审查清单

每次改完代码后，按以下顺序自检：

### 安全
- `session_id` 是否经过校验？文件路径是否可能被用户输入控制？
- Flask debug 是否默认关闭？API key 是否只从环境变量读取？
- 前端是否使用 `textContent`（非 `innerHTML`）渲染用户内容？

### 稳定性
- 外部接口失败是否有明确降级提示？网络超时是否设置？
- RAG 是否阻塞 `/health`？模型不存在时是否降级？
- 综合分析是否能容忍部分模块失败？

### 测试
- 新增逻辑是否有测试？是否 mock 外部网络？
- 是否避免写入真实 `data/memory`？`pytest -q` 是否通过？

### 交付
- README 是否同步？生成文件是否被 `.gitignore` 处理？

## 自主执行边界

**可自主执行：** 阅读非禁止目录源码、修改源码、新增测试、运行 pytest、更新 README/文档

**需暂停询问：** 安装新依赖、联网下载模型或数据、删除文件、重置 Git 历史、改变项目核心方向 (如 Flask → FastAPI)

## 进度记录

日常进度记录在 [`docs/PROGRESS.md`](docs/PROGRESS.md)，里程碑级记录在 [`REVIEW_HISTORY.md`](REVIEW_HISTORY.md)，路线图在 [`CC_AUTONOMOUS_ROADMAP.md`](CC_AUTONOMOUS_ROADMAP.md)。

阶段完成后，使用 `.claude/skills/progress-updater/SKILL.md` 追加进度。
