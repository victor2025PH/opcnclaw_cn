"""
Text-to-Speech module using GLM-TTS, Edge TTS, ElevenLabs, Chatterbox, or fallbacks.
"""

import asyncio
import base64
import io
import json
import os
import wave
from typing import Optional, AsyncGenerator
from pathlib import Path

import numpy as np
from loguru import logger


class ChatterboxTTS:
    """Text-to-Speech with multiple backends. Priority: GLM-TTS > Edge TTS > ElevenLabs > Chatterbox > XTTS > mock."""
    
    def __init__(
        self,
        voice_sample: Optional[str] = None,
        device: str = "auto",
        voice_id: Optional[str] = None,
    ):
        self.voice_sample = voice_sample
        self.device = device
        self.voice_id = voice_id or "cgSgspJ2msm6clMCkdW9"
        self.model = None
        self._backend = "mock"
        self._elevenlabs_client = None
        self._zhipu_api_key = None
        self._zhipu_voice = "female"
        self._edge_voice = "zh-CN-XiaoxiaoNeural"
        self._load_model()

    @property
    def audio_format(self) -> str:
        """Return output audio format: 'pcm' or 'mp3'."""
        if self._backend == "edge-tts":
            return "mp3"
        return "pcm"
    
    def _load_model(self):
        """Load the TTS model."""
        # Try GLM-TTS first (智谱, cloud, Chinese-optimized, streaming)
        zhipu_key = os.environ.get("ZHIPU_API_KEY")
        if zhipu_key:
            self._zhipu_api_key = zhipu_key
            self._zhipu_voice = os.environ.get("ZHIPU_TTS_VOICE", "female")
            self._backend = "glm-tts"
            logger.info(f"✅ GLM-TTS (智谱) ready — voice: {self._zhipu_voice}")
            return

        # Try Edge TTS (Microsoft, free, excellent Chinese support)
        try:
            import edge_tts
            self._edge_voice = os.environ.get("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
            self._backend = "edge-tts"
            logger.info(f"✅ Edge TTS ready — voice: {self._edge_voice}")
            return
        except ImportError:
            logger.warning("edge-tts not installed")

        # Try ElevenLabs (cloud, high quality)
        elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
        if elevenlabs_key:
            try:
                from elevenlabs import ElevenLabs
                self._elevenlabs_client = ElevenLabs(api_key=elevenlabs_key)
                self._backend = "elevenlabs"
                logger.info("✅ ElevenLabs TTS ready")
                return
            except ImportError:
                logger.warning("ElevenLabs SDK not installed")
            except Exception as e:
                logger.warning(f"ElevenLabs failed: {e}")
        
        # Try Chatterbox (self-hosted)
        try:
            from chatterbox.tts import ChatterboxTTS as CBModel
            logger.info("Loading Chatterbox TTS...")
            self.model = CBModel.from_pretrained(device=self._get_device())
            self._backend = "chatterbox"
            logger.info("✅ Chatterbox loaded")
            return
        except ImportError:
            logger.warning("Chatterbox not installed")
        except Exception as e:
            logger.warning(f"Chatterbox failed: {e}")
        
        # Try XTTS
        try:
            from TTS.api import TTS
            logger.info("Loading Coqui XTTS...")
            self.model = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
            self._backend = "xtts"
            logger.info("✅ XTTS loaded")
            return
        except ImportError:
            logger.warning("Coqui TTS not installed")
        except Exception as e:
            logger.warning(f"XTTS failed: {e}")
        
        # Mock mode
        logger.warning("⚠️ No TTS backend - using mock mode (silence)")
        self._backend = "mock"
    
    def _get_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"
    
    async def synthesize(self, text: str) -> np.ndarray:
        """Synthesize speech from text. Returns float32 numpy array."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._synthesize_sync, text)
    
    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Stream synthesized audio chunks.
        
        Yields:
            Raw audio bytes. Format depends on self.audio_format:
            - 'pcm': 24kHz 16-bit signed int PCM
            - 'mp3': MP3 encoded audio
        """
        if self._backend == "glm-tts":
            yield_count = 0
            import httpx
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                    async with client.stream(
                        "POST",
                        "https://open.bigmodel.cn/api/paas/v4/audio/speech",
                        json={
                            "model": "glm-tts",
                            "input": text,
                            "voice": self._zhipu_voice,
                            "stream": True,
                            "response_format": "pcm",
                            "encode_format": "base64",
                            "speed": 1.0,
                            "volume": 1.0,
                        },
                        headers={
                            "Authorization": f"Bearer {self._zhipu_api_key}",
                            "Content-Type": "application/json",
                        },
                    ) as response:
                        if response.status_code != 200:
                            body = await response.aread()
                            logger.warning(f"GLM-TTS HTTP {response.status_code}: {body[:200]}")
                        else:
                            async for line in response.aiter_lines():
                                line = line.strip()
                                if not line.startswith("data:"):
                                    continue
                                data_str = line[5:].strip()
                                try:
                                    data = json.loads(data_str)
                                    for choice in data.get("choices", []):
                                        if choice.get("finish_reason") == "stop":
                                            continue
                                        content = choice.get("delta", {}).get("content")
                                        if content:
                                            yield base64.b64decode(content)
                                            yield_count += 1
                                except json.JSONDecodeError:
                                    pass
                                except Exception as e:
                                    logger.debug(f"GLM-TTS chunk: {e}")
            except Exception as e:
                logger.error(f"GLM-TTS streaming error: {e}")

            # If GLM-TTS returned nothing (e.g. billing issue), fall back to Edge TTS
            if yield_count == 0:
                logger.warning("GLM-TTS returned no audio, falling back to Edge TTS")
                try:
                    import edge_tts
                    communicate = edge_tts.Communicate(text, self._edge_voice)
                    mp3_data = b""
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            mp3_data += chunk["data"]
                    if mp3_data:
                        self._backend = "edge-tts"
                        yield mp3_data
                except Exception as e2:
                    logger.error(f"Edge TTS fallback also failed: {e2}")

        elif self._backend == "edge-tts":
            try:
                import edge_tts
                communicate = edge_tts.Communicate(text, self._edge_voice)
                mp3_data = b""
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        mp3_data += chunk["data"]
                if mp3_data:
                    yield mp3_data
            except Exception as e:
                logger.error(f"Edge TTS error: {e}")

        elif self._backend == "elevenlabs":
            try:
                audio_generator = self._elevenlabs_client.text_to_speech.convert(
                    voice_id=self.voice_id,
                    text=text,
                    model_id="eleven_turbo_v2_5",
                    output_format="pcm_24000",
                )
                for chunk in audio_generator:
                    yield chunk
            except Exception as e:
                logger.error(f"ElevenLabs streaming error: {e}")
        else:
            # Non-streaming fallback (Chatterbox / XTTS / mock)
            audio = await self.synthesize(text)
            yield audio.tobytes()
    
    def _synthesize_sync(self, text: str) -> np.ndarray:
        """Synchronous synthesis. Returns float32 numpy array."""
        if self._backend == "glm-tts":
            import httpx
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(
                        "https://open.bigmodel.cn/api/paas/v4/audio/speech",
                        json={
                            "model": "glm-tts",
                            "input": text,
                            "voice": self._zhipu_voice,
                            "response_format": "wav",
                            "speed": 1.0,
                            "volume": 1.0,
                        },
                        headers={
                            "Authorization": f"Bearer {self._zhipu_api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                    if response.status_code == 200 and len(response.content) > 44:
                        with wave.open(io.BytesIO(response.content), 'rb') as wf:
                            frames = wf.readframes(wf.getnframes())
                            audio_array = np.frombuffer(frames, dtype=np.int16)
                            return audio_array.astype(np.float32) / 32768.0
                    else:
                        logger.warning(f"GLM-TTS sync: HTTP {response.status_code}")
            except Exception as e:
                logger.error(f"GLM-TTS sync error: {e}")
            return np.zeros(12000, dtype=np.float32)

        elif self._backend == "elevenlabs":
            try:
                audio_generator = self._elevenlabs_client.text_to_speech.convert(
                    voice_id=self.voice_id,
                    text=text,
                    model_id="eleven_turbo_v2_5",
                    output_format="pcm_24000",
                )
                audio_bytes = b"".join(audio_generator)
                audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
                return audio_array.astype(np.float32) / 32768.0
            except Exception as e:
                logger.error(f"ElevenLabs TTS error: {e}")
                return np.zeros(16000, dtype=np.float32)
        
        elif self._backend == "chatterbox":
            if self.voice_sample:
                audio = self.model.generate(text, audio_prompt=self.voice_sample)
            else:
                audio = self.model.generate(text)
            return audio.cpu().numpy().astype(np.float32)
        
        elif self._backend == "xtts":
            if self.voice_sample:
                wav = self.model.tts(text=text, speaker_wav=self.voice_sample, language="en")
            else:
                wav = self.model.tts(text=text, language="en")
            return np.array(wav, dtype=np.float32)
        
        else:
            logger.debug(f"Mock TTS: '{text[:50]}...'")
            return np.zeros(12000, dtype=np.float32)
