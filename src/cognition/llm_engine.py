"""LLM inference engine — wraps llama.cpp server."""
import asyncio, logging, json
import httpx
logger = logging.getLogger("omnimind.llm")

class LLMEngine:
    def __init__(self, config, bus):
        self.bus = bus
        svc = config.get("services", {}).get("llm_server", {})
        self.base_url = f"http://{svc.get('host', '127.0.0.1')}:{svc.get('port', 8080)}"
        self.leo_prompt = config.get("leo", {}).get("system_prompt", "You are Leo.")
        self.client = httpx.AsyncClient(timeout=60)

    async def start(self):
        try:
            r = await self.client.get(f"{self.base_url}/health")
            r.raise_for_status()
            logger.info("LLM server connected")
        except Exception as e:
            logger.warning(f"LLM server not ready: {e}")

    async def generate(self, messages: list, tools: list = None, **kwargs) -> dict:
        payload = {
            "messages": [{"role": "system", "content": self.leo_prompt}] + messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 1024),
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        try:
            r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return {"role": "assistant", "content": "Lo siento, ha habido un error procesando tu mensaje."}

    async def stop(self):
        await self.client.aclose()
