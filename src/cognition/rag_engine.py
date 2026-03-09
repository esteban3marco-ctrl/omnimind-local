"""
OMNIMIND LOCAL — Hybrid RAG Engine
═══════════════════════════════════

True hybrid retrieval: Vector Search (ChromaDB) + BM25 keyword search,
fused via Reciprocal Rank Fusion (RRF) and optionally reranked with a
cross-encoder model for maximum recall/precision.

Why hybrid? Each method has different strengths:
- Vector search: finds semantically similar content ("talk to me about my car")
- BM25: finds exact keyword matches ("OBD-II error code P0420")
- RRF fusion: gets the best of both without needing yet another model

Pipeline:
  Query → [Vector Search ‖ BM25] → RRF Fusion → (Optional Cross-Encoder Rerank) → Top-K
"""
import asyncio
import logging
import math
from typing import Optional

logger = logging.getLogger("omnimind.rag")


# ─────────────────────────────────
# Constants
# ─────────────────────────────────
RRF_K = 60              # RRF constant (Cormack et al. 2009)
DEFAULT_TOP_K = 5
RERANK_TOP_N = 20       # Retrieve more candidates before reranking


class RAGEngine:
    """
    Hybrid Retrieval-Augmented Generation engine.
    Combines ChromaDB vector search with BM25 keyword retrieval,
    fused and optionally reranked for high-precision context injection.
    """

    def __init__(self, config, bus):
        self.bus = bus
        self.config = config.get("rag", {})
        self._vector_store = None   # Injected after VectorStore starts
        self._bm25 = None           # Built lazily from stored documents
        self._reranker = None       # Optional cross-encoder (flashrank / sentence-transformers)
        self._corpus: list[str] = []        # Raw documents for BM25
        self._corpus_ids: list[str] = []    # Corresponding ids
        self._use_reranker = self.config.get("use_reranker", False)

    # ─────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────

    async def start(self):
        logger.info("RAG engine initialized (hybrid: vector + BM25 + RRF)")

    def attach_vector_store(self, vector_store):
        """Inject the shared VectorStore after it has started."""
        self._vector_store = vector_store
        logger.info("RAG engine: VectorStore attached")
        # Warm up BM25 with existing documents
        asyncio.create_task(self._warm_up_bm25())

    async def _warm_up_bm25(self):
        """Load existing documents from ChromaDB into BM25 index."""
        try:
            if not self._vector_store or not self._vector_store.collection:
                return
            all_docs = self._vector_store.collection.get(
                include=["documents"], limit=5000
            )
            if all_docs and all_docs.get("documents"):
                self._corpus = all_docs["documents"]
                self._corpus_ids = all_docs.get("ids", [])
                self._bm25 = self._build_bm25(self._corpus)
                logger.info(f"BM25 index warmed up with {len(self._corpus)} documents")
        except Exception as e:
            logger.warning(f"BM25 warm-up failed (BM25 disabled): {e}")

    def _build_bm25(self, corpus: list[str]):
        """Build a BM25Okapi index from a list of document strings."""
        try:
            from rank_bm25 import BM25Okapi
            tokenized = [doc.lower().split() for doc in corpus]
            return BM25Okapi(tokenized)
        except ImportError:
            logger.warning("rank_bm25 not installed. Install with: pip install rank-bm25")
            return None
        except Exception as e:
            logger.warning(f"BM25 build error: {e}")
            return None

    async def _load_reranker(self):
        """Lazy-load the cross-encoder reranker if enabled."""
        if self._reranker or not self._use_reranker:
            return
        try:
            from sentence_transformers import CrossEncoder
            model_name = self.config.get("reranker_model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
            self._reranker = CrossEncoder(model_name)
            logger.info(f"Cross-encoder reranker loaded: {model_name}")
        except ImportError:
            logger.warning("sentence-transformers not installed. Reranker disabled.")
        except Exception as e:
            logger.warning(f"Reranker load failed: {e}")

    # ─────────────────────────────────
    # Main Retrieval
    # ─────────────────────────────────

    async def retrieve(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
        """
        Hybrid retrieval with RRF fusion.
        Returns a list of {"content": str, "metadata": dict, "score": float}
        sorted by relevance (highest first).
        """
        if not query:
            return []

        # Run both retrievals concurrently
        vec_results, bm25_results = await asyncio.gather(
            self._vector_retrieve(query, top_k=top_k * 2),
            self._bm25_retrieve(query, top_k=top_k * 2),
        )

        # Fuse rankings with RRF
        fused = self._rrf_fusion(vec_results, bm25_results)

        # Optionally rerank with cross-encoder
        candidates = fused[:RERANK_TOP_N]
        if self._use_reranker and candidates:
            await self._load_reranker()
            if self._reranker:
                candidates = self._rerank(query, candidates)

        result = candidates[:top_k]

        if result:
            logger.debug(
                f"RAG retrieved {len(result)} docs for: '{query[:60]}' "
                f"(vector={len(vec_results)}, bm25={len(bm25_results)})"
            )

        return result

    # ─────────────────────────────────
    # Vector Search
    # ─────────────────────────────────

    async def _vector_retrieve(self, query: str, top_k: int) -> list[dict]:
        """ChromaDB cosine similarity search (async wrapper)."""
        if not self._vector_store:
            return []
        try:
            raw = self._vector_store.search(query, top_k=top_k)
            return [
                {
                    "content": r.get("content", ""),
                    "metadata": r.get("metadata", {}),
                    "source": "vector",
                }
                for r in raw if r.get("content")
            ]
        except Exception as e:
            logger.warning(f"Vector retrieval error: {e}")
            return []

    # ─────────────────────────────────
    # BM25 Search
    # ─────────────────────────────────

    async def _bm25_retrieve(self, query: str, top_k: int) -> list[dict]:
        """BM25Okapi keyword search over the in-memory corpus."""
        if not self._bm25 or not self._corpus:
            return []
        try:
            tokenized_query = query.lower().split()
            scores = self._bm25.get_scores(tokenized_query)

            # Get top_k indices by score
            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

            return [
                {
                    "content": self._corpus[i],
                    "metadata": {"id": self._corpus_ids[i] if i < len(self._corpus_ids) else str(i)},
                    "source": "bm25",
                    "bm25_score": float(scores[i]),
                }
                for i in top_indices
                if scores[i] > 0  # Filter zero-score results (no keyword match at all)
            ]
        except Exception as e:
            logger.warning(f"BM25 retrieval error: {e}")
            return []

    # ─────────────────────────────────
    # RRF Fusion
    # ─────────────────────────────────

    def _rrf_fusion(self, list_a: list[dict], list_b: list[dict]) -> list[dict]:
        """
        Reciprocal Rank Fusion.
        Score = Σ 1 / (k + rank_i) for each list the document appears in.
        """
        scores: dict[str, float] = {}
        docs: dict[str, dict] = {}

        for rank, doc in enumerate(list_a, start=1):
            key = doc["content"][:200]  # Use content prefix as dedup key
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            docs[key] = doc

        for rank, doc in enumerate(list_b, start=1):
            key = doc["content"][:200]
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            if key not in docs:
                docs[key] = doc

        # Sort by fused RRF score
        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
        return [
            {**docs[k], "rrf_score": round(scores[k], 6)}
            for k in sorted_keys
        ]

    # ─────────────────────────────────
    # Cross-Encoder Reranker
    # ─────────────────────────────────

    def _rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """Rerank candidates using a cross-encoder for high-precision ordering."""
        try:
            pairs = [(query, c["content"]) for c in candidates]
            cross_scores = self._reranker.predict(pairs)
            for i, doc in enumerate(candidates):
                doc["rerank_score"] = float(cross_scores[i])
            return sorted(candidates, key=lambda d: d.get("rerank_score", 0), reverse=True)
        except Exception as e:
            logger.warning(f"Reranker error: {e}")
            return candidates  # Fall back to RRF order

    # ─────────────────────────────────
    # Document Ingestion
    # ─────────────────────────────────

    async def add(self, text: str, metadata: dict = None, doc_id: str = None):
        """
        Add a document to both ChromaDB and BM25 index.
        Call this when saving a new memory, conversation turn, or personal fact.
        """
        if self._vector_store:
            self._vector_store.add(text, metadata=metadata, doc_id=doc_id)

        # Update BM25 incrementally
        if self._bm25 is not None and text not in self._corpus:
            self._corpus.append(text)
            if doc_id:
                self._corpus_ids.append(doc_id)
            self._bm25 = self._build_bm25(self._corpus)

    async def stop(self):
        self._bm25 = None
        self._reranker = None
