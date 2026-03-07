"""Text-to-Speech using Piper TTS."""
import asyncio, logging, subprocess
logger = logging.getLogger("omnimind.tts")

class TTSEngine:
    def __init__(self, config, bus):
        self.config = config.get("tts", {})
        self.bus = bus

    async def start(self):
        logger.info("TTS engine ready (Piper)")

    async def speak(self, text: str, language: str = "es"):
        voice = self.config.get("voices", {}).get("spanish" if language == "es" else "english", {})
        model_path = voice.get("path", "")
        try:
            proc = await asyncio.create_subprocess_exec(
                "piper", "--model", model_path, "--output-raw",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate(text.encode())
            # Play audio via aplay or sounddevice
            play = await asyncio.create_subprocess_exec(
                "aplay", "-r", "22050", "-f", "S16_LE", "-c", "1",
                stdin=asyncio.subprocess.PIPE,
            )
            await play.communicate(stdout)
        except Exception as e:
            logger.error(f"TTS error: {e}")

    async def stop(self):
        pass
