# -*- coding: utf-8 -*-
"""Voice / STT / TTS / WebSocket routes"""
from __future__ import annotations
import asyncio, base64, json, os, re, time
from typing import Optional

import httpx
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from ..text_utils import clean_for_speech
from .. import memory as mem_store
from ..auth import token_manager, APIKey
from ..stt import WhisperSTT, STTResult
from ..emotion import EmotionEngine

router = APIRouter()

_emotion = EmotionEngine()


def _get_globals():
    """Lazy access to globals set by main.py startup"""
    from ..main import stt, tts, backend, vad, settings, app
    return stt, tts, backend, vad, settings, app


# ---------------------------------------------------------------------------
# IM bridge (best-effort import, same as main.py)
# ---------------------------------------------------------------------------
try:
    from src.bridge.manager import get_bridge_manager as _get_bridge_mgr
    _bridge_manager = _get_bridge_mgr()
    _IM_BRIDGE_AVAILABLE = True
except Exception:
    _bridge_manager = None
    _IM_BRIDGE_AVAILABLE = False


# ===== POST /api/tts =====

@router.post("/api/tts")
async def tts_api(request: Request):
    """Convert text to speech audio and return as streaming response."""
    stt, tts, backend, vad, settings, app = _get_globals()
    body = await request.json()
    text = body.get("text", "").strip()
    if not text or not tts:
        return Response(content="", status_code=400)

    async def audio_stream():
        async for chunk in tts.synthesize_stream(text):
            b64 = base64.b64encode(chunk).decode()
            yield f"data: {json.dumps({'audio': b64, 'format': tts.audio_format})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        audio_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ===== POST /api/voice =====

