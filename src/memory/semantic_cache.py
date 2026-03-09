"""
Semantic Cache — skips the LLM for semantically similar repeated queries.

How it works:
1. When Leo answers a query, the (query, response) pair is stored in a
   dedicated ChromaDB collection using the same vector embeddings.
2. On the next query, before hitting the 72B LLM, we search this cache
   collection for a similar past query.
3. If cosine similarity >= threshold (default 0.95), we return the cached
   response instantly — no GPU inference required.
4. TTL: cached entries expire after `ttl_hours` to prevent stale answers
   (e.g., "what time is it?" should never be cached forever).

Expected hit rate for a typical home assistant: 25-40% of queries.
This means 25-40% fewer LLM calls, saving significant GPU time.
"""
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger("omnimind.cache")

DEFAULT_TTL_HOURS = 24      # Entries older than this are ignored
DEFAULT_THRESHOLD = 0.92    # Cosine similarity threshold for cache hit
CACHE_COLLECTION = "omnimind_semantic_cache"


class SemanticCache:
    def __init__(self, vector_store, similarity_threshold: float = DEFAULT_THRESHOLD,
                 ttl_hours: float = DEFAULT_TTL_HOURS):
        self._store = vector_store       # VectorStore instance (ChromaDB)
        self.threshold = similarity_threshold
        self.ttl_seconds = ttl_hours * 3600
        self._hits = 0
        self._misses = 0
        self._collection = None          # Dedicated cache collection
        self._ready = False

    def setup(self):
        """
        Initialize a dedicated ChromaDB collection for the cache.
        Called once the VectorStore is connected (separate from main memory).
        """
        try:
            if self._store.client:
                self._collection = self._store.client.get_or_create_collection(
                    CACHE_COLLECTION,
                    metadata={"hnsw:space": "cosine"}  # Use cosine similarity
                )
                self._ready = True
                count = self._collection.count()
                logger.info(f"Semantic cache ready ({count} cached entries, "
                            f"threshold={self.threshold}, TTL={self.ttl_seconds/3600:.0f}h)")
        except Exception as e:
            logger.warning(f"Semantic cache setup failed (will not cache): {e}")

    def get(self, query: str) -> str | None:
        """
        Look up a cached response for a semantically similar query.
        Returns the cached response string, or None on miss.
        """
        if not self._ready or not self._collection:
            return None

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=1,
                include=["documents", "metadatas", "distances"]
            )

            if not results["documents"] or not results["documents"][0]:
                self._misses += 1
                return None

            distance = results["distances"][0][0]    # ChromaDB cosine distance (0=identical, 2=opposite)
            similarity = 1.0 - (distance / 2.0)     # Convert to [0, 1] similarity score
            metadata = results["metadatas"][0][0]

            # Check TTL
            stored_at = metadata.get("stored_at", 0)
            age_seconds = time.time() - stored_at
            if age_seconds > self.ttl_seconds:
                logger.debug(f"[cache STALE] Entry expired ({age_seconds/3600:.1f}h old)")
                self._misses += 1
                return None

            # Check similarity threshold
            if similarity >= self.threshold:
                cached_response = metadata.get("response")
                self._hits += 1
                hit_rate = self._hits / max(1, self._hits + self._misses) * 100
                logger.info(
                    f"[cache HIT] similarity={similarity:.3f} | "
                    f"hit_rate={hit_rate:.1f}% ({self._hits}/{self._hits + self._misses})"
                )
                return cached_response

            self._misses += 1
            return None

        except Exception as e:
            logger.warning(f"Cache lookup error: {e}")
            self._misses += 1
            return None

    def put(self, query: str, response: str):
        """
        Store a (query, response) pair in the semantic cache.
        Uses a deterministic ID based on query hash for deduplication.
        """
        if not self._ready or not self._collection or not query or not response:
            return

        try:
            entry_id = f"cache_{abs(hash(query))}"
            self._collection.upsert(
                ids=[entry_id],
                documents=[query],
                metadatas=[{
                    "response": response,
                    "stored_at": time.time(),
                    "stored_at_human": datetime.now().isoformat(),
                    "type": "semantic_cache",
                }]
            )
        except Exception as e:
            logger.warning(f"Cache store error: {e}")

    def invalidate_old_entries(self):
        """
        Purge all entries older than TTL.
        Call this periodically (e.g., from the nightly learning scheduler).
        """
        if not self._ready or not self._collection:
            return

        try:
            all_entries = self._collection.get(include=["metadatas"])
            expired_ids = [
                entry_id
                for entry_id, meta in zip(all_entries["ids"], all_entries["metadatas"])
                if time.time() - meta.get("stored_at", 0) > self.ttl_seconds
            ]
            if expired_ids:
                self._collection.delete(ids=expired_ids)
                logger.info(f"Cache purged {len(expired_ids)} expired entries")
        except Exception as e:
            logger.warning(f"Cache purge error: {e}")

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self._hits / max(1, total) * 100:.1f}%",
            "total_queries": total,
            "cached_entries": self._collection.count() if self._collection else 0,
        }
