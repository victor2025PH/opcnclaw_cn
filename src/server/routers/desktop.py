# -*- coding: utf-8 -*-
"""Desktop control, file upload, and remote desktop streaming routes"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form
from fastapi.responses import Response
from loguru import logger
from starlette.responses import StreamingResponse

from ..desktop import DesktopStreamer
from ..desktop_skills import list_skills, get_skill, get_skills_prompt_section

router = APIRouter()

# ── Remote Desktop ──
desktop: Optional[DesktopStreamer] = None

try:
    desktop = DesktopStreamer()
except Exception as e:
    logger.warning(f"Desktop streamer unavailable: {e}")


# ── 文件上传到本地电脑 ──────────────────────────────────────
UPLOAD_DIR = Path(os.getenv("OPENCLAW_UPLOAD_DIR", str(Path.home() / "Downloads" / "OpenClawUploads")))


@router.get("/api/upload/dir")
async def get_upload_dir():
    """返回当前上传目录路径。"""
    return {"dir": str(UPLOAD_DIR)}


@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...), subdir: str = Form("")):
    """将文件保存到电脑本地目录（默认 ~/Downloads/OpenClawUploads）。"""
    try:
        save_dir = UPLOAD_DIR / subdir if subdir else UPLOAD_DIR
        save_dir.mkdir(parents=True, exist_ok=True)

        # 防止路径穿越攻击
        safe_name = Path(file.filename).name
        if not safe_name:
            safe_name = f"upload_{int(os.times().elapsed * 1000)}"

        # 如果同名文件已存在，自动加序号
        dest = save_dir / safe_name
        if dest.exists():
            stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
            counter = 1
            while dest.exists():
                dest = save_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        content = await file.read()
        dest.write_bytes(content)

        size_kb = len(content) / 1024
        logger.info(f"📁 文件已保存: {dest} ({size_kb:.1f} KB)")

        return {
            "ok": True,
            "filename": dest.name,
            "path": str(dest),
            "size": len(content),
            "dir": str(save_dir),
        }
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return {"ok": False, "error": str(e)}


DESKTOP_AI_SYSTEM_PROMPT = """你是桌面 AI 助手，可以看到并控制用户的 Windows 电脑屏幕。

当前屏幕上识别到的文字和位置（x,y 是归一化坐标 0~1，左上角为 0,0，右下角为 1,1）：
{screen_text}

你可以使用以下动作来控制电脑。把动作放在 [ACTIONS] 和 [/ACTIONS] 标记之间，格式为 JSON 数组：

可用动作：
- {{"action":"find_and_click","text":"微信"}} — 在屏幕上找到包含该文字的位置并点击（最推荐，不受窗口位置影响）
- {{"action":"find_and_double_click","text":"微信"}} — 找到文字并双击
- {{"action":"click","x":0.5,"y":0.5}} — 点击指定坐标
- {{"action":"double_click","x":0.5,"y":0.5}} — 双击指定坐标
- {{"action":"type","text":"你好"}} — 输入文字（支持中文）
- {{"action":"key","key":"enter"}} — 按键（enter/tab/esc/backspace/delete/up/down/left/right 等）
- {{"action":"hotkey","keys":["ctrl","a"]}} — 组合键
- {{"action":"scroll","dy":3}} — 滚动（正数向上，负数向下）
- {{"action":"wait","ms":1000}} — 等待指定毫秒

