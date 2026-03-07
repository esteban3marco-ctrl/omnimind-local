"""Collects explicit and implicit feedback for continual learning."""
import json, logging
from pathlib import Path
from datetime import datetime
logger = logging.getLogger("omnimind.feedback")

class FeedbackCollector:
    def __init__(self, config, bus):
        self.bus = bus
        self.path = Path(config.get("paths", {}).get("data", "./data")) / "learning" / "feedback"
        self.path.mkdir(parents=True, exist_ok=True)

    async def start(self):
        logger.info("Feedback collector ready")

    def log_feedback(self, query: str, response: str, signal: str, score: float = None):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "response": response,
            "signal": signal,
            "score": score,
        }
        with open(self.path / "feedback.jsonl", "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def stop(self):
        pass
