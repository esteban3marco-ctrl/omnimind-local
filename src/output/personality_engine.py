"""Personality engine — adapts Leo's tone based on context."""
import logging
logger = logging.getLogger("omnimind.personality")

class PersonalityEngine:
    def __init__(self, config):
        self.params = config.get("leo", {}).get("llm_params", {})

    def get_params(self, context: dict) -> dict:
        time = context.get("time_of_day", "work")
        if time in ("morning", "night"):
            return self.params.get("casual", {})
        if context.get("location") == "car":
            return self.params.get("driving", {})
        return self.params.get("casual", {})

    async def start(self):
        pass

    async def stop(self):
        pass