回复规则：
1. 先简要描述你在屏幕上看到了什么
2. 说明你打算执行什么操作
3. 在 [ACTIONS]...[/ACTIONS] 中给出动作序列
4. 如果需要多步操作（如先打开应用再操作），每次只执行当前步骤的动作，说明接下来还需要什么
5. 如果找不到目标，说明原因并建议用户怎么做
6. 用中文回复
{skills_section}"""


def _format_ocr_for_ai(items: list[dict], max_items: int = 80) -> str:
    """Format OCR results into a readable screen description for the AI."""
    if not items:
        return "  （屏幕上未识别到文字）"
    display = items[:max_items]
    lines = []
    for it in display:
        lines.append(f"  [{it['text']}] at ({it['x']:.2f}, {it['y']:.2f})")
    if len(items) > max_items:
        lines.append(f"  ...还有 {len(items) - max_items} 项未显示")
    return "\n".join(lines)


def _parse_actions(text: str) -> list[dict]:
    """Extract actions JSON from AI response text between [ACTIONS]...[/ACTIONS]."""
    pattern = r'\[ACTIONS\]\s*(.*?)\s*\[/ACTIONS\]'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        try:
            cleaned = match.group(1).strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```\w*\n?', '', cleaned)
                cleaned = re.sub(r'```$', '', cleaned).strip()
            return json.loads(cleaned)
        except Exception:
            return []


@router.post("/api/desktop-cmd")
async def desktop_ai_command(request: Request):
    """AI-driven desktop control: screenshot → OCR → AI plan → execute → respond."""
    if not desktop:
        return Response(content=json.dumps({"error": "Desktop not available"}), status_code=503)

    body = await request.json()
    command = body.get("command", "").strip()
    history = body.get("history", [])
    max_rounds = min(int(body.get("max_rounds", 3)), 5)

    if not command:
        return Response(content=json.dumps({"error": "No command"}), status_code=400)

    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    gateway_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
    loop = asyncio.get_running_loop()

    async def run_rounds():
        round_history = list(history[-6:])

        for round_num in range(1, max_rounds + 1):
            # 1. Screenshot + OCR
            yield f"data: {json.dumps({'type': 'status', 'text': f'正在分析屏幕... (第{round_num}轮)'})}\n\n"

            ocr_items = await loop.run_in_executor(None, desktop.ocr_screen)
            screen_desc = _format_ocr_for_ai(ocr_items)

            # 2. Build messages
            skills_section = get_skills_prompt_section()
            system_msg = DESKTOP_AI_SYSTEM_PROMPT.format(
                screen_text=screen_desc,
                skills_section=skills_section
            )
            messages = [{"role": "system", "content": system_msg}]
            messages.extend(round_history)

            if round_num == 1:
                messages.append({"role": "user", "content": command})
            else:
                messages.append({"role": "user", "content":
                    f"动作已执行完成。执行日志：\n{exec_log_text}\n\n"
                    f"屏幕已更新。请查看新的屏幕内容，判断操作是否成功，是否需要继续。"
                    f"如果任务已完成，不需要输出 [ACTIONS] 块。"
                })

            # 3. Call AI (collect full response)
            full_response = ""
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                    async with client.stream(
                        "POST",
                        f"{gateway_url}/v1/chat/completions",
                        json={"messages": messages, "model": "deepseek-chat", "stream": True},
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
                                    yield f"data: {json.dumps({'type': 'text', 'text': delta})}\n\n"
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                logger.error(f"Desktop AI error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
                break

            # 4. Parse actions
            actions = _parse_actions(full_response)
            if not actions:
                yield f"data: {json.dumps({'type': 'done', 'round': round_num})}\n\n"
                break

            # 5. Execute actions
            yield f"data: {json.dumps({'type': 'executing', 'actions': actions})}\n\n"
            exec_log = await loop.run_in_executor(None, desktop.execute_actions, actions)
            exec_log_text = "\n".join(exec_log)
            yield f"data: {json.dumps({'type': 'exec_result', 'log': exec_log})}\n\n"

            # Save to round history for multi-round
            round_history.append({"role": "assistant", "content": full_response})

            # Wait for screen to update after actions
            await asyncio.sleep(0.8)

            # Take a post-action screenshot
            screenshot_b64 = await loop.run_in_executor(None, desktop.capture_screenshot_b64)
            yield f"data: {json.dumps({'type': 'screenshot', 'data': screenshot_b64})}\n\n"

            if round_num >= max_rounds:
                yield f"data: {json.dumps({'type': 'done', 'round': round_num, 'reason': 'max_rounds'})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        run_rounds(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/desktop-skills")
async def desktop_skills_list():
    """Return available desktop skill packs."""
    return {"skills": list_skills()}


@router.post("/api/desktop-skill/{skill_id}")
async def execute_desktop_skill(skill_id: str):
    """Execute a desktop skill pack by ID."""
    if not desktop:
        return Response(content=json.dumps({"error": "Desktop not available"}), status_code=503)

    skill = get_skill(skill_id)
    if not skill:
        return Response(content=json.dumps({"error": f"Skill '{skill_id}' not found"}), status_code=404)

    loop = asyncio.get_running_loop()

    async def run_skill():
        yield f"data: {json.dumps({'type': 'skill_start', 'id': skill_id, 'name': skill.name_zh})}\n\n"

        try:
            result = await loop.run_in_executor(None, skill.execute, desktop)

            for step in result.steps:
                yield f"data: {json.dumps({'type': 'skill_step', 'desc': step.description, 'status': step.status, 'detail': step.detail})}\n\n"

            payload = {
                'type': 'skill_done',
                'success': result.success,
                'message': result.message,
            }
            if result.screenshot_b64:
                payload['screenshot'] = result.screenshot_b64
            yield f"data: {json.dumps(payload)}\n\n"

        except Exception as e:
            logger.error(f"Skill {skill_id} error: {e}")
            yield f"data: {json.dumps({'type': 'skill_error', 'message': str(e)})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        run_skill(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/desktop-skill/send_wechat_message")
async def send_wechat_message_api(request: Request):
    """
    向微信联系人发送消息（双重 OCR 验证，绝不依赖坐标）。
    Body: { "contact": "张三", "message": "你好" }
    """
    if not desktop:
        return Response(content=json.dumps({"error": "Desktop not available"}), status_code=503)

    body = await request.json()
    contact = (body.get("contact") or "").strip()
    message = (body.get("message") or "").strip()

    if not contact:
        return Response(content=json.dumps({"error": "缺少 contact 参数（联系人名字）"}), status_code=400)
    if not message:
        return Response(content=json.dumps({"error": "缺少 message 参数（消息内容）"}), status_code=400)

    from ..desktop_skills import execute_send_wechat_message

    loop = asyncio.get_running_loop()

    async def run_send():
        yield f"data: {json.dumps({'type': 'skill_start', 'id': 'send_wechat_message', 'contact': contact})}\n\n"
        try:
            result = await loop.run_in_executor(
                None, execute_send_wechat_message, desktop, contact, message
            )
            for step in result.steps:
                yield f"data: {json.dumps({'type': 'skill_step', 'desc': step.description, 'status': step.status, 'detail': step.detail})}\n\n"

            payload = {
                "type": "skill_done",
                "success": result.success,
                "message": result.message,
            }
            if result.screenshot_b64:
                payload["screenshot"] = result.screenshot_b64
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            logger.error(f"send_wechat_message error: {e}")
            yield f"data: {json.dumps({'type': 'skill_error', 'message': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        run_send(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/ws/desktop")
async def desktop_ws(websocket: WebSocket):
    """Stream desktop frames and receive mouse/keyboard commands."""
    if not desktop:
        await websocket.close(code=4010, reason="Desktop streaming unavailable")
        return

    await websocket.accept()
    logger.info("Desktop client connected")

    streaming = True
    fps = desktop.fps

    async def send_frames():
        loop = asyncio.get_running_loop()
        frame_count = 0
        while streaming:
            try:
                data, w, h = await loop.run_in_executor(
                    None, desktop.capture_frame
                )
                await websocket.send_json({
                    "type": "frame",
                    "data": data,
                    "w": w,
                    "h": h,
                    "sw": desktop.screen_size[0],
                    "sh": desktop.screen_size[1],
                })
                frame_count += 1
                if frame_count == 1:
                    logger.info(f"Desktop: first frame sent ({len(data)//1024}KB {w}x{h})")
                await asyncio.sleep(1.0 / fps)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Desktop frame error: {e}")
                await asyncio.sleep(0.5)

    frame_task = asyncio.create_task(send_frames())

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "set_fps":
                fps = max(1, min(30, int(msg.get("fps", 10))))
                desktop.fps = fps
            else:
                await asyncio.get_event_loop().run_in_executor(
                    None, desktop.handle_command, msg
                )
    except WebSocketDisconnect:
        logger.info("Desktop client disconnected")
    except Exception as e:
        logger.error(f"Desktop WS error: {e}")
    finally:
        streaming = False
        frame_task.cancel()
