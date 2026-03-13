"""
Speech-to-Text module — cloud-first with emotion detection.

Backend priority (cloud-first, zero GPU):
  1. DashScope SenseVoice (Ali cloud API, emotion + events, fast)
  2. OpenAI Whisper API   (cloud, high quality, multilingual)
  3. SenseVoice local     (GPU, 15x faster, Full installer only)
  4. faster-whisper local (GPU/CPU, Full installer only)
  5. mock                 (testing)

All backends return STTResult with text + optional emotion metadata.
"""

import asyncio
import io
import os
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, List, Optional

import numpy as np
from loguru import logger


@dataclass
class STTResult:
    text: str
    emotion: str = "neutral"
    emotion_score: float = 0.0
    events: List[str] = field(default_factory=list)
    language: str = ""
    latency_ms: int = 0


class SpeechToText:
    """Unified STT — cloud-first, local optional for Full installs."""

    def __init__(
        self,
        model_name: str = "base",
        device: str = "auto",
        language: str = "zh",
        prefer_cloud: bool = True,
    ):
        self.model_name = model_name
        self.device = device
        self.language = language
        self._prefer_cloud = prefer_cloud
        self._backend = "mock"
        self._model = None
        self._dashscope_key: Optional[str] = None
        self._openai_key: Optional[str] = None
        self._load_model()

    def _load_model(self):
        if self._prefer_cloud:
            if self._try_dashscope():
                return
            if self._try_openai_api():
                return

        if self._try_sensevoice_local():
            return
        if self._try_faster_whisper():
            return

        logger.warning("No STT backend — using mock mode")
        self._backend = "mock"

    # ------------------------------------------------------------------
    #  Cloud backends
    # ------------------------------------------------------------------

    def _try_dashscope(self) -> bool:
        key = os.environ.get("DASHSCOPE_API_KEY")
        if not key:
            return False
        self._dashscope_key = key
        self._backend = "dashscope"
        logger.info("DashScope SenseVoice API ready (cloud, emotion detection)")
        return True

    def _try_openai_api(self) -> bool:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return False
        self._openai_key = key
        self._backend = "openai-api"
        logger.info("OpenAI Whisper API ready (cloud)")
        return True

    # ------------------------------------------------------------------
    #  Local backends (Full installer only)
    # ------------------------------------------------------------------

    def _try_sensevoice_local(self) -> bool:
        try:
            from funasr import AutoModel
            dev = self._resolve_device()
            logger.info("Loading SenseVoice-Small (local) …")
            self._model = AutoModel(
                model="iic/SenseVoiceSmall",
                device=dev,
                disable_update=True,
            )
            self._backend = "sensevoice-local"
            logger.info("SenseVoice-Small local loaded")
            return True
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"SenseVoice local failed: {e}")
        return False

    def _try_faster_whisper(self) -> bool:
        try:
            from faster_whisper import WhisperModel
            dev = self._resolve_device()
            compute = "float16" if dev == "cuda" else "int8"
            real_dev = "cpu" if dev == "mps" else dev
            logger.info(f"Loading faster-whisper {self.model_name} on {real_dev}")
            self._model = WhisperModel(self.model_name, device=real_dev,
                                       compute_type=compute)
            self._backend = "faster-whisper"
            logger.info("faster-whisper loaded")
            return True
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"faster-whisper failed: {e}")
        return False

    def _resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    @property
    def backend_name(self) -> str:
        return self._backend

    @property
    def is_cloud(self) -> bool:
        return self._backend in ("dashscope", "openai-api")

    async def transcribe(self, audio: np.ndarray) -> STTResult:
        t0 = time.perf_counter()
        if self._backend == "dashscope":
            result = await self._transcribe_dashscope(audio)
        elif self._backend == "openai-api":
            result = await self._transcribe_openai_api(audio)
        else:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._transcribe_local_sync, audio)
        result.latency_ms = int((time.perf_counter() - t0) * 1000)
        return result

    async def transcribe_stream(
        self, audio: np.ndarray
    ) -> AsyncGenerator[STTResult, None]:
        if self._backend == "faster-whisper":
            async for r in self._stream_faster_whisper(audio):
                yield r
        else:
            result = await self.transcribe(audio)
            if result.text:
                yield result

    # ------------------------------------------------------------------
    #  DashScope SenseVoice cloud
    # ------------------------------------------------------------------

    async def _transcribe_dashscope(self, audio: np.ndarray) -> STTResult:
        import httpx
        try:
            wav_bytes = self._audio_to_wav(audio)

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://dashscope.aliyuncs.com/api/v1/services/"
                    "audio/asr/transcription",
                    headers={
                        "Authorization": f"Bearer {self._dashscope_key}",
                    },
                    files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                    data={
                        "model": "sensevoice-v1",
                        "language_hints": self.language
                        if self.language != "auto" else "",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return self._parse_dashscope(data)

                logger.warning(f"DashScope STT HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"DashScope STT error: {e}")
        return STTResult(text="")

    def _parse_dashscope(self, data: dict) -> STTResult:
        output = data.get("output", {})
        text = ""
        emotion = "neutral"
        events: List[str] = []

        if "sentence" in output:
            text = output.get("sentence", {}).get("text", "")
        elif "text" in output:
            text = output["text"]
        elif "transcription" in output:
            results = output["transcription"].get("results", [])
            text = " ".join(r.get("text", "") for r in results)

        emotion_data = output.get("emotion", {})
        if emotion_data:
            emo = emotion_data.get("label", "neutral")
            emotion = self._EMOTION_MAP.get(emo.upper(), "neutral")

        for tag in ("<|HAPPY|>", "<|SAD|>", "<|ANGRY|>", "<|NEUTRAL|>"):
            if tag in text:
                emotion = tag.strip("<|>").lower()
                text = text.replace(tag, "")
        for tag in ("<|Laughter|>", "<|Applause|>", "<|Cry|>",
                     "<|Cough|>", "<|Sneeze|>", "<|Music|>"):
            if tag in text:
                events.append(tag.strip("<|>").lower())
                text = text.replace(tag, "")
        for t in ("<|zh|>", "<|en|>", "<|ja|>", "<|ko|>", "<|yue|>",
                   "<|nospeech|>"):
            text = text.replace(t, "")

        return STTResult(text=text.strip(), emotion=emotion, events=events)

    # ------------------------------------------------------------------
    #  OpenAI Whisper cloud
    # ------------------------------------------------------------------

    async def _transcribe_openai_api(self, audio: np.ndarray) -> STTResult:
        import httpx
        try:
            wav_bytes = self._audio_to_wav(audio)
            base_url = os.environ.get(
                "OPENAI_BASE_URL", "https://api.openai.com/v1")

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._openai_key}"},
                    files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                    data={
                        "model": "whisper-1",
                        "language": self.language
                        if self.language != "auto" else "",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return STTResult(text=data.get("text", "").strip())
                logger.warning(f"OpenAI STT HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"OpenAI STT error: {e}")
        return STTResult(text="")

    # ------------------------------------------------------------------
    #  Audio conversion helper
    # ------------------------------------------------------------------

    @staticmethod
    def _audio_to_wav(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
        import wave
        buf = io.BytesIO()
        pcm = (audio * 32767).astype(np.int16) if audio.dtype == np.float32 \
            else audio.astype(np.int16)
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    # ------------------------------------------------------------------
    #  Emotion parsing
    # ------------------------------------------------------------------

    _EMOTION_MAP = {
        "HAPPY": "happy", "SAD": "sad", "ANGRY": "angry",
        "NEUTRAL": "neutral", "SURPRISED": "surprised",
        "DISGUSTED": "disgusted", "FEARFUL": "fearful",
    }
    _EVENT_TAGS = {"Laughter", "Applause", "Cry", "Cough", "Sneeze", "Music"}

    def _parse_sensevoice_local(self, raw) -> STTResult:
        if not raw:
            return STTResult(text="")
        item = raw[0] if isinstance(raw, list) else raw
        text = ""
        emotion = "neutral"
        events: List[str] = []

        if isinstance(item, dict):
            text = item.get("text", "")
            emo_raw = item.get("emotion", "")
            if emo_raw:
                emotion = self._EMOTION_MAP.get(emo_raw.upper(), "neutral")
            for ev in item.get("event", []):
                if ev in self._EVENT_TAGS:
                    events.append(ev.lower())
        elif isinstance(item, str):
            text = item
        else:
            text = str(item)

        for tag in ("<|HAPPY|>", "<|SAD|>", "<|ANGRY|>", "<|NEUTRAL|>",
                     "<|SURPRISED|>", "<|DISGUSTED|>", "<|FEARFUL|>"):
            if tag in text:
                emotion = tag.strip("<|>").lower()
                text = text.replace(tag, "")
        for tag in ("<|Laughter|>", "<|Applause|>", "<|Cry|>",
                     "<|Cough|>", "<|Sneeze|>", "<|Music|>"):
            if tag in text:
                events.append(tag.strip("<|>").lower())
                text = text.replace(tag, "")
        text = text.replace("<|nospeech|>", "").strip()
        for t in ("<|zh|>", "<|en|>", "<|ja|>", "<|ko|>", "<|yue|>"):
            text = text.replace(t, "")

        return STTResult(text=text.strip(), emotion=emotion, events=events)

    # ------------------------------------------------------------------
    #  Local sync backends
    # ------------------------------------------------------------------

    def _transcribe_local_sync(self, audio: np.ndarray) -> STTResult:
        if self._backend == "sensevoice-local":
            try:
                raw = self._model.generate(
                    input=audio,
                    language=self.language if self.language != "auto" else "",
                    use_itn=True,
                )
                return self._parse_sensevoice_local(raw)
            except Exception as e:
                logger.error(f"SenseVoice local error: {e}")
                return STTResult(text="")

        if self._backend == "faster-whisper":
            try:
                segments, _ = self._model.transcribe(
                    audio,
                    language=self.language if self.language != "auto" else None,
                    beam_size=5, vad_filter=True,
                )
                text = " ".join(s.text for s in segments).strip()
                return STTResult(text=text)
            except Exception as e:
                logger.error(f"faster-whisper error: {e}")
                return STTResult(text="")

        return STTResult(text="[mock — set DASHSCOPE_API_KEY for cloud STT]")

    # ------------------------------------------------------------------
    #  Streaming (faster-whisper only, local)
    # ------------------------------------------------------------------

    async def _stream_faster_whisper(
        self, audio: np.ndarray
    ) -> AsyncGenerator[STTResult, None]:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _worker():
            try:
                segments, _ = self._model.transcribe(
                    audio,
                    language=self.language if self.language != "auto" else None,
                    beam_size=3, vad_filter=True, word_timestamps=False,
                )
                for seg in segments:
                    text = seg.text.strip()
                    if text:
                        loop.call_soon_threadsafe(
                            queue.put_nowait, STTResult(text=text))
            except Exception as e:
                logger.error(f"Streaming STT error: {e}")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, _worker)
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item


# Backward-compatible alias
WhisperSTT = SpeechToText
