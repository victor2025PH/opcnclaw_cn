"""
Text-to-Speech module — cloud-first with emotion & voice cloning.

Backend priority (cloud-first, zero GPU):
  1. DashScope CosyVoice (Ali cloud, clone + emotion + streaming)
  2. GLM-TTS             (Zhipu cloud, streaming)
  3. Edge TTS            (Microsoft free, zero-config, zero-cost default)
  4. ElevenLabs          (cloud, English focus)
  --- Full installer only (local GPU) ---
  5. CosyVoice local     (GPU 4GB+)
  6. Fish Speech local    (GPU 4GB)
  7. mock
"""

import asyncio
import base64
import io
import json
import os
import wave
from pathlib import Path
from typing import AsyncGenerator, Optional

import numpy as np
from loguru import logger

CLONE_DIR = Path("data/voice_clones")
CLONE_DIR.mkdir(parents=True, exist_ok=True)


class TextToSpeech:
    """Unified TTS — cloud-first, local GPU optional for Full installs."""

    def __init__(
        self,
        voice_sample: Optional[str] = None,
        device: str = "auto",
        voice_id: Optional[str] = None,
        emotion: str = "neutral",
    ):
        self.voice_sample = voice_sample
        self.device = device
        self.voice_id = voice_id or "cgSgspJ2msm6clMCkdW9"
        self.emotion = emotion
        self.model = None
        self._backend = "mock"
        self._elevenlabs_client = None
        self._zhipu_api_key = None
        self._zhipu_voice = "female"
        self._edge_voice = os.environ.get("EDGE_TTS_VOICE",
                                           "zh-CN-XiaoxiaoNeural")
        self._dashscope_key: Optional[str] = None
        self._cosyvoice_voice = "longxiaochun"
        self._cosyvoice_model = None
        self._fish_model = None
        self._clone_audio_path: Optional[str] = None
        self._load_model()

    @property
    def audio_format(self) -> str:
        if self._backend == "edge-tts":
            return "mp3"
        return "pcm"

    @property
    def sample_rate(self) -> int:
        rates = {
            "dashscope-cosyvoice": 22050,
            "cosyvoice-local": 22050,
            "glm-tts": 24000,
            "elevenlabs": 24000,
            "edge-tts": 24000,
        }
        return rates.get(self._backend, 24000)

    @property
    def backend_name(self) -> str:
        return self._backend

    @property
    def is_cloud(self) -> bool:
        return self._backend in (
            "dashscope-cosyvoice", "glm-tts", "edge-tts", "elevenlabs")

    def set_emotion(self, emotion: str):
        self.emotion = emotion

    def set_clone_voice(self, audio_path: str):
        self._clone_audio_path = audio_path

    # ------------------------------------------------------------------
    #  Model loading (cloud-first priority)
    # ------------------------------------------------------------------

    def _load_model(self):
        if self._try_dashscope_cosyvoice():
            return

        # Edge TTS first: free, unlimited, stable MP3 output, no PCM conversion needed
        try:
            import edge_tts  # noqa: F401
            self._backend = "edge-tts"
            logger.info(f"Edge TTS ready — voice: {self._edge_voice}")
            # Also keep GLM-TTS key as backup
            zhipu_key = os.environ.get("ZHIPU_API_KEY")
            if zhipu_key:
                self._zhipu_api_key = zhipu_key
                self._zhipu_voice = os.environ.get("ZHIPU_TTS_VOICE", "female")
            return
        except ImportError:
            pass

        zhipu_key = os.environ.get("ZHIPU_API_KEY")
        if zhipu_key:
            self._zhipu_api_key = zhipu_key
            self._zhipu_voice = os.environ.get("ZHIPU_TTS_VOICE", "female")
            self._backend = "glm-tts"
            logger.info(f"GLM-TTS cloud ready — voice: {self._zhipu_voice}")
            return

        elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
        if elevenlabs_key:
            try:
                from elevenlabs import ElevenLabs
                self._elevenlabs_client = ElevenLabs(api_key=elevenlabs_key)
                self._backend = "elevenlabs"
                logger.info("ElevenLabs TTS cloud ready")
                return
            except (ImportError, Exception):
                pass

        if self._try_cosyvoice_local():
            return
        if self._try_fish_local():
            return

        logger.warning("No TTS backend — using mock")
        self._backend = "mock"

    def _try_dashscope_cosyvoice(self) -> bool:
        key = os.environ.get("DASHSCOPE_API_KEY")
        if not key:
            return False
        self._dashscope_key = key
        self._cosyvoice_voice = os.environ.get(
            "COSYVOICE_VOICE", "longxiaochun")
        self._backend = "dashscope-cosyvoice"
        logger.info(
            f"DashScope CosyVoice cloud ready — "
            f"voice: {self._cosyvoice_voice}")
        return True

    def _try_cosyvoice_local(self) -> bool:
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice as CV
            logger.info("Loading CosyVoice 2.0 local …")
            self._cosyvoice_model = CV("pretrained_models/CosyVoice2-0.5B",
                                       load_jit=False, fp16=True)
            self._backend = "cosyvoice-local"
            logger.info("CosyVoice 2.0 local loaded")
            return True
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"CosyVoice local failed: {e}")
        return False

    def _try_fish_local(self) -> bool:
        try:
            from fish_speech.inference import TTSInference
            self._fish_model = TTSInference.from_pretrained(
                device=self._get_device())
            self._backend = "fish-local"
            logger.info("Fish Speech local loaded")
            return True
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Fish Speech local failed: {e}")
        return False

    def _get_device(self) -> str:
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
    #  Emotion detection + prosody mapping
    # ------------------------------------------------------------------

    _EMOTION_TAGS = {
        "happy": "[laughter]", "sad": "[sigh]", "angry": "",
        "neutral": "", "gentle": "[soft]", "cheerful": "[laughter]",
        "calm": "[breath]",
    }

    _SSML_PROSODY = {
        "happy":    {"rate": "+10%",  "pitch": "+5%",   "volume": "+5dB"},
        "cheerful": {"rate": "+15%",  "pitch": "+8%",   "volume": "+5dB"},
        "sad":      {"rate": "-15%",  "pitch": "-5%",   "volume": "-3dB"},
        "angry":    {"rate": "+5%",   "pitch": "+3%",   "volume": "+8dB"},
        "gentle":   {"rate": "-10%",  "pitch": "-3%",   "volume": "-5dB"},
        "calm":     {"rate": "-8%",   "pitch": "-2%",   "volume": "-2dB"},
        "neutral":  {},
    }

    _EMOTION_KEYWORDS = {
        "happy":    ["哈哈", "太好了", "开心", "恭喜", "好棒", "太棒", "不错哦", "great", "awesome", "wonderful", "happy"],
        "cheerful": ["加油", "期待", "激动", "厉害", "amazing", "excited", "fantastic"],
        "sad":      ["抱歉", "遗憾", "可惜", "对不起", "sorry", "unfortunately", "sad"],
        "angry":    ["警告", "严重", "危险", "不要", "禁止", "warning", "danger"],
        "gentle":   ["别担心", "没关系", "慢慢来", "放心", "好好休息", "take care", "don't worry"],
        "calm":     ["建议", "总结", "分析", "来看看", "let me explain", "in summary"],
    }

    def detect_emotion(self, text: str) -> str:
        """Detect emotion from text content using keyword matching."""
        if not text:
            return "neutral"
        lower = text.lower()
        scores = {}
        for emotion, keywords in self._EMOTION_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in lower)
            if score > 0:
                scores[emotion] = score
        if scores:
            return max(scores, key=scores.get)
        return "neutral"

    def _apply_emotion(self, text: str) -> str:
        tag = self._EMOTION_TAGS.get(self.emotion, "")
        if tag and self._backend in (
                "cosyvoice-local", "fish-local", "dashscope-cosyvoice"):
            return f"{tag} {text}"
        return text

    def _wrap_ssml(self, text: str, emotion: str = "") -> str:
        """Wrap text in SSML with prosody for Edge TTS."""
        emo = emotion or self.emotion
        prosody = self._SSML_PROSODY.get(emo, {})
        if not prosody:
            return text
        attrs = " ".join(f'{k}="{v}"' for k, v in prosody.items())
        import xml.sax.saxutils as saxutils
        escaped = saxutils.escape(text)
        return (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">'
            f'<voice name="{self._edge_voice}">'
            f'<prosody {attrs}>{escaped}</prosody>'
            f'</voice></speak>'
        )

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    async def synthesize(self, text: str) -> np.ndarray:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._synthesize_sync, text)

    async def synthesize_stream(
        self, text: str, emotion: str = ""
    ) -> AsyncGenerator[bytes, None]:
        if not emotion:
            emotion = self.detect_emotion(text)
        self.emotion = emotion

        text = self._apply_emotion(text)

        if self._backend == "dashscope-cosyvoice":
            async for chunk in self._stream_dashscope(text):
                yield chunk
            return

        if self._backend == "cosyvoice-local":
            async for chunk in self._stream_cosyvoice_local(text):
                yield chunk
            return

        if self._backend == "glm-tts":
            async for chunk in self._stream_glm(text):
                yield chunk
            return

        if self._backend == "edge-tts":
            async for chunk in self._stream_edge(text, emotion):
                yield chunk
            return

        if self._backend == "elevenlabs":
            async for chunk in self._stream_elevenlabs(text):
                yield chunk
            return

        audio = await self.synthesize(text)
        yield audio.tobytes()

    # ------------------------------------------------------------------
    #  DashScope CosyVoice cloud streaming
    # ------------------------------------------------------------------

    async def _stream_dashscope(self, text: str) -> AsyncGenerator[bytes, None]:
        import httpx
        yield_count = 0
        try:
            payload = {
                "model": "cosyvoice-v1",
                "input": {"text": text},
                "parameters": {
                    "voice": self._cosyvoice_voice,
                    "format": "pcm",
                    "sample_rate": 22050,
                },
            }

            clone_path = self._clone_audio_path or self.voice_sample
            if clone_path and Path(clone_path).exists():
                audio_b64 = base64.b64encode(
                    Path(clone_path).read_bytes()).decode()
                payload["input"]["reference_audio"] = audio_b64
                payload["model"] = "cosyvoice-clone-v1"

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0)
            ) as client:
                async with client.stream(
                    "POST",
                    "https://dashscope.aliyuncs.com/api/v1/services/"
                    "audio/tts/synthesis",
                    headers={
                        "Authorization": f"Bearer {self._dashscope_key}",
                        "Content-Type": "application/json",
                        "X-DashScope-DataInspection": "enable",
                    },
                    json=payload,
                ) as resp:
                    if resp.status_code == 200:
                        async for chunk in resp.aiter_bytes(4096):
                            if chunk:
                                yield chunk
                                yield_count += 1
                    else:
                        body = await resp.aread()
                        logger.warning(
                            f"DashScope TTS HTTP {resp.status_code}: "
                            f"{body[:200]}")
        except Exception as e:
            logger.error(f"DashScope TTS error: {e}")

        if yield_count == 0:
            logger.warning("DashScope TTS returned nothing, falling back")
            async for chunk in self._stream_edge(text):
                yield chunk

    # ------------------------------------------------------------------
    #  CosyVoice local streaming (Full installer only)
    # ------------------------------------------------------------------

    async def _stream_cosyvoice_local(
        self, text: str
    ) -> AsyncGenerator[bytes, None]:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _worker():
            try:
                model = self._cosyvoice_model
                clone = self._clone_audio_path or self.voice_sample
                if clone and Path(clone).exists():
                    gen = model.inference_zero_shot(
                        text, "", clone, stream=True)
                else:
                    gen = model.inference_sft(
                        text, "Chinese Female", stream=True)
                for chunk in gen:
                    pcm = chunk["tts_speech"]
                    if hasattr(pcm, "numpy"):
                        pcm = pcm.numpy()
                    data = (pcm * 32767).astype(np.int16).tobytes()
                    loop.call_soon_threadsafe(queue.put_nowait, data)
            except Exception as e:
                logger.error(f"CosyVoice local error: {e}")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, _worker)
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    # ------------------------------------------------------------------
    #  GLM-TTS cloud streaming
    # ------------------------------------------------------------------

    async def _stream_glm(self, text: str) -> AsyncGenerator[bytes, None]:
        import httpx
        yield_count = 0
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0)
            ) as client:
                async with client.stream(
                    "POST",
                    "https://open.bigmodel.cn/api/paas/v4/audio/speech",
                    json={
                        "model": "glm-tts", "input": text,
                        "voice": self._zhipu_voice, "stream": True,
                        "response_format": "pcm", "encode_format": "base64",
                        "speed": 1.0, "volume": 1.0,
                    },
                    headers={
                        "Authorization": f"Bearer {self._zhipu_api_key}",
                        "Content-Type": "application/json",
                    },
                ) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            try:
                                data = json.loads(line[5:].strip())
                                for ch in data.get("choices", []):
                                    if ch.get("finish_reason") == "stop":
                                        continue
                                    content = ch.get("delta", {}).get(
                                        "content")
                                    if content:
                                        yield base64.b64decode(content)
                                        yield_count += 1
                            except (json.JSONDecodeError, Exception):
                                pass
        except Exception as e:
            logger.error(f"GLM-TTS error: {e}")
        if yield_count < 3:
            logger.info(f"GLM-TTS insufficient data ({yield_count} chunks), falling back to Edge TTS")
            async for chunk in self._stream_edge(text):
                yield chunk

    # ------------------------------------------------------------------
    #  语言检测 + 多语言声音自动切换
    # ------------------------------------------------------------------

    # Edge TTS 多语言声音映射
    _LANG_VOICES = {
        "zh": "zh-CN-XiaoxiaoNeural",      # 中文女声
        "en": "en-US-JennyNeural",          # 英文女声
        "ja": "ja-JP-NanamiNeural",         # 日文女声
        "ko": "ko-KR-SunHiNeural",         # 韩文女声
        "fr": "fr-FR-DeniseNeural",         # 法文女声
        "de": "de-DE-KatjaNeural",          # 德文女声
        "es": "es-ES-ElviraNeural",         # 西班牙文女声
        "ru": "ru-RU-SvetlanaNeural",       # 俄文女声
    }

    def _detect_voice_for_text(self, text: str) -> str:
        """检测文本语种，自动选择对应 Edge TTS 声音

        规则：
          - 50%+ CJK 字符 → 中文
          - 50%+ 日文假名 → 日文
          - 50%+ 韩文 → 韩文
          - 其他 → 用户配置的默认声音
          - 混合文本：按多数语种决定
        """
        if not text or len(text.strip()) < 3:
            return self._edge_voice

        # 统计各语种字符数
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        ja_kana = sum(1 for c in text if '\u3040' <= c <= '\u30ff' or '\u31f0' <= c <= '\u31ff')
        ko = sum(1 for c in text if '\uac00' <= c <= '\ud7af')
        alpha = sum(1 for c in text if c.isascii() and c.isalpha())
        total = max(cjk + ja_kana + ko + alpha, 1)

        if ja_kana / total > 0.3:
            return self._LANG_VOICES["ja"]
        if ko / total > 0.3:
            return self._LANG_VOICES["ko"]
        if cjk / total > 0.3:
            return self._LANG_VOICES["zh"]
        if alpha / total > 0.5:
            return self._LANG_VOICES["en"]

        return self._edge_voice  # 默认使用用户配置

    # ------------------------------------------------------------------
    #  Edge TTS (free cloud default)
    # ------------------------------------------------------------------

    async def _stream_edge(self, text: str, emotion: str = "neutral") -> AsyncGenerator[bytes, None]:
        try:
            import edge_tts
            # 多语言自动切换：检测文本语种 → 选择对应声音
            voice = self._detect_voice_for_text(text)
            if emotion and emotion != "neutral":
                ssml = self._wrap_ssml(text, emotion)
                communicate = edge_tts.Communicate(ssml, voice)
            else:
                communicate = edge_tts.Communicate(text, voice)
            mp3_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_data += chunk["data"]
            if mp3_data:
                yield mp3_data
        except Exception as e:
            logger.error(f"Edge TTS error: {e}")
            if emotion != "neutral":
                logger.debug("Retrying Edge TTS without SSML prosody")
                try:
                    import edge_tts
                    comm = edge_tts.Communicate(text, self._edge_voice)
                    mp3 = b""
                    async for c in comm.stream():
                        if c["type"] == "audio":
                            mp3 += c["data"]
                    if mp3:
                        yield mp3
                except Exception:
                    pass

    # ------------------------------------------------------------------
    #  ElevenLabs cloud
    # ------------------------------------------------------------------

    async def _stream_elevenlabs(
        self, text: str
    ) -> AsyncGenerator[bytes, None]:
        try:
            gen = self._elevenlabs_client.text_to_speech.convert(
                voice_id=self.voice_id, text=text,
                model_id="eleven_turbo_v2_5", output_format="pcm_24000",
            )
            for chunk in gen:
                yield chunk
        except Exception as e:
            logger.error(f"ElevenLabs error: {e}")

    # ------------------------------------------------------------------
    #  Sync synthesis
    # ------------------------------------------------------------------

    def _synthesize_sync(self, text: str) -> np.ndarray:
        text = self._apply_emotion(text)

        if self._backend == "glm-tts":
            return self._synth_glm(text)
        if self._backend == "elevenlabs":
            return self._synth_elevenlabs(text)
        if self._backend == "cosyvoice-local":
            return self._synth_cosyvoice_local(text)
        if self._backend == "fish-local":
            return self._synth_fish_local(text)
        return np.zeros(12000, dtype=np.float32)

    def _synth_glm(self, text: str) -> np.ndarray:
        import httpx
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    "https://open.bigmodel.cn/api/paas/v4/audio/speech",
                    json={"model": "glm-tts", "input": text,
                          "voice": self._zhipu_voice,
                          "response_format": "wav"},
                    headers={
                        "Authorization": f"Bearer {self._zhipu_api_key}",
                        "Content-Type": "application/json"},
                )
                if resp.status_code == 200 and len(resp.content) > 44:
                    with wave.open(io.BytesIO(resp.content), 'rb') as wf:
                        frames = wf.readframes(wf.getnframes())
                        arr = np.frombuffer(frames, dtype=np.int16)
                        return arr.astype(np.float32) / 32768.0
        except Exception as e:
            logger.error(f"GLM-TTS sync error: {e}")
        return np.zeros(12000, dtype=np.float32)

    def _synth_elevenlabs(self, text: str) -> np.ndarray:
        try:
            gen = self._elevenlabs_client.text_to_speech.convert(
                voice_id=self.voice_id, text=text,
                model_id="eleven_turbo_v2_5", output_format="pcm_24000",
            )
            raw = b"".join(gen)
            arr = np.frombuffer(raw, dtype=np.int16)
            return arr.astype(np.float32) / 32768.0
        except Exception as e:
            logger.error(f"ElevenLabs sync error: {e}")
            return np.zeros(16000, dtype=np.float32)

    def _synth_cosyvoice_local(self, text: str) -> np.ndarray:
        try:
            model = self._cosyvoice_model
            clone = self._clone_audio_path or self.voice_sample
            if clone and Path(clone).exists():
                result = model.inference_zero_shot(text, "", clone)
            else:
                result = model.inference_sft(text, "Chinese Female")
            pcm = next(iter(result))["tts_speech"]
            if hasattr(pcm, "numpy"):
                pcm = pcm.numpy()
            return pcm.astype(np.float32)
        except Exception as e:
            logger.error(f"CosyVoice local sync error: {e}")
            return np.zeros(12000, dtype=np.float32)

    def _synth_fish_local(self, text: str) -> np.ndarray:
        try:
            clone = self._clone_audio_path or self.voice_sample
            if clone and Path(clone).exists():
                audio = self._fish_model.synthesize(
                    text, reference_audio=clone)
            else:
                audio = self._fish_model.synthesize(text)
            if hasattr(audio, "numpy"):
                audio = audio.numpy()
            return audio.astype(np.float32)
        except Exception as e:
            logger.error(f"Fish Speech local error: {e}")
            return np.zeros(12000, dtype=np.float32)

    # ------------------------------------------------------------------
    #  Voice clone management
    # ------------------------------------------------------------------

    @staticmethod
    def list_cloned_voices() -> list:
        voices = []
        for f in CLONE_DIR.glob("*.wav"):
            voices.append({"id": f.stem, "path": str(f), "name": f.stem})
        for f in CLONE_DIR.glob("*.mp3"):
            voices.append({"id": f.stem, "path": str(f), "name": f.stem})
        return voices

    @staticmethod
    def save_clone_sample(name: str, audio_data: bytes,
                          fmt: str = "wav") -> str:
        path = CLONE_DIR / f"{name}.{fmt}"
        path.write_bytes(audio_data)
        logger.info(f"Voice clone sample saved: {path}")
        return str(path)


# Backward-compatible alias
ChatterboxTTS = TextToSpeech
