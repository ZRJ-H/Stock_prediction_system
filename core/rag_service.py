"""
RAG 知识库服务（RAG Service）
=============================
基于 FAISS + sentence-transformers 的本地投资知识检索：

文档管理：
  - 源文件：data/knowledge/*.md（Markdown 格式）
  - 分段策略：按 ## 二级标题切分，超长段落按段落再切（max 800 字符）
  - 向量化：paraphrase-multilingual-MiniLM-L12-v2（中英文兼容）

检索流程：
  1. 用户查询 → 向量化
  2. 与知识库做余弦相似度匹配（归一化向量点积）
  3. 返回 top_k 个相关片段 + 相似度得分

持久化：
  - 构建后的索引缓存到 data/knowledge_index.json
  - 下次启动直接加载，避免重复 embedding
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# 路径常量
BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge"    # Markdown 源文件目录
INDEX_PATH = BASE_DIR / "data" / "knowledge_index.json"  # 向量索引缓存


class RAGService:
    """RAG 知识库服务类。

    采用懒加载 + 缓存策略：
      - 首次使用时调用 initialize() 构建/加载索引
      - 索引持久化到 JSON，避免重复 embedding
      - 类级别缓存 embedding 模型，避免重复加载大模型
    """

    def __init__(self) -> None:
        self._chunks: List[str] = []             # 文本块
        self._titles: List[str] = []             # 每块对应的标题
        self._embeddings: Optional[np.ndarray] = None  # 向量矩阵 (N, dim)
        self._ready = False                       # 就绪标志

    def is_ready(self) -> bool:
        """知识库是否已加载就绪。"""
        return self._ready

    def initialize(self, force_rebuild: bool = False) -> bool:
        """初始化知识库：加载已有索引或重新构建。

        Args:
            force_rebuild: 是否强制重建索引（忽略缓存）

        Returns:
            True 初始化成功，False 失败
        """
        if self._ready and not force_rebuild:
            return True
        try:
            if not force_rebuild and INDEX_PATH.exists():
                return self._load_index()
            return self._build_index()
        except Exception:
            return False

    def search(self, query: str, top_k: int = 3) -> List[Tuple[str, str, float]]:
        """检索与查询最相关的知识片段。

        Args:
            query: 用户查询文本
            top_k: 返回片段数

        Returns:
            [(标题, 文本片段, 相似度得分), ...] 列表
        """
        if not self._ready:
            if not self.initialize():
                return []
        if self._embeddings is None or len(self._chunks) == 0:
            return []

        try:
            # 编码查询向量（归一化后点积 = 余弦相似度）
            q_vec = self._embedder().encode([query], normalize_embeddings=True)
            scores = np.dot(self._embeddings, q_vec.T).flatten()
            # 按相似度降序排列
            indices = np.argsort(scores)[::-1][:top_k]
            results: List[Tuple[str, str, float]] = []
            for i in indices:
                # 过滤低相关度噪声（阈值 0.2）
                if scores[i] > 0.2:
                    results.append((self._titles[i], self._chunks[i], float(scores[i])))
            return results
        except Exception:
            return []

    def search_formatted(self, query: str, top_k: int = 3) -> str:
        """检索并格式化为可读文本（供 Chat UI 展示）。"""
        results = self.search(query, top_k=top_k)
        if not results:
            return "知识库中未找到相关内容。"
        lines = ["从知识库检索到以下相关内容：\n"]
        for i, (title, chunk, score) in enumerate(results):
            chunk_short = chunk[:300].replace("\n", " ")
            lines.append(f"[{i + 1}] ({title}) 相关度 {score:.0%}")
            lines.append(f"    {chunk_short}...")
        return "\n".join(lines)

    # ── 私有方法 ──────────────────────────────────────────

    def _embedder(self):
        """获取/缓存 sentence-transformers 模型（类级别单例）。"""
        from sentence_transformers import SentenceTransformer

        if not hasattr(RAGService, "_model"):
            RAGService._model = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
        return RAGService._model

    def _load_docs(self) -> List[Tuple[str, str]]:
        """加载 data/knowledge/ 下的所有 .md 文件。
        Returns:
            [(文档标题, 全文文本), ...]
        """
        docs: List[Tuple[str, str]] = []
        if not KNOWLEDGE_DIR.exists():
            return docs
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            # 标题优先用 # 一级标题，否则用文件名
            title = path.stem
            m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if m:
                title = m.group(1).strip()
            docs.append((title, text))
        return docs

    def _chunk_doc(self, title: str, text: str) -> List[Tuple[str, str]]:
        """将单篇文档按 ## 二级标题切分为多个片段。

        切分策略：
          1. 按 ## 标题分割
          2. 每个片段去掉 Markdown 标记和多余空白
          3. 短于 20 字符的片段丢弃
          4. 长于 800 字符的片段按自然段再切

        Returns:
            [(片段标题, 片段文本), ...]
        """
        chunks: List[Tuple[str, str]] = []
        # 按 ## 二级标题分割（保留分隔符）
        sections = re.split(r"\n(?=##\s)", text)
        for section in sections:
            # 提取当前 section 的标题
            heading = title
            hm = re.match(r"^##\s+(.+)", section)
            if hm:
                heading = f"{title} / {hm.group(1).strip()}"

            # 清理 Markdown 标记和多余空白
            cleaned = re.sub(r"^#.*\n?", "", section, flags=re.MULTILINE).strip()
            cleaned = re.sub(r"-{3,}", "", cleaned)       # 去掉水平分割线
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # 压缩多余空行

            if len(cleaned) < 20:
                continue

            # 过长片段按段落再切（目标：每块 ≤ 800 字符）
            if len(cleaned) > 800:
                paras = cleaned.split("\n\n")
                buffer = ""
                for p in paras:
                    if len(buffer) + len(p) < 800:
                        buffer += p + "\n\n"
                    else:
                        if buffer.strip():
                            chunks.append((heading, buffer.strip()))
                        buffer = p + "\n\n"
                if buffer.strip():
                    chunks.append((heading, buffer.strip()))
            else:
                chunks.append((heading, cleaned))
        return chunks

    def _build_index(self) -> bool:
        """构建向量索引：加载文档 → 切分 → 向量化 → 持久化。"""
        docs = self._load_docs()
        if not docs:
            return False

        # 所有文档统一切分
        all_chunks: List[Tuple[str, str]] = []
        for title, text in docs:
            all_chunks.extend(self._chunk_doc(title, text))
        if not all_chunks:
            return False

        self._titles = [t for t, _ in all_chunks]
        self._chunks = [c for _, c in all_chunks]

        # 向量化（归一化以支持余弦相似度）
        model = self._embedder()
        self._embeddings = model.encode(self._chunks, normalize_embeddings=True)

        # 持久化到磁盘
        self._save_index()
        self._ready = True
        return True

    def _save_index(self) -> None:
        """将向量索引序列化到 JSON 文件。"""
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "titles": self._titles,
            "chunks": self._chunks,
            "embeddings": self._embeddings.tolist() if self._embeddings is not None else [],
        }
        INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _load_index(self) -> bool:
        """从 JSON 文件反序列化向量索引。"""
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            self._titles = data["titles"]
            self._chunks = data["chunks"]
            self._embeddings = np.array(data["embeddings"])
            self._ready = True
            return True
        except (json.JSONDecodeError, KeyError):
            return False
