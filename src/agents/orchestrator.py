"""
OMNIMIND LOCAL — Agent Orchestrator
════════════════════════════════════

Central router that receives LLM tool calls and dispatches them to the
right execution backend: DeviceOrchestrator (physical hardware) or
built-in software agents (calendar, files, notes, etc.).

Key improvements over the original stub:
- Real dispatch to DeviceOrchestrator for any device__ tool call
- Confirmation gate: dangerous actions (drone flight, door locks, car control)
  require an explicit "yes/no" confirmation from the user before execution
- Retry logic: failed tool calls are retried up to N times before reporting error
- Timeout per-agent: prevent a hung device from blocking the voice loop
- Execution log: every tool call is logged with timing for debugging and UX
"""
import asyncio
import logging
import time
from enum import Enum, auto
from dataclasses import dataclass, field

logger = logging.getLogger("omnimind.orchestrator")


# ─────────────────────────────────
# Risk levels
# ─────────────────────────────────

class RiskLevel(Enum):
    SAFE = auto()       # Execute immediately (query, read, light toggle)
    CONFIRM = auto()    # Ask user to confirm before executing (irreversible actions)
    BLOCKED = auto()    # Never execute autonomously (e.g., payments above threshold)


# Tools that require user confirmation before execution
CONFIRM_REQUIRED: set[str] = {
    "drone__takeoff", "drone__fly_to", "drone__land",
    "car__unlock_doors", "car__start_engine",
    "smart_lock__unlock", "smart_lock__lock",
    "alarm__disarm",
    "garage__open",
}

# Map agent name prefix → risk level (if not in CONFIRM_REQUIRED, defaults to SAFE)
AGENT_RISK_LEVELS: dict[str, RiskLevel] = {
    "drone":       RiskLevel.CONFIRM,
    "car":         RiskLevel.CONFIRM,
    "smart_lock":  RiskLevel.CONFIRM,
    "alarm":       RiskLevel.CONFIRM,
    "garage":      RiskLevel.CONFIRM,
}


@dataclass
class ToolCallResult:
    tool_name: str
    params: dict
    success: bool
    result: dict
    duration_ms: float
    attempts: int = 1
    confirmed: bool = True


