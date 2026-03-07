"""Build system prompts with context injection."""

class PromptBuilder:
    def __init__(self, config):
        self.base_prompt = config.get("leo", {}).get("system_prompt", "")

    def build(self, context: dict = None, rag_results: list = None, tools: list = None) -> str:
        parts = [self.base_prompt]
        if context:
            parts.append(f"\n## CONTEXTO ACTUAL\n- Ubicación: {context.get('location', 'desconocida')}")
            parts.append(f"- Momento: {context.get('time_of_day', '')}")
            parts.append(f"- Hora: {context.get('timestamp', '')}")
        if rag_results:
            parts.append("\n## MEMORIA RELEVANTE")
            for r in rag_results:
                parts.append(f"- {r.get('content', '')}")
        return "\n".join(parts)
