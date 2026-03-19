"""
Voice Activity Detection module.

Uses silero-vad v6 (pip installable, torch-based, no torchaudio needed in older versions).
Falls back to simple energy-based detection if unavailable.
"""

from typing import Optional, List, Tuple
import numpy as np
from loguru import logger


class VoiceActivityDetector:
    """Voice Activity Detection using silero-vad v6."""

    # Silero v6 requires exactly 512 samples at 16 kHz
    CHUNK_SAMPLES = 512

    def __init__(self, threshold: float = 0.4, sample_rate: int = 16000):
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.model = None
        self._get_speech_timestamps = None
        self._backend = "none"
        self._loaded = False
        # 不在构造时加载，首次使用时加载（节省 4 秒启动时间）

    def _ensure_loaded(self):
        """懒加载：首次调用 VAD 方法时才加载模型"""
        if not self._loaded:
            self._loaded = True
            self._load_model()

    # ──────────────────────────────────────────────────────
    # Model loading
    # ──────────────────────────────────────────────────────

    def _load_model(self):
        """Load VAD model (silero-vad v6 preferred, energy fallback)."""
        # 1. Try silero-vad (pip package, torch-based)
        try:
            import warnings
            from silero_vad import load_silero_vad, get_speech_timestamps

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.model = load_silero_vad()

            self._get_speech_timestamps = get_speech_timestamps
            self._backend = "silero"
            logger.info("✅ Silero VAD v6 loaded")
            return
        except ImportError:
            logger.warning("silero-vad not installed — trying torch.hub...")
        except Exception as e:
            logger.warning(f"silero-vad load error: {e} — trying torch.hub...")

        # 2. Try torch.hub (older silero-vad, needs internet first time)
        try:
            import warnings
            import torch

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model, utils = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    force_reload=False,
                    verbose=False,
                )
            self.model = model
            self._get_speech_timestamps = utils[0]
            self._backend = "silero_hub"
            logger.info("✅ Silero VAD loaded via torch.hub")
            return
        except Exception as e:
            logger.warning(f"torch.hub silero-vad failed: {e} — using energy VAD")

        # 3. Energy-based fallback (no dependencies)
        self._backend = "energy"
        logger.info("⚠️ VAD fallback: simple energy detector (no silence detection)")

    # ──────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────

    def is_speech(self, audio: np.ndarray, sample_rate: int = None) -> bool:
        """
        Return True if the audio chunk likely contains speech.

        Works with any chunk length (internally splits into 512-sample windows).
        """
        self._ensure_loaded()
        sr = sample_rate or self.sample_rate

        if self._backend in ("silero", "silero_hub"):
            return self._silero_is_speech(audio, sr)
        else:
            return self._energy_is_speech(audio)

    def has_speech(self, audio: np.ndarray, sample_rate: int = None) -> bool:
        """
        Check whether a full audio buffer (e.g. a complete utterance) contains
        any speech segment. Use this after recording is done.
        """
        return self.is_speech(audio, sample_rate)

    def get_speech_segments(
        self, audio: np.ndarray, sample_rate: int = None
    ) -> List[Tuple[int, int]]:
        """
        Return a list of (start_sample, end_sample) speech segments.
        Useful for trimming silence from a recording.
        """
        sr = sample_rate or self.sample_rate

        if self._backend in ("silero", "silero_hub"):
            return self._silero_timestamps(audio, sr)
        else:
            # Energy-based: return whole buffer if speech detected
            if self._energy_is_speech(audio):
                return [(0, len(audio))]
            return []

    @property
    def backend(self) -> str:
        return self._backend

    # ──────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────

    def _silero_is_speech(self, audio: np.ndarray, sr: int) -> bool:
        """Run silero VAD on variable-length audio by splitting into chunks."""
        try:
            import torch

            audio_f32 = audio.astype(np.float32)

            # Pad to multiple of CHUNK_SAMPLES
            remainder = len(audio_f32) % self.CHUNK_SAMPLES
            if remainder:
                audio_f32 = np.concatenate(
                    [audio_f32, np.zeros(self.CHUNK_SAMPLES - remainder, dtype=np.float32)]
                )

            # Score each chunk; return True if any chunk exceeds threshold
            for i in range(0, len(audio_f32), self.CHUNK_SAMPLES):
                chunk = torch.from_numpy(audio_f32[i : i + self.CHUNK_SAMPLES])
                prob = self.model(chunk, sr)
                if float(prob.detach()) > self.threshold:
                    return True
            return False
        except Exception as e:
            logger.error(f"Silero VAD error: {e}")
            return True  # Assume speech on error to avoid silent drops

    def _silero_timestamps(self, audio: np.ndarray, sr: int) -> List[Tuple[int, int]]:
        """Use get_speech_timestamps to find speech segments."""
        try:
            import torch

            tensor = torch.from_numpy(audio.astype(np.float32))
            ts = self._get_speech_timestamps(
                tensor,
                self.model,
                sampling_rate=sr,
                threshold=self.threshold,
                return_seconds=False,
            )
            return [(t["start"], t["end"]) for t in ts]
        except Exception as e:
            logger.error(f"Silero timestamps error: {e}")
            return [(0, len(audio))]

    def _energy_is_speech(self, audio: np.ndarray) -> bool:
        """Simple RMS energy threshold — very fast, no ML required."""
        if len(audio) == 0:
            return False
        rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
        return rms > 0.01  # ~-40 dBFS threshold
