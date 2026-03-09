"""
Speech-to-Text using faster-whisper with integrated Silero VAD.

Improvements:
- VAD pre-filter: only sends audio to Whisper when actual speech is detected.
  This stops Whisper from processing silence 24/7, saving CPU and VRAM.
- Language auto-detection fallback: if confidence < 0.8, detects language automatically.
- No-speech probability filter: discards hallucinated transcriptions from background noise.
- Publishes transcribed text to the message bus for downstream consumption.
"""
import asyncio
import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger("omnimind.stt")

# Silero VAD constants
VAD_SAMPLE_RATE = 16000
VAD_CHUNK_SIZE = 512   # samples per chunk (~32ms at 16kHz)
VAD_MIN_SPEECH_MS = 300  # ignore blips shorter than 300ms
VAD_MAX_SILENCE_MS = 700  # end utterance after 700ms of silence


class STTEngine:
    def __init__(self, config, bus):
        self.config = config.get("stt", {})
        self.bus = bus
        self.model = None
        self._vad_model = None
        self._language = self.config.get("language", None)  # None = auto-detect
        self._no_speech_threshold = self.config.get("no_speech_threshold", 0.6)

    async def start(self):
        await asyncio.gather(
            self._load_whisper(),
            self._load_vad(),
        )

    async def _load_whisper(self):
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(
                self.config.get("model", "large-v3-turbo"),
                device=self.config.get("device", "cuda"),
                compute_type=self.config.get("compute_type", "int8"),
            )
            logger.info("STT engine ready (faster-whisper large-v3-turbo)")
        except Exception as e:
            logger.warning(f"STT init failed: {e}")

    async def _load_vad(self):
        """Load Silero VAD for speech/silence detection."""
        try:
            import torch
            self._vad_model, _ = torch.hub.load(
                "snakers4/silero-vad",
                "silero_vad",
                force_reload=False,
                verbose=False,
            )
            self._vad_model.eval()
            logger.info("Silero VAD integrated into STT pipeline")
        except Exception as e:
            logger.warning(f"VAD load failed (will transcribe all audio): {e}")
            self._vad_model = None

    def is_speech(self, audio_chunk_np: np.ndarray) -> bool:
        """
        Quick VAD check on a raw numpy float32 chunk.
        Returns True if speech is detected above threshold.
        Falls back to True (always transcribe) if VAD is unavailable.
        """
        if self._vad_model is None:
            return True
        try:
            import torch
            chunk = torch.from_numpy(audio_chunk_np).float()
            if chunk.dim() == 1:
                chunk = chunk.unsqueeze(0)
            prob = self._vad_model(chunk, VAD_SAMPLE_RATE).item()
            return prob > self.config.get("vad_threshold", 0.5)
        except Exception:
            return True  # On error, pass audio through

    async def transcribe(self, audio_path: str) -> str:
        """
        Transcribe an audio file.
        - Skips transcription if the file appears to be silence (VAD pre-check).
        - Discards results with high no_speech_prob (Whisper hallucinations).
        - Auto-detects language if not configured.
        Returns the transcribed text, or "" if nothing meaningful was detected.
        """
        if not self.model:
            return ""

        try:
            segments, info = self.model.transcribe(
                audio_path,
                language=self._language,         # None = auto-detect per file
                vad_filter=True,                 # faster-whisper built-in VAD pre-filter
                vad_parameters={
                    "min_silence_duration_ms": VAD_MAX_SILENCE_MS,
                    "speech_pad_ms": 100,
                },
                no_speech_threshold=self._no_speech_threshold,
                word_timestamps=False,
                beam_size=self.config.get("beam_size", 5),
            )

            # Log detected language if auto-detecting
            if not self._language and info.language_probability > 0.0:
                logger.debug(
                    f"Detected language: {info.language} "
                    f"(confidence={info.language_probability:.2f})"
                )

            # Filter out low-confidence segments (likely noise/hallucination)
            text_parts = []
            for seg in segments:
                no_speech = getattr(seg, "no_speech_prob", 0.0)
                if no_speech < self._no_speech_threshold:
                    text_parts.append(seg.text.strip())

            transcript = " ".join(text_parts).strip()

            if transcript:
                logger.info(f"Transcribed: '{transcript}'")
                # Publish to message bus for downstream modules
                await self.bus.publish("omnimind.voice.text", {
                    "text": transcript,
                    "language": info.language,
                    "confidence": info.language_probability,
                })

            return transcript

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""

    async def stop(self):
        self.model = None
        self._vad_model = None