class AgentOrchestrator:
    """
    Routes LLM-generated tool calls to the correct backend with safety gates.
    """

    def __init__(self, config, bus):
        self.config = config.get("agents", {})
        self.bus = bus
        self.agents: dict[str, dict] = {}
        self._device_orchestrator = None     # Injected after DeviceOrchestrator starts
        self._pending_confirmation: dict[str, dict] = {}  # tool_call_id → pending action
        self._exec_log: list[ToolCallResult] = []
        self._timeout_s = self.config.get("orchestrator", {}).get("timeout_per_agent_seconds", 10)
        self._max_retries = self.config.get("orchestrator", {}).get("max_retries", 2)

    def attach_device_orchestrator(self, device_orchestrator):
        """Inject DeviceOrchestrator reference after it has started."""
        self._device_orchestrator = device_orchestrator
        logger.info("Orchestrator: DeviceOrchestrator attached")

    async def start(self):
        for name, cfg in self.config.items():
            if isinstance(cfg, dict) and cfg.get("enabled"):
                self.agents[name] = cfg
                logger.info(f"  Agent registered: {name}")
        logger.info(f"Agent orchestrator ready ({len(self.agents)} software agents)")

    # ─────────────────────────────────
    # Main Entry Point
    # ─────────────────────────────────

    async def execute(self, tool_name: str, params: dict) -> dict:
        """
        Execute a tool call from the LLM.
        1. Determine the risk level of the action.
        2. If CONFIRM required, enqueue and request user confirmation.
        3. Otherwise dispatch and retry up to _max_retries.
        Returns a dict that gets injected back into the conversation.
        """
        risk = self._assess_risk(tool_name)

        if risk == RiskLevel.BLOCKED:
            return {
                "status": "blocked",
                "reason": f"Tool '{tool_name}' is blocked for autonomous execution.",
                "tool": tool_name,
            }

        if risk == RiskLevel.CONFIRM:
            return await self._request_confirmation(tool_name, params)

        return await self._dispatch_with_retry(tool_name, params)

    async def confirm(self, tool_name: str, confirmed: bool) -> dict:
        """
        Called when the user responds 'yes' or 'no' to a confirmation request.
        If confirmed, the pending action is executed.
        """
        pending = self._pending_confirmation.pop(tool_name, None)
        if not pending:
            return {"status": "error", "reason": "No pending confirmation found for this action."}

        if not confirmed:
            logger.info(f"[orchestrator] User REJECTED: {tool_name}")
            await self.bus.publish("omnimind.agent.response", {
                "tool": tool_name,
                "status": "cancelled",
                "message": "Action cancelled by user.",
            })
            return {"status": "cancelled", "tool": tool_name}

        logger.info(f"[orchestrator] User CONFIRMED: {tool_name}")
        result = await self._dispatch_with_retry(tool_name, pending.get("params", {}))
        result["confirmed"] = True
        return result

    # ─────────────────────────────────
    # Risk Assessment
    # ─────────────────────────────────

    def _assess_risk(self, tool_name: str) -> RiskLevel:
        if tool_name in CONFIRM_REQUIRED:
            return RiskLevel.CONFIRM
        prefix = tool_name.split("__")[0]
        return AGENT_RISK_LEVELS.get(prefix, RiskLevel.SAFE)

    async def _request_confirmation(self, tool_name: str, params: dict) -> dict:
        """Enqueue the action and ask Leo to request confirmation from the user."""
        self._pending_confirmation[tool_name] = {"params": params}
        logger.info(f"[orchestrator] Confirmation required for: {tool_name} params={params}")
        await self.bus.publish("omnimind.confirmation.required", {
            "tool": tool_name,
            "params": params,
            "message": f"I need your confirmation to execute: {tool_name.replace('__', ' → ')}. Say 'yes' to proceed or 'no' to cancel.",
        })
        return {
            "status": "awaiting_confirmation",
            "tool": tool_name,
            "message": f"Confirmation requested for '{tool_name}'.",
        }

    # ─────────────────────────────────
    # Dispatch with Retry
    # ─────────────────────────────────

    async def _dispatch_with_retry(self, tool_name: str, params: dict) -> dict:
        """Dispatch a tool call with timeout and retry logic."""
        last_error = None
        for attempt in range(1, self._max_retries + 2):  # +2 = initial try + retries
            t0 = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    self._dispatch(tool_name, params),
                    timeout=self._timeout_s,
                )
                duration_ms = (time.perf_counter() - t0) * 1000

                self._log(ToolCallResult(
                    tool_name=tool_name,
                    params=params,
                    success=True,
                    result=result,
                    duration_ms=duration_ms,
                    attempts=attempt,
                ))

                await self.bus.publish("omnimind.agent.response", {
                    "tool": tool_name,
                    "status": "success",
                    "result": result,
                    "duration_ms": round(duration_ms),
                })
                return result

            except asyncio.TimeoutError:
                last_error = f"Timeout after {self._timeout_s}s"
                logger.warning(f"[orchestrator] {tool_name} timed out (attempt {attempt})")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"[orchestrator] {tool_name} failed (attempt {attempt}): {e}")

            if attempt <= self._max_retries:
                await asyncio.sleep(0.5 * attempt)  # Back-off before retry

        # All attempts exhausted
        error_result = {"status": "error", "tool": tool_name, "reason": last_error}
        self._log(ToolCallResult(
            tool_name=tool_name,
            params=params,
            success=False,
            result=error_result,
            duration_ms=0,
            attempts=self._max_retries + 1,
        ))
        return error_result

    async def _dispatch(self, tool_name: str, params: dict) -> dict:
        """Route to the correct backend."""
        # Device calls: device_id__capability_name
        if "__" in tool_name and self._device_orchestrator:
            return await self._device_orchestrator.execute(tool_name, params)

        # Software agents registered from agents.yaml
        prefix = tool_name.split("_")[0] if "_" in tool_name else tool_name
        if prefix in self.agents:
            return await self._run_software_agent(prefix, tool_name, params)

        return {"status": "error", "reason": f"No backend found for tool: {tool_name}"}

    async def _run_software_agent(self, agent_name: str, tool: str, params: dict) -> dict:
        """
        Placeholder for software agent execution.
        Individual agent modules (calendar, files, notes…) plug in here.
        Each implements a handle(tool, params) → dict coroutine.
        """
        logger.info(f"[orchestrator] Executing {tool} via {agent_name} agent")
        # TODO: dynamically import agent module from src/agents/{agent_name}_agent.py
        return {"status": "ok", "agent": agent_name, "tool": tool, "params": params}

    # ─────────────────────────────────
    # Logging & Stats
    # ─────────────────────────────────

    def _log(self, result: ToolCallResult):
        self._exec_log.append(result)
        if len(self._exec_log) > 1000:    # Circular buffer — keep last 1000
            self._exec_log.pop(0)

    def get_stats(self) -> dict:
        total = len(self._exec_log)
        successes = sum(1 for r in self._exec_log if r.success)
        avg_ms = sum(r.duration_ms for r in self._exec_log) / max(1, total)
        return {
            "total_calls": total,
            "success_rate": f"{successes / max(1, total) * 100:.1f}%",
            "avg_latency_ms": round(avg_ms, 1),
            "pending_confirmations": list(self._pending_confirmation.keys()),
        }

    async def stop(self):
        self._pending_confirmation.clear()
