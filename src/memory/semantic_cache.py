"""Semantic cache — cache LLM responses by query similarity."""
import logging
logger = logging.getLogger("omnimind.cache")

class SemanticCache:
    def __init__(self, vector_store, similarity_threshold: float = 0.95):
        self.store = vector_store
        self.threshold = similarity_threshold

    def get(self, query: str):
        results = self.store.search(query, top_k=1)
        if results and results[0].get("metadata", {}).get("type") == "cache":
            return results[0].get("metadata", {}).get("response")
        return None

    def put(self, query: str, response: str):
        self.store.add(query, metadata={"type": "cache", "response": response})
