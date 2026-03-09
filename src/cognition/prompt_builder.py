"""
OMNIMIND LOCAL — Dynamic Prompt Builder
═════════════════════════════════════════

Builds the final system prompt injected into every LLM call.
Goes far beyond simple text concatenation:
- Injects real-time context (time of day, location, environment mode)
- Injects RAG memory results as structured bullet points
- Adapts Leo's persona based on context (home / car / mobile / night)
- Injects device status summary (which devices are connected and their state)
- Caps total prompt length to avoid exceeding the model's context window
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("omnimind.prompt")

# Maximum characters for injected RAG context (prevents context overflow)
MAX_RAG_CHARS = 2400
# Maximum characters for device status summary
MAX_DEVICE_CHARS = 800


class PromptBuilder:
    def __init__(self, config):
        cfg = config.get("leo", {})
        self.base_prompt = cfg.get("system_prompt", "You are Leo, a private AI assistant.")
        self.assistant_name = cfg.get("name", "Leo")
        self.user_name = config.get("personal", {}).get("name", "there")
        self.timezone = config.get("system", {}).get("timezone", "Europe/Madrid")

        # Per-context personality modifiers
        self._context_modifiers = {
            "car": (
                "\n\n## ACTIVE CONTEXT: CAR MODE\n"
                "The user is driving. Use SHORT responses (max 2 sentences). "
                "Never ask multiple questions. Prioritize safety — if you detect "
                "distraction risk, politely limit the interaction."
            ),
            "mobile": (
                "\n\n## ACTIVE CONTEXT: MOBILE\n"
                "The user is on their phone/away from home. Keep responses concise. "
                "For device controls, always confirm location before acting on home devices."
            ),
            "night": (
                "\n\n## ACTIVE CONTEXT: NIGHT MODE\n"
                f"It's late. Use a calm, quieter tone. Avoid exciting or alarming responses "
                f"unless urgent. Remind {self.user_name} to rest if interacting past midnight."
            ),
            "home": "",  # Default, no modifier needed
        }

    def build(
        self,
        context: dict = None,
        rag_results: list = None,
        device_summaries: list = None,
        active_context: str = "home",
    ) -> str:
        """
        Build the full system prompt for the current LLM call.

        Args:
            context: From ContextEngine (location, time_of_day, timestamp, etc.)
            rag_results: From RAGEngine (list of {"content", "metadata", ...})
            device_summaries: From DeviceOrchestrator (list of device status dicts)
            active_context: One of "home", "car", "mobile", "night"

        Returns:
            The complete system prompt string.
        """
        parts = [self.base_prompt]

        # 1. Context-adaptive personality modifier
        modifier = self._context_modifiers.get(active_context, "")
        if modifier:
            parts.append(modifier)

        # 2. Real-time situational context
        if context:
            parts.append(self._build_context_section(context))

        # 3. Connected devices summary (so Leo knows what tools he can use)
        if device_summaries:
            parts.append(self._build_devices_section(device_summaries))

        # 4. Relevant memory chunks from RAG
        if rag_results:
            parts.append(self._build_memory_section(rag_results))

        prompt = "\n".join(parts)
        logger.debug(f"Prompt built: {len(prompt)} chars, context={active_context}, "
                     f"rag_docs={len(rag_results or [])}, devices={len(device_summaries or [])}")
        return prompt

    def _build_context_section(self, context: dict) -> str:
        """Build the real-time situational context block."""
        try:
            tz = ZoneInfo(self.timezone)
            now = datetime.now(tz)
            time_str = now.strftime("%A, %d %B %Y at %H:%M")
        except Exception:
            time_str = context.get("timestamp", "unknown time")

        lines = [
            "\n## SITUATIONAL CONTEXT",
            f"- Date/Time: {time_str}",
        ]

        if context.get("location"):
            lines.append(f"- Location: {context['location']}")
        if context.get("time_of_day"):
            lines.append(f"- Time of day: {context['time_of_day']}")
        if context.get("weather"):
            w = context["weather"]
            lines.append(f"- Weather: {w.get('condition', '?')}, {w.get('temp_c', '?')}°C")
        if context.get("user_state"):
            lines.append(f"- User state: {context['user_state']}")

        return "\n".join(lines)

    def _build_devices_section(self, device_summaries: list) -> str:
        """Build a compact summary of connected devices and their current state."""
        connected = [d for d in device_summaries if d.get("connected")]
        if not connected:
            return ""  # Don't inject a "no devices" section to save tokens

        lines = ["\n## CONNECTED DEVICES (available tools)"]
        total_chars = 0

        for d in connected:
            caps = ", ".join(d.get("capabilities", []))
            state = ""
            if d.get("state"):
                state_kv = ", ".join(f"{k}={v}" for k, v in list(d["state"].items())[:3])
                state = f" | state: {state_kv}"
            line = f"- {d['name']} [{d.get('type', '?')}] @ {d.get('location', '?')} → {caps}{state}"

            if total_chars + len(line) > MAX_DEVICE_CHARS:
                lines.append(f"  ... and {len(connected) - len(lines) + 1} more devices")
                break
            lines.append(line)
            total_chars += len(line)

        return "\n".join(lines)

    def _build_memory_section(self, rag_results: list) -> str:
        """Build a memory block from RAG retrieved documents."""
        if not rag_results:
            return ""

        lines = ["\n## RELEVANT MEMORY"]
        total_chars = 0

        for r in rag_results:
            content = r.get("content", "").strip()
            if not content:
                continue
            # Truncate individual chunks if too long
            if len(content) > 400:
                content = content[:400] + "…"

            if total_chars + len(content) > MAX_RAG_CHARS:
                remaining = len(rag_results) - len(lines) + 1
                lines.append(f"  [+{remaining} more memory chunks not shown to fit context]")
                break

            lines.append(f"- {content}")
            total_chars += len(content)

        return "\n".join(lines)
