"""ChromaDB vector store for semantic memory."""
import logging
logger = logging.getLogger("omnimind.vectors")

class VectorStore:
    def __init__(self, config):
        self.persist_dir = config.get("services", {}).get("vector_db", {}).get("persist_directory", "./data/memory/vectors")
        self.client = None
        self.collection = None

    async def start(self):
        try:
            import chromadb
            self.client = chromadb.PersistentClient(path=self.persist_dir)
            self.collection = self.client.get_or_create_collection("omnimind_memory")
            logger.info(f"Vector store ready ({self.collection.count()} docs)")
        except Exception as e:
            logger.warning(f"Vector store init failed: {e}")

    def add(self, text: str, metadata: dict = None, doc_id: str = None):
        if self.collection:
            self.collection.add(documents=[text], metadatas=[metadata or {}], ids=[doc_id or str(hash(text))])

    def search(self, query: str, top_k: int = 5) -> list:
        if not self.collection:
            return []
        results = self.collection.query(query_texts=[query], n_results=top_k)
        return [{"content": doc, "metadata": meta} for doc, meta in zip(results["documents"][0], results["metadatas"][0])]

    async def stop(self):
        pass
