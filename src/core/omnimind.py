"""
OMNIMIND LOCAL — Main Entry Point
Leo: Your private cognitive AI assistant.

This is the main orchestration loop that ties together:
- Wake word detection → STT → LLM → TTS (voice loop)
- Context engine (location, time, state)
- Memory (RAG: vector + BM25)
- Agent orchestration (tools, actions)
- Proactive intelligence
- Learning feedback collection
"""

import asyncio
import signal
import logging
from pathlib import Path

from src.core.config_loader import load_config
from src.core.message_bus import MessageBus
from src.core.health_checker import HealthChecker

logger = logging.getLogger("omnimind")


class OmniMind:
    """Main application class — Leo's brain."""

    def __init__(self):
        self.config = load_config()
        self.bus = MessageBus(self.config)
        self.health = HealthChecker(self.config)
        self.running = False

    async def start(self):
        """Boot up all services and enter main loop."""
        logger.info("🧠 OMNIMIND LOCAL v2.0 'PROMETHEUS' starting...")
        logger.info(f"Assistant: {self.config['system']['assistant_name']}")

        # Connect to Redis message bus
        await self.bus.connect()
        logger.info("Message bus connected")

        # Initialize components (each subscribes to relevant channels)
        # These are imported and initialized lazily to allow partial boot
        from src.perception.wake_word import WakeWordDetector
        from src.perception.stt_engine import STTEngine
        from src.output.tts_engine import TTSEngine
        from src.cognition.llm_engine import LLMEngine
        from src.cognition.rag_engine import RAGEngine
        from src.memory.vector_store import VectorStore
        from src.understanding.context_engine import ContextEngine
        from src.agents.orchestrator import AgentOrchestrator
        from src.output.personality_engine import PersonalityEngine
        from src.learning.feedback_collector import FeedbackCollector

        self.components = {
            "wake_word": WakeWordDetector(self.config, self.bus),
            "stt": STTEngine(self.config, self.bus),
            "tts": TTSEngine(self.config, self.bus),
            "llm": LLMEngine(self.config, self.bus),
            "rag": RAGEngine(self.config, self.bus),
            "vectors": VectorStore(self.config),
            "context": ContextEngine(self.config, self.bus),
            "agents": AgentOrchestrator(self.config, self.bus),
            "personality": PersonalityEngine(self.config),
            "feedback": FeedbackCollector(self.config, self.bus),
        }

        # Start all components
        for name, component in self.components.items():
            try:
                await component.start()
                logger.info(f"  ✓ {name}")
            except Exception as e:
                logger.warning(f"  ✗ {name}: {e} (continuing without it)")

        # Start health monitoring
        asyncio.create_task(self.health.monitor_loop())

        self.running = True
        logger.info("🟢 Leo is awake and listening!")

        # Main event loop
        await self._main_loop()

    async def _main_loop(self):
        """Main event loop — processes messages from the bus."""
        while self.running:
            try:
                # The voice loop:
                # 1. WakeWordDetector listens for "Hey Leo"
                # 2. On detection, publishes to omnimind.voice.input
                # 3. STTEngine transcribes and publishes text
                # 4. ContextEngine enriches with context
                # 5. RAGEngine retrieves relevant memory
                # 6. LLMEngine generates response
                # 7. AgentOrchestrator executes any tool calls
                # 8. PersonalityEngine adapts tone
                # 9. TTSEngine speaks the response
                # 10. FeedbackCollector logs for learning

                # All of this happens via pub/sub on the message bus.
                # This loop just keeps the process alive and handles health.
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(5)

    async def shutdown(self):
        """Graceful shutdown of all services."""
        logger.info("Shutting down OMNIMIND...")
        self.running = False

        for name, component in self.components.items():
            try:
                await component.stop()
                logger.info(f"  ✓ {name} stopped")
            except Exception as e:
                logger.warning(f"  ✗ {name} stop failed: {e}")

        await self.bus.disconnect()
        logger.info("👋 Leo is asleep. Goodbye!")


def main():
    """Entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    app = OmniMind()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Handle shutdown signals
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(app.shutdown()))

    try:
        loop.run_until_complete(app.start())
    except KeyboardInterrupt:
        loop.run_until_complete(app.shutdown())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
