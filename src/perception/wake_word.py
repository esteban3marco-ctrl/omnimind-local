"""Wake word detection — listens for 'Hey Leo'."""
import asyncio, logging
logger = logging.getLogger("omnimind.wake")

class WakeWordDetector:
    def __init__(self, config, bus):
        self.config = config.get("wake_word", {})
        self.bus = bus
        self.running = False

    async def start(self):
        self.running = True
        asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        """Continuously listen for wake word using OpenWakeWord."""
        # In production: uses openwakeword + pyaudio to detect "Hey Leo"
        # On detection, publishes event to trigger STT recording
        try:
            from openwakeword.model import Model
            import pyaudio, numpy as np

            model = Model(wakeword_models=[self.config.get("model_path", "hey_jarvis")])
            audio = pyaudio.PyAudio()
            stream = audio.open(rate=16000, channels=1, format=pyaudio.paInt16, input=True, frames_per_buffer=1280)
            logger.info("Wake word detector active — say 'Hey Leo'")

            while self.running:
                data = stream.read(1280, exception_on_overflow=False)
                audio_array = np.frombuffer(data, dtype=np.int16)
                prediction = model.predict(audio_array)
                for name, score in prediction.items():
                    if score > self.config.get("threshold", 0.7):
                        logger.info(f"Wake word detected! (score: {score:.2f})")
                        await self.bus.publish("omnimind.voice.input", {"event": "wake_detected"})
                        await asyncio.sleep(self.config.get("cooldown_seconds", 2))
        except ImportError:
            logger.warning("OpenWakeWord not installed — wake word detection disabled")
        except Exception as e:
            logger.error(f"Wake word error: {e}")

    async def stop(self):
        self.running = False
