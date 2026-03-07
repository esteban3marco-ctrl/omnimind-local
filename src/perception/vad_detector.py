"""Voice Activity Detection using Silero VAD."""
import logging
logger = logging.getLogger("omnimind.vad")

class VADDetector:
    def __init__(self, config):
        self.threshold = config.get("vad", {}).get("threshold", 0.5)
        self.model = None

    def load(self):
        try:
            import torch
            self.model, _ = torch.hub.load("snakers4/silero-vad", "silero_vad")
            logger.info("Silero VAD loaded")
        except Exception as e:
            logger.warning(f"VAD load failed: {e}")

    def is_speech(self, audio_chunk) -> bool:
        if not self.model:
            return True
        prob = self.model(audio_chunk, 16000).item()
        return prob > self.threshold
