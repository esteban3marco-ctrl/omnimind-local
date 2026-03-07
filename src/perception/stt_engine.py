"""Speech-to-Text using faster-whisper."""
import asyncio, logging
logger = logging.getLogger("omnimind.stt")

class STTEngine:
    def __init__(self, config, bus):
        self.config = config.get("stt", {})
        self.bus = bus
        self.model = None

    async def start(self):
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(
                self.config.get("model", "large-v3-turbo"),
                device=self.config.get("device", "cuda"),
                compute_type=self.config.get("compute_type", "int8"),
            )
            logger.info("STT engine ready (faster-whisper)")
        except Exception as e:
            logger.warning(f"STT init failed: {e}")

    async def transcribe(self, audio_path: str) -> str:
        if not self.model:
            return ""
        segments, info = self.model.transcribe(audio_path, language=self.config.get("language", "es"))
        return " ".join(s.text for s in segments).strip()

    async def stop(self):
        self.model = None
