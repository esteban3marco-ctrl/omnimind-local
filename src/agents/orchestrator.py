"""Agent orchestrator — routes LLM tool calls to the right agent."""
import asyncio, logging
logger = logging.getLogger("omnimind.agents")

class AgentOrchestrator:
    def __init__(self, config, bus):
        self.config = config.get("agents", {})
        self.bus = bus
        self.agents = {}

    async def start(self):
        # Register enabled agents
        for name, cfg in self.config.items():
            if isinstance(cfg, dict) and cfg.get("enabled"):
                self.agents[name] = cfg
                logger.info(f"  Agent registered: {name}")

    async def execute(self, tool_name: str, params: dict) -> dict:
        for agent_name, cfg in self.agents.items():
            if tool_name.startswith(agent_name):
                return await self._dispatch(agent_name, tool_name, params)
        return {"error": f"No agent found for tool: {tool_name}"}

    async def _dispatch(self, agent: str, tool: str, params: dict) -> dict:
        logger.info(f"Executing {tool} via {agent} agent")
        # Each agent module handles its own tool calls
        return {"status": "ok", "agent": agent, "tool": tool}

    async def stop(self):
        pass
