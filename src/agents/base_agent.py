"""Base class for all OMNIMIND agents."""
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    def __init__(self, config: dict, bus):
        self.config = config
        self.bus = bus

    @abstractmethod
    async def execute(self, tool_name: str, params: dict) -> dict:
        pass

    @abstractmethod
    def get_tools_schema(self) -> list:
        """Return list of tool definitions for LLM function calling."""
        pass
