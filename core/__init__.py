"""
核心服务模块（Core Service Modules）
=====================================
本包包含股票预测系统的所有核心业务逻辑：
  - agent          : 对话 Agent，负责意图分类与工具调度
  - llm_service    : LLM 调用服务，封装 OpenAI 兼容 API
  - market_data    : 行情数据层，腾讯 API → StockQuote / KlineBar
  - data_pipeline  : 数据预处理管道，滑动窗口 + 归一化
  - indicators     : 技术指标计算（MA/MACD/RSI/BOLL/KDJ/K线形态）
  - model_service  : CNN/MLP 模型训练与推理服务
  - memory         : 会话记忆（30min TTL）+ 用户偏好持久化
  - rag_service    : RAG 知识库，Markdown 文档 → 向量检索
  - fundamentals   : 基本面/财报数据获取（AKShare）
  - news           : 新闻舆情获取（腾讯/东方财富）
  - screener       : 选股筛选引擎，5 种量化策略
  - tools          : 工具注册表，统一管理 Agent 可调用工具
"""
