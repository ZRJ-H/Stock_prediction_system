"""RAG service: load markdown docs, chunk, embed, search. Lazy init to avoid heavy model loading at import."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge"
INDEX_PATH = BASE_DIR / "data" / "knowledge_index.json"


class RAGService:
    def __init__(self) -> None:
        self._chunks: List[str] = []
        self._titles: List[str] = []
        self._embeddings: Optional[np.ndarray] = None
        self._ready = False

    def is_ready(self) -> bool:
        return self._ready

    def initialize(self, force_rebuild: bool = False) -> bool:
        """Load docs, chunk, embed. Returns True if successful."""
        if self._ready and not force_rebuild:
            return True
        try:
            if not force_rebuild and INDEX_PATH.exists():
                return self._load_index()
            return self._build_index()
        except Exception:
            return False

    def search(self, query: str, top_k: int = 3) -> List[Tuple[str, str, float]]:
        """Return list of (title, chunk_text, score)."""
        if not self._ready:
            if not self.initialize():
                return []
        if self._embeddings is None or len(self._chunks) == 0:
            return []
        try:
            q_vec = self._embedder().encode([query], normalize_embeddings=True)
            scores = np.dot(self._embeddings, q_vec.T).flatten()
            indices = np.argsort(scores)[::-1][:top_k]
            results: List[Tuple[str, str, float]] = []
            for i in indices:
                if scores[i] > 0.2:
                    results.append((self._titles[i], self._chunks[i], float(scores[i])))
            return results
        except Exception:
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

    # ── private ──────────────────────────────────────────

    def _embedder(self):
        from sentence_transformers import SentenceTransformer
        # Cache on class to avoid reload
        if not hasattr(RAGService, "_model"):
            RAGService._model = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
        return RAGService._model

    def _load_docs(self) -> List[Tuple[str, str]]:
        """Return list of (filename_title, full_text)."""
        docs: List[Tuple[str, str]] = []
        if not KNOWLEDGE_DIR.exists():
            return docs
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            # Title from first # heading or filename
            title = path.stem
            m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if m:
                title = m.group(1).strip()
            docs.append((title, text))
        return docs

    def _chunk_doc(self, title: str, text: str) -> List[Tuple[str, str]]:
        """Split a doc into chunks by ## headings. Return (title, chunk_text) pairs."""
        chunks: List[Tuple[str, str]] = []
        # Split on ##  headings
        sections = re.split(r"\n(?=##\s)", text)
        for section in sections:
            # Grab section heading
            heading = title
            hm = re.match(r"^##\s+(.+)", section)
            if hm:
                heading = f"{title} / {hm.group(1).strip()}"
            cleaned = re.sub(r"^#.*\n?", "", section, flags=re.MULTILINE).strip()
            cleaned = re.sub(r"-{3,}", "", cleaned)  # Remove horizontal rules
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # Normalize whitespace
            if len(cleaned) < 20:
                continue
            # If still too long, split by paragraphs
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
        docs = self._load_docs()
        if not docs:
            return False
        all_chunks: List[Tuple[str, str]] = []
        for title, text in docs:
            all_chunks.extend(self._chunk_doc(title, text))
        if not all_chunks:
            return False

        self._titles = [t for t, _ in all_chunks]
        self._chunks = [c for _, c in all_chunks]

        model = self._embedder()
        self._embeddings = model.encode(self._chunks, normalize_embeddings=True)

        # Persist
        self._save_index()
        self._ready = True
        return True

    def _save_index(self) -> None:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "titles": self._titles,
            "chunks": self._chunks,
            "embeddings": self._embeddings.tolist() if self._embeddings is not None else [],
        }
        INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _load_index(self) -> bool:
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            self._titles = data["titles"]
            self._chunks = data["chunks"]
            self._embeddings = np.array(data["embeddings"])
            self._ready = True
            return True
        except (json.JSONDecodeError, KeyError):
            return False
