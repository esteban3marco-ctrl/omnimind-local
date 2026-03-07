"""Context engine — tracks environment state (home/car/work, time, calendar)."""
import asyncio, logging
from datetime import datetime
logger = logging.getLogger("omnimind.context")

class ContextEngine:
    def __init__(self, config, bus):
        self.bus = bus
        self.state = {
            "location": "home",
            "time_of_day": "morning",
            "last_interaction": None,
        }

    async def start(self):
        asyncio.create_task(self._update_loop())

    async def _update_loop(self):
        while True:
            now = datetime.now()
            hour = now.hour
            if 6 <= hour < 9: self.state["time_of_day"] = "morning"
            elif 9 <= hour < 14: self.state["time_of_day"] = "work"
            elif 14 <= hour < 16: self.state["time_of_day"] = "lunch"
            elif 16 <= hour < 20: self.state["time_of_day"] = "evening"
            else: self.state["time_of_day"] = "night"
            await asyncio.sleep(60)

    def get_context(self) -> dict:
        return {**self.state, "timestamp": datetime.now().isoformat()}

    async def stop(self):
        pass