@router.post("/api/voice")
async def voice_http(request: Request):
    """HTTP-based voice: receive audio → STT → AI → TTS, all via SSE.
    Fallback for when WebSocket (wss://) fails on iOS with self-signed certs."""
    stt, tts, backend, vad, settings, app = _get_globals()
    body = await request.json()
    audio_b64 = body.get("audio", "")
    image_b64: Optional[str] = body.get("image")  # optional camera frame

    if not audio_b64:
        return Response(content=json.dumps({"error": "No audio data"}), status_code=400)

    audio_bytes = base64.b64decode(audio_b64)
    audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
    logger.info(f"HTTP voice: {len(audio_np)} samples, max={np.abs(audio_np).max():.4f}")

    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    gateway_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

    async def voice_stream():
        # 1. STT
        stt_result = await stt.transcribe(audio_np)
        transcript = stt_result.text if isinstance(stt_result, STTResult) else str(stt_result)
        _emotion.process_stt_result(
            getattr(stt_result, "emotion", "neutral"),
            getattr(stt_result, "events", None),
        )
        yield f"data: {json.dumps({'type': 'transcript', 'text': transcript})}\n\n"
        if stt_result.emotion != "neutral" if isinstance(stt_result, STTResult) else False:
            yield f"data: {json.dumps({'type': 'emotion', 'emotion': stt_result.emotion})}\n\n"
        if image_b64:
            yield f"data: {json.dumps({'type': 'vision_used', 'value': True})}\n\n"

        if not transcript.strip():
            yield f"data: {json.dumps({'type': 'done', 'empty': True})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # 2. AI response (streaming) with emotion-aware prompt
        full_response = ""
        sentence_buffer = ""
        emo_tts = _emotion.get_tts_emotion()
        if tts and emo_tts != "neutral":
            tts.set_emotion(emo_tts)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                sys_prompt = "你是 OpenClaw AI 助手，用中文简洁回答。"
                emotion_addon = _emotion.get_system_prompt_addon()
                if emotion_addon:
                    sys_prompt += f"\n\n【情感提示】{emotion_addon}"
                if image_b64:
                    sys_prompt += "\n\n用户发送了摄像头画面，请结合图像内容来回答，说明你看到了什么。"
                user_content = transcript if not image_b64 else [
                    {"type": "text", "text": transcript},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}",
                        "detail": "low",
                    }},
                ]
                async with client.stream(
                    "POST",
                    f"{gateway_url}/v1/chat/completions",
                    json={
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "model": "deepseek-chat",
                        "stream": True,
                    },
                    headers={
                        "Authorization": f"Bearer {gateway_token}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data)
                            delta = parsed.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                full_response += delta
                                sentence_buffer += delta
                                yield f"data: {json.dumps({'type': 'text', 'text': delta})}\n\n"

                                # TTS sentence by sentence
                                seps = ['。', '！', '？', '；', '.\n', '!\n', '?\n', '\n\n']
                                while any(sep in sentence_buffer for sep in seps):
                                    earliest = len(sentence_buffer)
                                    for sep in seps:
                                        idx = sentence_buffer.find(sep)
                                        if idx != -1 and idx < earliest:
                                            earliest = idx + len(sep)
                                    if earliest < len(sentence_buffer):
                                        sentence = sentence_buffer[:earliest].strip()
                                        sentence_buffer = sentence_buffer[earliest:]
                                        speech = clean_for_speech(sentence)
                                        if speech:
                                            async for audio_chunk in tts.synthesize_stream(speech):
                                                yield f"data: {json.dumps({'type': 'audio', 'data': base64.b64encode(audio_chunk).decode(), 'format': tts.audio_format})}\n\n"
                        except json.JSONDecodeError:
                            continue

            # TTS remaining text
            remaining = clean_for_speech(sentence_buffer.strip())
            if remaining:
                async for audio_chunk in tts.synthesize_stream(remaining):
                    yield f"data: {json.dumps({'type': 'audio', 'data': base64.b64encode(audio_chunk).decode(), 'format': tts.audio_format})}\n\n"

        except Exception as e:
            logger.error(f"HTTP voice AI error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'text': full_response})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        voice_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ===== POST /api/chat =====

@router.post("/api/chat")
async def chat_completions_proxy(request: Request):
    """Proxy chat completions to OpenClaw Gateway with SSE streaming."""
    body = await request.json()

    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    gateway_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

    if "stream" not in body:
        body["stream"] = True

    async def event_stream():
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{gateway_url}/v1/chat/completions",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {gateway_token}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.strip():
                            yield f"{line}\n\n"
            except Exception as e:
                logger.error(f"Chat proxy error: {e}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===== POST /api/vision =====

class VisionRequest(BaseModel):
    text: str
    image_b64: Optional[str] = None

@router.post("/api/vision")
async def vision_chat(req: VisionRequest):
    """Text + optional camera image → streaming AI response (SSE).
    Routes through Zhipu GLM-4V when image present and vision key configured."""
    stt, tts, backend, vad, settings, app = _get_globals()
    if not backend:
        return Response("Server initializing", status_code=503)

    async def event_stream():
        try:
            async for chunk in backend.chat_stream(req.text, image_b64=req.image_b64):
                data = json.dumps({
                    "choices": [{"delta": {"content": chunk}, "finish_reason": None}]
                })
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Vision chat error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ===== GET /api/history, DELETE /api/history, GET /api/history/sessions =====

@router.get("/api/history")
async def get_history(session: str = "default", limit: int = 50):
    """Return conversation history for a session."""
    try:
        msgs = mem_store.get_history_raw(session, limit=limit)
        return {"session": session, "messages": msgs, "count": len(msgs)}
    except Exception as e:
        logger.error(f"History fetch error: {e}")
        return {"session": session, "messages": [], "count": 0, "error": str(e)}

@router.delete("/api/history")
async def clear_history(session: str = "default"):
    """Clear conversation history for a session."""
    stt, tts, backend, vad, settings, app = _get_globals()
    try:
        deleted = mem_store.clear_history(session)
        # Also clear in-memory cache in the backend
        if backend:
            backend.clear_history()
        return {"ok": True, "deleted": deleted, "session": session}
    except Exception as e:
        logger.error(f"History clear error: {e}")
        return {"ok": False, "error": str(e)}

@router.get("/api/history/sessions")
async def list_history_sessions():
    """List all sessions with message counts."""
    try:
        sessions = mem_store.list_sessions()
        return {"sessions": sessions}
    except Exception as e:
        return {"sessions": [], "error": str(e)}


# ===== POST /api/stt-model, GET /api/stt-model =====

class STTModelRequest(BaseModel):
    model: str  # tiny / base / small / medium / large-v3-turbo

@router.post("/api/stt-model")
async def switch_stt_model(req: STTModelRequest):
    """Hot-switch the Whisper STT model (reloads the model immediately)."""
    stt, tts, backend, vad, settings, app = _get_globals()
    # We need to write back the new stt to main module
    import src.server.main as _main
    VALID_MODELS = {"tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"}
    if req.model not in VALID_MODELS:
        return {"ok": False, "error": f"Invalid model. Valid: {sorted(VALID_MODELS)}"}
    try:
        logger.info(f"Switching STT model: {stt.model_name} → {req.model}")
        new_stt = WhisperSTT(
            model_name=req.model,
            device=settings.stt_device,
            language=settings.stt_language,
        )
        _main.stt = new_stt
        logger.info(f"✅ STT model switched to: {req.model}")
        return {"ok": True, "model": req.model, "backend": new_stt._backend}
    except Exception as e:
        logger.error(f"STT model switch failed: {e}")
        return {"ok": False, "error": str(e)}

@router.get("/api/stt-model")
async def get_stt_model():
    """Return current STT model info."""
    stt, tts, backend, vad, settings, app = _get_globals()
    if not stt:
        return {"model": None, "backend": None}
    return {"model": stt.model_name, "backend": stt._backend}


# ===== GET /api/skills =====

@router.get("/api/skills")
async def get_skills_catalog():
    """返回所有技能的分类列表（供技能中心 UI 使用）"""
    import json as _json
    from pathlib import Path as _Path
    skills_dir = _Path(__file__).parent.parent.parent.parent / "skills"
    categories = []
    for meta_file in sorted(skills_dir.rglob("_meta.json")):
        try:
            meta = _json.loads(meta_file.read_text(encoding="utf-8"))
            categories.append({
                "id": meta.get("category", ""),
                "name": meta.get("name", ""),
                "description": meta.get("description", ""),
                "skills": meta.get("skills", []),
            })
        except Exception:
            pass
    total = sum(len(c["skills"]) for c in categories)
    return {"categories": categories, "total": total}


# ===== POST /api/stats/record, GET /api/stats/skills =====

@router.post("/api/stats/record")
async def record_skill_stat(data: dict):
    """记录技能调用统计"""
    try:
        from src.server.stats import record_usage
        record_usage(
            skill_id=data.get("skill_id", ""),
            session_id=data.get("session_id"),
            user_input=data.get("input", ""),
            success=data.get("success", True),
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/stats/skills")
async def get_skill_stats():
    """获取技能使用统计（热度排行）"""
    try:
        from src.server.stats import get_skill_stats as _get_stats, get_recent_skills, get_summary
        return {
            "top": _get_stats(20),
            "recent": get_recent_skills(5),
            "summary": get_summary(),
        }
    except Exception as e:
        return {"top": [], "recent": [], "summary": {}, "error": str(e)}


# ===== GET /api/emotion/state =====

@router.get("/api/emotion/state")
async def get_emotion_state():
    """Return current detected emotion state."""
    return {
        "current": _emotion.state.current,
        "dominant": _emotion.state.dominant,
        "history": _emotion.state.history[-5:],
        "enabled": _emotion.enabled,
    }


@router.post("/api/emotion/toggle")
async def toggle_emotion(request: Request):
    """Enable/disable emotion-aware mode."""
    body = await request.json()
    _emotion.enabled = bool(body.get("enabled", True))
    return {"ok": True, "enabled": _emotion.enabled}


# ===== WEBSOCKET /ws and /voice/ws =====

@router.websocket("/ws")
@router.websocket("/voice/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle voice WebSocket connections."""
    stt, tts, backend, vad, settings, app = _get_globals()

    # Check for API key in query params or headers
    api_key_str = websocket.query_params.get("api_key") or \
                  websocket.headers.get("x-api-key")
    
    api_key: Optional[APIKey] = None
    
    if settings.require_auth:
        if not api_key_str:
            await websocket.close(code=4001, reason="API key required")
            return
        
        api_key = token_manager.validate_key(api_key_str)
        if not api_key:
            await websocket.close(code=4002, reason="Invalid API key")
            return
        
        if not token_manager.check_rate_limit(api_key):
            await websocket.close(code=4003, reason="Rate limit exceeded")
            return
        
        logger.info(f"Client connected: {api_key.name} (tier={api_key.tier})")
    else:
        # Dev mode - allow all
        if api_key_str:
            api_key = token_manager.validate_key(api_key_str)
        logger.info("Client connected (auth disabled)")
    
    await websocket.accept()
    
    audio_buffer = []
    is_listening = False
    session_start = None
    pending_image: Optional[str] = None  # camera frame waiting for stop_listening

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg["type"] == "image_frame":
                # Client sends camera frame just before stop_listening
                pending_image = msg.get("data")
                logger.debug(f"Image frame queued ({len(pending_image or '') // 1024}KB b64)")

            elif msg["type"] == "start_listening":
                is_listening = True
                audio_buffer = []
                await websocket.send_json({"type": "listening_started"})
                logger.debug("Started listening")
                
            elif msg["type"] == "stop_listening":
                is_listening = False
                
                if audio_buffer:
                    # Combine audio chunks
                    audio_data = np.concatenate(audio_buffer)
                    
                    # Stream transcription — send partial results as segments arrive
                    logger.debug("Transcribing audio (streaming)...")
                    transcript_parts = []
                    last_emotion = "neutral"
                    last_events = []
                    async for partial in stt.transcribe_stream(audio_data):
                        text = partial.text if isinstance(partial, STTResult) else str(partial)
                        if isinstance(partial, STTResult):
                            last_emotion = partial.emotion
                            last_events = partial.events
                        transcript_parts.append(text)
                        await websocket.send_json({
                            "type": "transcript",
                            "text": text,
                            "partial": True,
                            "accumulated": " ".join(transcript_parts),
                        })

                    transcript = " ".join(transcript_parts).strip()

                    _emotion.process_stt_result(last_emotion, last_events)
                    if last_emotion != "neutral":
                        await websocket.send_json({
                            "type": "emotion",
                            "emotion": last_emotion,
                            "dominant": _emotion.state.dominant,
                        })

                    # Send final complete transcript
                    await websocket.send_json({
                        "type": "transcript",
                        "text": transcript,
                        "final": True,
                    })
                    logger.info(f"Transcript: {transcript}")
                    
                    if not transcript.strip():
                        await websocket.send_json({
                            "type": "response_complete",
                            "text": "",
                            "empty_transcript": True,
                        })
                    
                    if transcript.strip():
                        # Stream AI response with progressive TTS
                        has_image = bool(pending_image)
                        logger.debug(f"Streaming AI response (vision={has_image}, emotion={_emotion.state.dominant})...")

                        full_response = ""
                        sentence_buffer = ""
                        audio_chunks = []

                        emo_tts = _emotion.get_tts_emotion()
                        if tts and emo_tts != "neutral":
                            tts.set_emotion(emo_tts)

                        event_resp = _emotion.get_event_response()
                        if event_resp:
                            await websocket.send_json({
                                "type": "response_chunk",
                                "text": event_resp + "\n",
                            })
                            full_response += event_resp + "\n"

                        if has_image:
                            await websocket.send_json({"type": "vision_used", "value": True})

                        async for chunk in backend.chat_stream(transcript, image_b64=pending_image):
                            full_response += chunk
                            sentence_buffer += chunk
                            
                            # Send text chunk for progressive display
                            await websocket.send_json({
                                "type": "response_chunk",
                                "text": chunk,
                            })
                            
                            # Check for sentence boundaries (English + Chinese punctuation)
                            SENTENCE_SEPS = ['. ', '! ', '? ', '.\n', '!\n', '?\n',
                                             '。', '！', '？', '；', '\n\n']
                            while any(sep in sentence_buffer for sep in SENTENCE_SEPS):
                                earliest_idx = len(sentence_buffer)
                                for sep in SENTENCE_SEPS:
                                    idx = sentence_buffer.find(sep)
                                    if idx != -1 and idx < earliest_idx:
                                        earliest_idx = idx + len(sep)
                                
                                if earliest_idx < len(sentence_buffer):
                                    sentence = sentence_buffer[:earliest_idx].strip()
                                    sentence_buffer = sentence_buffer[earliest_idx:]
                                    
                                    if sentence:
                                        # Clean and synthesize this sentence
                                        speech_text = clean_for_speech(sentence)
                                        if speech_text:
                                            try:
                                                logger.debug(f"Synthesizing: {speech_text[:50]}...")
                                                async for audio_chunk in tts.synthesize_stream(speech_text):
                                                    audio_b64 = base64.b64encode(audio_chunk).decode()
                                                    await websocket.send_json({
                                                        "type": "audio_chunk",
                                                        "data": audio_b64,
                                                        "sample_rate": 24000,
                                                        "format": tts.audio_format,
                                                    })
                                            except Exception as tts_err:
                                                logger.warning(f"TTS stream error: {tts_err}")
                                else:
                                    break
                        
                        # Handle any remaining text
                        if sentence_buffer.strip():
                            speech_text = clean_for_speech(sentence_buffer.strip())
                            if speech_text:
                                try:
                                    async for audio_chunk in tts.synthesize_stream(speech_text):
                                        audio_b64 = base64.b64encode(audio_chunk).decode()
                                        await websocket.send_json({
                                            "type": "audio_chunk",
                                            "data": audio_b64,
                                            "sample_rate": 24000,
                                            "format": tts.audio_format,
                                        })
                                except Exception as tts_err:
                                    logger.warning(f"TTS error on remaining text: {tts_err}")
                        
                        # Signal end of response
                        await websocket.send_json({
                            "type": "response_complete",
                            "text": full_response,
                        })
                        logger.info(f"Response complete: {full_response[:100]}...")

                        # 异步推送到 IM 平台（不阻塞语音回复）
                        if _IM_BRIDGE_AVAILABLE and _bridge_manager and full_response:
                            asyncio.create_task(
                                _bridge_manager.broadcast(
                                    f"用户：{transcript}\n\nAI：{full_response[:200]}",
                                    title="语音对话记录"
                                )
                            )
                
                pending_image = None  # consumed
                audio_buffer = []
                await websocket.send_json({"type": "listening_stopped"})
                logger.debug("Stopped listening")
                
            elif msg["type"] == "audio" and is_listening:
                audio_bytes = base64.b64decode(msg["data"])
                audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
                audio_buffer.append(audio_np)

                if len(audio_buffer) == 1:
                    logger.debug(f"Audio: first chunk {len(audio_np)} samples, "
                                 f"max={np.abs(audio_np).max():.4f}, "
                                 f"rms={np.sqrt(np.mean(audio_np**2)):.4f}")
                
                # VAD check - notify client if speech detected
                if vad and len(audio_np) > 0:
                    has_speech = vad.is_speech(audio_np)
                    await websocket.send_json({
                        "type": "vad_status",
                        "speech_detected": has_speech,
                    })
                
            elif msg["type"] == "monitor_audio":
                # Wake-word monitoring: transcribe a short chunk, check for wake word
                audio_bytes = base64.b64decode(msg["data"])
                audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
                max_amp = float(np.abs(audio_np).max()) if len(audio_np) > 0 else 0.0
                if max_amp > 0.005:  # skip silent chunks
                    try:
                        stt_r = await stt.transcribe(audio_np)
                        transcript = stt_r.text if isinstance(stt_r, STTResult) else str(stt_r)
                        if transcript.strip():
                            lower = transcript.lower()
                            wake_words = [
                                '你好', '小龙', '龙虾', '唤醒', '开始', '在吗',
                                'hey claw', 'hey cloud', 'hello', 'hi claw',
                            ]
                            has_wake = any(w in lower for w in wake_words)
                            await websocket.send_json({
                                "type": "monitor_transcript",
                                "text": transcript,
                                "has_wake_word": has_wake,
                            })
                            logger.debug(f"Monitor: '{transcript}' wake={has_wake}")
                    except Exception as e:
                        logger.warning(f"Monitor STT error: {e}")

            elif msg["type"] == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()
