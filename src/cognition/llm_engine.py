"""
LLM inference engine — wraps llama.cpp server.

Improvements:
- Streaming mode: Leo starts speaking in <500ms instead of waiting 5-10s
- Context-aware temperature: different tone for car vs home vs mobile
- Semantic cache integration: skip LLM for repeated similar queries
- Retry logic with exponential backoff
"""
import asyncio
import logging
import json
import httpx
from typing import AsyncIterator

logger = logging.getLogger("omnimind.llm")


class LLMEngine:
    def __init__(self, config, bus):
        self.bus = bus
        svc = config.get("services", {}).get("llm_server", {})
        self.base_url = f"http://{svc.get('host', '127.0.0.1')}:{svc.get('port', 8080)}"
        self.leo_prompt = config.get("leo", {}).get("system_prompt", "You are Leo.")
        self.client = httpx.AsyncClient(timeout=60)

        # Context-aware temperature per environment
        # Leo is more relaxed and creative at home, more concise in the car
        self._context_temperature = {
            "home":   0.75,
            "car":    0.45,  # Short, focused answers while driving
            "mobile": 0.60,
            "default": 0.70,
        }

        # Semantic cache (injected after VectorStore is ready)
        self._semantic_cache = None
        self._current_context = "home"

    def set_context(self, context: str):
        """Switch Leo's personality based on environment (home / car / mobile)."""
        self._current_context = context
        logger.info(f"LLM context switched to: {context} "
                    f"(temperature={self._context_temperature.get(context, 0.70)})")

    def attach_semantic_cache(self, cache):
        """Inject the SemanticCache once the VectorStore is ready."""
        self._semantic_cache = cache
        logger.info("Semantic cache attached to LLM engine")

    def _get_temperature(self) -> float:
        return self._context_temperature.get(self._current_context,
                                              self._context_temperature["default"])

    async def start(self):
        """Connect to llama.cpp server with retry."""
        for attempt in range(5):
            try:
                r = await self.client.get(f"{self.base_url}/health")
                r.raise_for_status()
                logger.info("LLM server connected")
                return
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(f"LLM server not ready (attempt {attempt+1}/5): {e}. Retrying in {wait}s...")
                await asyncio.sleep(wait)
        logger.error("LLM server unreachable after 5 attempts. Voice loop will not work.")

    async def generate(self, messages: list, tools: list = None, **kwargs) -> dict:
        """
        Generate a response (non-streaming).
        Checks semantic cache first — if hit, skips the LLM entirely.
        Falls back to full LLM generation on cache miss.
        """
        # Build the last user query string for cache lookup
        last_user_msg = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            None
        )

        # --- Semantic Cache Lookup ---
        if self._semantic_cache and last_user_msg and not tools:
            cached = self._semantic_cache.get(last_user_msg)
            if cached:
                logger.info(f"[cache HIT] Skipping LLM for: '{last_user_msg[:60]}...'")
                return {"role": "assistant", "content": cached}

        # --- Full LLM Generation ---
        response = await self._generate_full(messages, tools, **kwargs)

        # Store in cache (only for simple text responses, not tool calls)
        if (self._semantic_cache and last_user_msg and not tools
                and response.get("content") and not response.get("tool_calls")):
            self._semantic_cache.put(last_user_msg, response["content"])

        return response

    async def generate_stream(self, messages: list, tools: list = None, **kwargs) -> AsyncIterator[str]:
        """
        Streaming generation — yields text chunks as they arrive.
        Leo starts "speaking" in <500ms instead of waiting for the full response.
        Connect TTS to consume these chunks token by token.
        """
        payload = {
            "messages": [{"role": "system", "content": self.leo_prompt}] + messages,
            "temperature": kwargs.get("temperature", self._get_temperature()),
            "max_tokens": kwargs.get("max_tokens", 1024),
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except Exception as e:
            logger.error(f"LLM stream error: {e}")
            yield "Lo siento, ha habido un error procesando tu mensaje."

    async def _generate_full(self, messages: list, tools: list = None, **kwargs) -> dict:
        """Internal non-streaming generation with retry (max 3 attempts)."""
        payload = {
            "messages": [{"role": "system", "content": self.leo_prompt}] + messages,
            "temperature": kwargs.get("temperature", self._get_temperature()),
            "max_tokens": kwargs.get("max_tokens", 1024),
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        for attempt in range(3):
            try:
                r = await self.client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload
                )
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]
            except Exception as e:
                if attempt == 2:
                    logger.error(f"LLM error after 3 attempts: {e}")
                    return {"role": "assistant", "content": "Lo siento, ha habido un error procesando tu mensaje."}
                await asyncio.sleep(1)

    async def stop(self):
        await self.client.aclose()
