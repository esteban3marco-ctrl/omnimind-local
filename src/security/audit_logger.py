"""Append-only audit logger with SHA-256 hash chain."""
import json, hashlib, logging
from pathlib import Path
from datetime import datetime
logger = logging.getLogger("omnimind.audit")

class AuditLogger:
    def __init__(self, config):
        self.path = Path(config.get("audit", {}).get("path", "./data/logs/audit"))
        self.path.mkdir(parents=True, exist_ok=True)
        self.last_hash = "0" * 64

    def log(self, event_type: str, data: dict):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data,
            "prev_hash": self.last_hash,
        }
        entry_str = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        entry["hash"] = hashlib.sha256(entry_str.encode()).hexdigest()
        self.last_hash = entry["hash"]
        with open(self.path / "audit.jsonl", "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
