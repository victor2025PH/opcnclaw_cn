"""
Speech-to-Text module using Whisper.

Supports:
- transcribe()        — full-audio transcription (wait for result)
- transcribe_stream() — yield partial results as segments finish
"""

import asyncio
from typing import Optional, AsyncGenerator

import numpy as np
from loguru import logger


class WhisperSTT:
    """Whisper-based Speech-to-Text."""
    
    def __init__(
        self,
        model_name: str = "base",
        device: str = "auto",
        language: str = "en",
    ):
        self.model_name = model_name
        self.device = device
        self.language = language
        self.model = None
        self._backend = "mock"
        self._load_model()
    
    def _load_model(self):
        """Load the Whisper model."""
        # Try faster-whisper first
        try:
            from faster_whisper import WhisperModel
            
            if self.device == "auto":
                import torch
                if torch.cuda.is_available():
                    self.device = "cuda"
                    compute_type = "float16"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    self.device = "cpu"
                    compute_type = "int8"
                else:
                    self.device = "cpu"
                    compute_type = "int8"
            elif self.device == "cuda":
                compute_type = "float16"
            else:
                compute_type = "int8"
            
            logger.info(f"Loading faster-whisper {self.model_name} on {self.device}")
            self.model = WhisperModel(
                self.model_name,
                device=self.device if self.device != "mps" else "cpu",
                compute_type=compute_type,
            )
            self._backend = "faster-whisper"
            logger.info("✅ faster-whisper loaded")
            return
        except ImportError:
            logger.warning("faster-whisper not available")
        except Exception as e:
            logger.warning(f"faster-whisper failed: {e}")
        
        # Try openai-whisper
        try:
            import whisper
            
            if self.device == "auto":
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            
            logger.info(f"Loading openai-whisper {self.model_name}")
            self.model = whisper.load_model(self.model_name, device=self.device)
            self._backend = "openai-whisper"
            logger.info("✅ openai-whisper loaded")
            return
        except ImportError:
            logger.warning("openai-whisper not available")
        except Exception as e:
            logger.warning(f"openai-whisper failed: {e}")
        
        # Mock mode for testing
        logger.warning("⚠️ No STT backend - using mock mode")
        self._backend = "mock"
    
    async def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio to text (waits for full result)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio)

    async def transcribe_stream(
        self, audio: np.ndarray
    ) -> AsyncGenerator[str, None]:
        """
        Yield partial transcription results as segments complete.

        For faster-whisper: each *segment* is yielded as soon as it finishes.
        This provides real-time feedback — the caller sees text appear sentence
        by sentence rather than waiting for the entire audio to process.

        For openai-whisper / mock: falls back to a single final yield.
        """
        if self._backend == "faster-whisper":
            async for partial in self._stream_faster_whisper(audio):
                yield partial
        else:
            # Fallback: run full transcription and yield once
            result = await self.transcribe(audio)
            if result:
                yield result

    async def _stream_faster_whisper(
        self, audio: np.ndarray
    ) -> AsyncGenerator[str, None]:
        """
        Use faster-whisper's lazy segment iterator so each segment is sent
        to the caller immediately rather than collecting all segments first.
        """
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _worker():
            try:
                segments, _info = self.model.transcribe(
                    audio,
                    language=self.language,
                    beam_size=3,        # Slightly smaller for lower latency
                    vad_filter=True,
                    word_timestamps=False,
                )
                for seg in segments:
                    text = seg.text.strip()
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
            except Exception as e:
                logger.error(f"Streaming STT error: {e}")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        # Run the blocking Whisper work in a thread
        loop.run_in_executor(None, _worker)

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    def _transcribe_sync(self, audio: np.ndarray) -> str:
        """Synchronous full transcription."""
        if self._backend == "faster-whisper":
            segments, _info = self.model.transcribe(
                audio,
                language=self.language,
                beam_size=5,
                vad_filter=True,
            )
            return " ".join(seg.text for seg in segments).strip()

        elif self._backend == "openai-whisper":
            result = self.model.transcribe(audio, language=self.language)
            return result["text"].strip()

        else:
            logger.debug(f"Mock STT: received {len(audio)} samples")
            return "[Mock transcription - install whisper for real STT]"
