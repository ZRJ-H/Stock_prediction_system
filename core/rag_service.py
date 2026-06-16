"""
RAG knowledge service.

The preferred backend uses sentence-transformers embeddings.  When that
optional dependency is not installed, the service falls back to a small local
TF-IDF style index so a freshly cloned project can still answer from
data/knowledge/*.md without downloading model files.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("stock_app.rag")

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge"
INDEX_PATH = BASE_DIR / "data" / "knowledge_index.json"

EMBEDDING_BACKEND = "sentence_transformers"
KEYWORD_BACKEND = "keyword_tfidf"
INDEX_VERSION = 2


def has_knowledge_sources() -> bool:
    """Return True when Markdown source files exist without loading a model."""
    return KNOWLEDGE_DIR.exists() and any(KNOWLEDGE_DIR.glob("*.md"))


class RAGService:
    """Markdown based knowledge retrieval with an embedding or keyword backend."""

    def __init__(self) -> None:
        self._chunks: List[str] = []
        self._titles: List[str] = []
        self._embeddings: Optional[np.ndarray] = None
        self._backend = EMBEDDING_BACKEND
        self._vocab: List[str] = []
        self._idf: List[float] = []
        self._ready = False

    def is_ready(self) -> bool:
        return self._ready

    @property
    def backend(self) -> str:
        return self._backend

    def initialize(self, force_rebuild: bool = False) -> bool:
        """Load an existing index or build one from data/knowledge/*.md."""
        if self._ready and not force_rebuild:
            return True
        try:
            if not force_rebuild and INDEX_PATH.exists() and self._load_index():
                return True
            return self._build_index()
        except Exception:
            logger.warning("RAG initialize failed", exc_info=True)
            return False

    def search(self, query: str, top_k: int = 3) -> List[Tuple[str, str, float]]:
        if not self._ready and not self.initialize():
            return []
        if self._embeddings is None or len(self._chunks) == 0:
            return []

        try:
            q_vec = self._encode_query(query)
            if q_vec is None:
                return []
            scores = np.dot(self._embeddings, q_vec.T).flatten()
            indices = np.argsort(scores)[::-1][:top_k]
            threshold = 0.2 if self._backend == EMBEDDING_BACKEND else 0.05

            results: List[Tuple[str, str, float]] = []
            for i in indices:
                if scores[i] > threshold:
                    results.append((self._titles[i], self._chunks[i], float(scores[i])))
            return results
        except Exception:
            logger.warning("RAG search failed", exc_info=True)
            return []

    def search_formatted(self, query: str, top_k: int = 3) -> str:
        results = self.search(query, top_k=top_k)
        if not results:
            return "知识库中未找到相关内容。"

        lines = ["从知识库检索到以下相关内容：\n"]
        for i, (title, chunk, score) in enumerate(results):
            chunk_short = chunk[:300].replace("\n", " ")
            lines.append(f"[{i + 1}] ({title}) 相关度 {score:.0%}")
            lines.append(f"    {chunk_short}...")
        return "\n".join(lines)

    def _embedder(self):
        from sentence_transformers import SentenceTransformer

        if not hasattr(RAGService, "_model"):
            RAGService._model = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
        return RAGService._model

    def _load_docs(self) -> List[Tuple[str, str]]:
        docs: List[Tuple[str, str]] = []
        if not KNOWLEDGE_DIR.exists():
            return docs
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = path.stem
            match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if match:
                title = match.group(1).strip()
            docs.append((title, text))
        return docs

    def _chunk_doc(self, title: str, text: str) -> List[Tuple[str, str]]:
        chunks: List[Tuple[str, str]] = []
        sections = re.split(r"\n(?=##\s)", text)
        for section in sections:
            heading = title
            heading_match = re.match(r"^##\s+(.+)", section)
            if heading_match:
                heading = f"{title} / {heading_match.group(1).strip()}"

            cleaned = re.sub(r"^#.*\n?", "", section, flags=re.MULTILINE).strip()
            cleaned = re.sub(r"-{3,}", "", cleaned)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            if len(cleaned) < 20:
                continue

            if len(cleaned) <= 800:
                chunks.append((heading, cleaned))
                continue

            buffer = ""
            for para in cleaned.split("\n\n"):
                if len(buffer) + len(para) < 800:
                    buffer += para + "\n\n"
                else:
                    if buffer.strip():
                        chunks.append((heading, buffer.strip()))
                    buffer = para + "\n\n"
            if buffer.strip():
                chunks.append((heading, buffer.strip()))
        return chunks

    def _build_index(self) -> bool:
        docs = self._load_docs()
        if not docs:
            return False

        all_chunks: List[Tuple[str, str]] = []
        for title, text in docs:
            all_chunks.extend(self._chunk_doc(title, text))
        if not all_chunks:
            return False

        self._titles = [title for title, _ in all_chunks]
        self._chunks = [chunk for _, chunk in all_chunks]

        try:
            model = self._embedder()
            self._embeddings = np.asarray(
                model.encode(self._chunks, normalize_embeddings=True)
            )
            self._backend = EMBEDDING_BACKEND
            self._vocab = []
            self._idf = []
        except Exception:
            logger.info(
                "sentence-transformers unavailable; using keyword RAG index",
                exc_info=True,
            )
            self._build_keyword_index()

        self._save_index()
        self._ready = True
        return True

    def _encode_query(self, query: str) -> Optional[np.ndarray]:
        if self._backend == KEYWORD_BACKEND:
            return self._keyword_vector(query)
        return np.asarray(self._embedder().encode([query], normalize_embeddings=True))

    def _build_keyword_index(self) -> None:
        tokenized = [self._tokenize(chunk) for chunk in self._chunks]
        doc_count = len(tokenized)
        document_frequency: Counter[str] = Counter()
        for tokens in tokenized:
            document_frequency.update(set(tokens))

        self._vocab = sorted(document_frequency)
        self._idf = [
            math.log((1 + doc_count) / (1 + document_frequency[token])) + 1
            for token in self._vocab
        ]

        vectors = [self._keyword_vector_from_tokens(tokens) for tokens in tokenized]
        self._embeddings = np.vstack(vectors) if vectors else np.empty((0, 0))
        self._backend = KEYWORD_BACKEND

    def _keyword_vector(self, text: str) -> Optional[np.ndarray]:
        if not self._vocab:
            return None
        return self._keyword_vector_from_tokens(self._tokenize(text)).reshape(1, -1)

    def _keyword_vector_from_tokens(self, tokens: List[str]) -> np.ndarray:
        vocab_index = {token: i for i, token in enumerate(self._vocab)}
        vec = np.zeros(len(self._vocab), dtype=float)
        counts = Counter(tokens)
        for token, count in counts.items():
            idx = vocab_index.get(token)
            if idx is not None:
                vec[idx] = count * self._idf[idx]

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        text = text.lower()
        tokens: List[str] = []

        for word in re.findall(r"[a-z0-9_]+", text):
            if len(word) >= 2:
                tokens.append(word)

        for run in re.findall(r"[\u4e00-\u9fff]+", text):
            tokens.extend(run)
            for size in (2, 3):
                tokens.extend(run[i:i + size] for i in range(0, len(run) - size + 1))

        return tokens

    def _save_index(self) -> None:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": INDEX_VERSION,
            "backend": self._backend,
            "titles": self._titles,
            "chunks": self._chunks,
            "embeddings": self._embeddings.tolist() if self._embeddings is not None else [],
            "vocab": self._vocab,
            "idf": self._idf,
        }
        INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _load_index(self) -> bool:
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            self._titles = data["titles"]
            self._chunks = data["chunks"]
            self._embeddings = np.asarray(data["embeddings"], dtype=float)
            self._backend = data.get("backend", EMBEDDING_BACKEND)
            self._vocab = data.get("vocab", [])
            self._idf = data.get("idf", [])
            self._ready = True
            return True
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.warning("RAG index is invalid; will rebuild", exc_info=True)
            return False
