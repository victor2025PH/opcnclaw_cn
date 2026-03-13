"""
Speech-to-Speech (S2S) engine — end-to-end voice conversation.

Supports:
  1. GLM-4-Voice (Zhipu, 9B, open-source, Chinese+English)
  2. Future: Moshi (Kyutai, 160ms latency, full-duplex)

Eliminates the STT -> LLM -> TTS pipeline, achieving ~200ms latency
while preserving emotion, tone, and non-verbal cues.
"""

import asyncio
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

import numpy as np
from loguru import logger


class SpeechToSpeech:
    """End-to-end speech conversation engine."""

    def __init__(self, device: str = "auto"):
        self.device = device
        self._backend = "none"
        self._model = None
        self._tokenizer = None
        self._decoder = None
        self._resolved_device = self._resolve_device()
        self._load_model()

    @property
    def available(self) -> bool:
        return self._backend != "none"

    @property
    def backend_name(self) -> str:
        return self._backend

    def _resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                mem = torch.cuda.get_device_properties(0).total_mem
                if mem >= 8 * 1024**3:
                    return "cuda"
                logger.info(
                    f"GPU memory {mem / 1024**3:.1f}GB — "
                    "S2S needs 8GB+, skipping")
                return "skip"
        except ImportError:
            pass
        return "skip"

    def _load_model(self):
        if self._resolved_device == "skip":
            logger.info("S2S skipped — insufficient GPU memory")
            return

        if self._try_glm4voice():
            return
        logger.info("No S2S backend available")

    def _try_glm4voice(self) -> bool:
        try:
            from transformers import AutoModel as HFAutoModel, AutoTokenizer

            model_name = "THUDM/glm-4-voice-9b"
            logger.info("Loading GLM-4-Voice (9B) …")

            self._tokenizer = AutoTokenizer.from_pretrained(
                model_name, trust_remote_code=True)
            self._model = HFAutoModel.from_pretrained(
                model_name, trust_remote_code=True,
                device_map=self._resolved_device,
            )
            self._model.eval()

            try:
                from glm4voice.decoder import FlowMatchingDecoder
                self._decoder = FlowMatchingDecoder.from_pretrained(
                    "THUDM/glm-4-voice-decoder")
                self._decoder.to(self._resolved_device)
            except ImportError:
                logger.info("GLM-4-Voice decoder not available — text mode only")

            self._backend = "glm-4-voice"
            logger.info("GLM-4-Voice loaded (end-to-end speech)")
            return True
        except ImportError:
            logger.info("GLM-4-Voice deps not installed")
        except Exception as e:
            logger.warning(f"GLM-4-Voice load failed: {e}")
        return False

    async def chat(
        self,
        audio_input: np.ndarray,
        history: Optional[list] = None,
    ) -> AsyncGenerator[bytes, None]:
        """
        Process audio input end-to-end and yield audio response chunks.
        Falls back to text output if decoder not available.
        """
        if not self.available:
            return

        t0 = time.perf_counter()
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _worker():
            try:
                self._process_glm4voice(audio_input, history, queue, loop)
            except Exception as e:
                logger.error(f"S2S error: {e}")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, _worker)

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

        latency = (time.perf_counter() - t0) * 1000
        logger.debug(f"S2S latency: {latency:.0f}ms")

    def _process_glm4voice(self, audio, history, queue, loop):
        if self._backend != "glm-4-voice" or not self._model:
            return

        try:
            import torch

            audio_tensor = torch.from_numpy(audio).float()
            if audio_tensor.dim() == 1:
                audio_tensor = audio_tensor.unsqueeze(0)

            inputs = self._tokenizer(
                audio_tensor, return_tensors="pt",
                sampling_rate=16000)
            inputs = {k: v.to(self._resolved_device)
                      for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs, max_new_tokens=2000,
                    do_sample=True, temperature=0.7)

            if self._decoder:
                speech_tokens = outputs[:, inputs["input_ids"].shape[1]:]
                audio_out = self._decoder(speech_tokens)
                if hasattr(audio_out, "numpy"):
                    audio_out = audio_out.cpu().numpy()
                pcm = (audio_out * 32767).astype(np.int16).tobytes()
                loop.call_soon_threadsafe(queue.put_nowait, pcm)
            else:
                text = self._tokenizer.decode(
                    outputs[0], skip_special_tokens=True)
                loop.call_soon_threadsafe(
                    queue.put_nowait, text.encode("utf-8"))
        except Exception as e:
            logger.error(f"GLM-4-Voice processing error: {e}")

    def get_gpu_info(self) -> dict:
        try:
            import torch
            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                return {
                    "name": props.name,
                    "total_mem_gb": round(props.total_mem / 1024**3, 1),
                    "s2s_available": self.available,
                    "backend": self._backend,
                }
        except ImportError:
            pass
        return {"s2s_available": False, "backend": "none"}
