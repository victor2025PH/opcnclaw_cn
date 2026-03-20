# -*- coding: utf-8 -*-
"""Desktop control, file upload, and remote desktop streaming routes"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
import uuid as _uuid
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


@router.get("/api/desktop/screenshot")
async def desktop_screenshot():
    """Capture a single screenshot and return as JSON {data, w, h}."""
    if not desktop:
        return Response(
            json.dumps({"error": "Desktop streaming unavailable"}),
            status_code=503, media_type="application/json",
        )
    loop = asyncio.get_running_loop()
    data, w, h = await loop.run_in_executor(None, desktop.capture_frame)
    return {
        "data": data, "w": w, "h": h,
        "sw": desktop.screen_size[0], "sh": desktop.screen_size[1],
    }


@router.post("/api/desktop/click")
async def desktop_click(request: Request):
    """Click at normalized (x, y) coordinates. Body: {x, y, button?}."""
    if not desktop:
        return {"ok": False, "error": "Desktop unavailable"}
    body = await request.json()
    x, y = body.get("x", 0.5), body.get("y", 0.5)
    btn = body.get("button", "left")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, desktop.mouse_click, x, y, btn)
    return {"ok": True}


@router.post("/api/desktop/type")
async def desktop_type(request: Request):
    """Type text on the remote desktop. Body: {text}."""
    if not desktop:
        return {"ok": False, "error": "Desktop unavailable"}
    body = await request.json()
    text = body.get("text", "")
    if not text:
        return {"ok": False, "error": "No text"}
    loop = asyncio.get_running_loop()
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in text)
    if has_cjk:
        await loop.run_in_executor(None, desktop.type_chinese, text)
    else:
        await loop.run_in_executor(None, desktop.type_text, text)
    return {"ok": True}


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


DESKTOP_AI_SYSTEM_PROMPT = """你是桌面 AI 助手，可以看到并控制用户的电脑屏幕。

当前屏幕 OCR 识别结果（x,y 是归一化坐标 0~1，左上角 0,0，右下角 1,1）：
{screen_text}

## 可用动作
把动作放在 [ACTIONS] 和 [/ACTIONS] 标记之间，格式为 JSON 数组。

### 推荐动作（OCR 文字定位，不受分辨率影响）
- {{"action":"find_and_click","text":"文字"}} — 找到包含该文字的位置并点击
- {{"action":"find_and_double_click","text":"文字"}} — 找到文字并双击
- {{"action":"find_and_type","target":"搜索框","text":"内容"}} — 找到目标文字点击后输入

### 坐标动作
- {{"action":"click","x":0.5,"y":0.5}} — 点击坐标
- {{"action":"double_click","x":0.5,"y":0.5}} — 双击坐标

### 键盘动作
- {{"action":"type","text":"你好"}} — 输入文字（支持中文）
- {{"action":"key","key":"enter"}} — 按键（enter/tab/esc/backspace/delete/up/down/left/right/space）
- {{"action":"hotkey","keys":["ctrl","a"]}} — 组合键（ctrl+c/v/z/s/a, alt+tab/F4, win+d 等）

### 窗口和屏幕
- {{"action":"focus_window","title":"记事本"}} — 聚焦到包含该标题的窗口
- {{"action":"minimize_all"}} — 最小化所有窗口（显示桌面）
- {{"action":"close_window"}} — 关闭当前窗口
- {{"action":"screenshot"}} — 截图保存到本地
- {{"action":"scroll","dy":3}} — 滚动（正数向上，负数向下）
- {{"action":"wait","ms":1000}} — 等待指定毫秒

## 回复规则
1. 先简要描述屏幕内容和你看到的关键信息
2. 说明你的操作计划
3. 在 [ACTIONS]...[/ACTIONS] 中给出动作序列（优先用 find_and_click 而非坐标）
4. 多步操作时，每次只执行当前步骤，说明后续计划
5. 找不到目标时说明原因和建议
6. 用中文回复

## OCR 解读技巧
- 任务栏在屏幕底部（y > 0.92），系统托盘在右下角（x > 0.8, y > 0.92）
- 窗口标题栏通常在顶部（y < 0.05）
- 中文应用名可能被 OCR 拆分，如"微 信"→"微信"，注意模糊匹配
{skills_section}"""


def _format_ocr_for_ai(items: list[dict], max_items: int = 80) -> str:
    """Format OCR results into a readable screen description for the AI."""
    if not items:
        return "  （屏幕上未识别到文字）"
    sorted_items = sorted(items, key=lambda i: (round(i["y"], 1), i["x"]))
    display = sorted_items[:max_items]
    lines = []
    for it in display:
        lines.append(f"  [{it['text']}] ({it['x']:.2f}, {it['y']:.2f})")
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


# ── Z3: Multi-client session management ──
_desktop_clients: dict = {}
_control_owner: str | None = None


def _build_client_list() -> list:
    return [
        {"id": cid, "name": c["name"], "role": c["role"],
         "since": round(c["connected_at"])}
        for cid, c in _desktop_clients.items()
    ]


async def _broadcast_clients(exclude: str | None = None):
    payload = json.dumps({
        "type": "clients", "list": _build_client_list(),
        "control": _control_owner,
    })
    for cid, c in list(_desktop_clients.items()):
        if cid == exclude:
            continue
        try:
            await c["ws"].send_text(payload)
        except Exception:
            pass


_READ_ONLY_TYPES = frozenset({
    "ping", "set_fps", "set_quality", "set_name", "get_clients",
    "request_control", "release_control",
    "get_sysinfo", "get_windows", "get_clipboard",
    "list_files", "get_processes",
    "ocr_point", "ocr_screen", "get_monitors",
    "collab_annotate", "collab_cursor",
})


@router.websocket("/ws/desktop")
async def desktop_ws(websocket: WebSocket):
    """Stream desktop frames with multi-client support and control ownership."""
    global _control_owner

    if not desktop:
        await websocket.close(code=4010, reason="Desktop streaming unavailable")
        return

    await websocket.accept()

    client_id = _uuid.uuid4().hex[:8]
    client_name = f"User-{client_id[:4]}"
    role = "controller" if _control_owner is None else "viewer"
    if role == "controller":
        _control_owner = client_id

    _desktop_clients[client_id] = {
        "ws": websocket, "name": client_name,
        "role": role, "connected_at": time.time(),
    }
    logger.info(
        f"Desktop client {client_id} ({role}) connected, "
        f"total: {len(_desktop_clients)}"
    )

    await websocket.send_json({
        "type": "session_info",
        "client_id": client_id,
        "role": role,
        "clients": _build_client_list(),
    })
    await _broadcast_clients(exclude=client_id)

    streaming = True
    local_fps = desktop.fps

    use_binary = True

    async def send_frames():
        nonlocal local_fps, use_binary
        loop = asyncio.get_running_loop()
        first = True
        prev_np = None
        kf_counter = 0

        while streaming:
            try:
                force_key = kf_counter >= 50

                if use_binary:
                    jpg, header, prev_np = await loop.run_in_executor(
                        None, desktop.capture_frame_binary, prev_np, force_key,
                    )
                    if header.get("m") == "s":
                        kf_counter += 1
                        await asyncio.sleep(1.0 / local_fps)
                        continue

                    if header.get("m") == "k":
                        kf_counter = 0
                    else:
                        kf_counter += 1

                    header_bytes = json.dumps(header).encode("utf-8")
                    hlen = len(header_bytes)
                    payload = hlen.to_bytes(2, "big") + header_bytes + jpg

                    send_t = time.monotonic()
                    await asyncio.wait_for(
                        websocket.send_bytes(payload),
                        timeout=2.0,
                    )
                    send_ms = (time.monotonic() - send_t) * 1000

                    if first:
                        first = False
                        kb = len(jpg) // 1024
                        logger.info(
                            f"Desktop: first binary frame ({kb}KB)"
                        )
                else:
                    result, prev_np = await loop.run_in_executor(
                        None, desktop.capture_frame_delta, prev_np, force_key,
                    )
                    if result.get("mode") == "skip":
                        kf_counter += 1
                        await asyncio.sleep(1.0 / local_fps)
                        continue
                    if result.get("mode") == "key":
                        kf_counter = 0
                    else:
                        kf_counter += 1

                    send_t = time.monotonic()
                    await asyncio.wait_for(
                        websocket.send_json(result),
                        timeout=2.0,
                    )
                    send_ms = (time.monotonic() - send_t) * 1000

                    if first:
                        first = False
                        kb = len(result.get("data", "")) // 1024
                        logger.info(f"Desktop: first frame ({kb}KB)")

                if send_ms > 300:
                    local_fps = max(2, local_fps - 1)
                elif send_ms < 80 and local_fps < desktop.fps:
                    local_fps = min(desktop.fps, local_fps + 0.5)

                await asyncio.sleep(1.0 / local_fps)
            except asyncio.TimeoutError:
                local_fps = max(1, local_fps - 2)
                prev_np = None
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Desktop frame error: {e}")
                prev_np = None
                await asyncio.sleep(0.5)

    frame_task = asyncio.create_task(send_frames())

    try:
        loop = asyncio.get_running_loop()
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            t = msg.get("type", "")

            if t == "ping":
                await websocket.send_json({"type": "pong", "t": msg.get("t", 0)})
                continue

            if t == "set_fps":
                local_fps = max(1, min(30, int(msg.get("fps", 10))))
                desktop.fps = local_fps
            elif t == "set_quality":
                desktop.quality = max(15, min(95, int(msg.get("quality", 45))))
            elif t == "set_name":
                new_name = str(msg.get("name", ""))[:20]
                if new_name and client_id in _desktop_clients:
                    _desktop_clients[client_id]["name"] = new_name
                    await _broadcast_clients()
            elif t == "get_clients":
                await websocket.send_json({
                    "type": "clients",
                    "list": _build_client_list(),
                    "control": _control_owner,
                })
            elif t == "request_control":
                if _control_owner == client_id:
                    await websocket.send_json({
                        "type": "control_result", "ok": True,
                        "msg": "already_controller",
                    })
                else:
                    old = _control_owner
                    _control_owner = client_id
                    _desktop_clients[client_id]["role"] = "controller"
                    if old and old in _desktop_clients:
                        _desktop_clients[old]["role"] = "viewer"
                        try:
                            await _desktop_clients[old]["ws"].send_json({
                                "type": "control_transferred",
                                "to": client_name,
                            })
                        except Exception:
                            pass
                    await websocket.send_json({
                        "type": "control_result", "ok": True,
                        "msg": "granted",
                    })
                    await _broadcast_clients()
            elif t == "release_control":
                if _control_owner == client_id:
                    _desktop_clients[client_id]["role"] = "viewer"
                    _control_owner = None
                    for cid, c in _desktop_clients.items():
                        if cid != client_id:
                            _control_owner = cid
                            c["role"] = "controller"
                            try:
                                await c["ws"].send_json({
                                    "type": "control_granted",
                                })
                            except Exception:
                                pass
                            break
                    await _broadcast_clients()

            elif t == "get_sysinfo":
                info = await loop.run_in_executor(
                    None, desktop.get_system_info
                )
                await websocket.send_json({"type": "sysinfo", **info})
            elif t == "get_windows":
                wins = await loop.run_in_executor(
                    None, desktop.get_window_list
                )
                await websocket.send_json({"type": "windows", "list": wins})
            elif t == "get_clipboard":
                txt = await loop.run_in_executor(
                    None, desktop.get_clipboard_text
                )
                await websocket.send_json({"type": "clipboard", "text": txt})
            elif t == "list_files":
                real_path, entries = await loop.run_in_executor(
                    None, desktop.list_files, msg.get("path", "~")
                )
                await websocket.send_json({
                    "type": "files", "path": real_path,
                    "entries": entries,
                })
            elif t == "get_processes":
                procs = await loop.run_in_executor(
                    None, desktop.get_processes
                )
                await websocket.send_json({
                    "type": "processes", "list": procs,
                })
            elif t == "ocr_screen":
                items = await loop.run_in_executor(
                    None, desktop.ocr_screen
                )
                full_text = " ".join(
                    it[1] for it in items if len(it) > 1
                ) if items else ""
                await websocket.send_json({
                    "type": "ocr_result", "text": full_text,
                })
            elif t == "ocr_point":
                items = await loop.run_in_executor(
                    None, desktop.ocr_at_point,
                    float(msg.get("x", 0.5)),
                    float(msg.get("y", 0.5)),
                    float(msg.get("r", 0.08)),
                )
                await websocket.send_json({
                    "type": "ocr_result", "items": items,
                    "x": msg.get("x"), "y": msg.get("y"),
                })
            elif t == "get_monitors":
                mons = await loop.run_in_executor(
                    None, desktop.get_monitors
                )
                await websocket.send_json({
                    "type": "monitors", "list": mons,
                })
            elif t == "smart_click":
                target = msg.get("text", "")
                if target:
                    found = await loop.run_in_executor(
                        None, desktop.find_text, target
                    )
                    if found:
                        await loop.run_in_executor(
                            None, desktop.mouse_click,
                            found["x"], found["y"], "left",
                        )
                        await websocket.send_json({
                            "type": "smart_click_result",
                            "ok": True, "text": target,
                            "x": found["x"], "y": found["y"],
                        })
                    else:
                        await websocket.send_json({
                            "type": "smart_click_result",
                            "ok": False, "text": target,
                            "msg": "未找到",
                        })
            elif t == "smart_dblclick":
                target = msg.get("text", "")
                if target:
                    found = await loop.run_in_executor(
                        None, desktop.find_text, target
                    )
                    if found:
                        await loop.run_in_executor(
                            None, desktop.mouse_double_click,
                            found["x"], found["y"],
                        )
                        await websocket.send_json({
                            "type": "smart_click_result",
                            "ok": True, "text": target,
                            "x": found["x"], "y": found["y"],
                        })
                    else:
                        await websocket.send_json({
                            "type": "smart_click_result",
                            "ok": False, "text": target,
                        })
            elif t == "smart_type":
                target = msg.get("target", "")
                text = msg.get("text", "")
                if target and text:
                    found = await loop.run_in_executor(
                        None, desktop.find_text, target
                    )
                    if found:
                        await loop.run_in_executor(
                            None, desktop.mouse_click,
                            found["x"], found["y"], "left",
                        )
                        import time as _time
                        _time.sleep(0.3)
                        await loop.run_in_executor(
                            None, desktop.type_text, text
                        )
                        await websocket.send_json({
                            "type": "smart_click_result",
                            "ok": True, "text": target,
                        })
                    else:
                        await websocket.send_json({
                            "type": "smart_click_result",
                            "ok": False, "text": target,
                        })
            elif t == "collab_annotate" or t == "collab_cursor":
                relay = json.dumps(msg)
                for cid, c in list(_desktop_clients.items()):
                    if cid != client_id:
                        try:
                            await c["ws"].send_text(relay)
                        except Exception:
                            pass

            elif t not in _READ_ONLY_TYPES:
                if client_id != _control_owner:
                    await websocket.send_json({
                        "type": "error",
                        "msg": "no_control",
                    })
                    continue

                if t == "set_clipboard":
                    await loop.run_in_executor(
                        None, desktop.set_clipboard_text,
                        msg.get("text", ""),
                    )
                    await websocket.send_json({"type": "clipboard_ok"})
                elif t == "focus_window":
                    await loop.run_in_executor(
                        None, desktop.focus_window,
                        msg.get("title", ""),
                    )
                elif t == "open_file":
                    await loop.run_in_executor(
                        None, desktop.open_file,
                        msg.get("path", ""),
                    )
                elif t == "kill_process":
                    ok = await loop.run_in_executor(
                        None, desktop.kill_process,
                        int(msg.get("pid", 0)),
                    )
                    await websocket.send_json({
                        "type": "kill_result", "ok": ok,
                        "pid": msg.get("pid", 0),
                    })
                elif t == "set_monitor":
                    ok = await loop.run_in_executor(
                        None, desktop.set_monitor,
                        int(msg.get("index", 1)),
                    )
                    await websocket.send_json({
                        "type": "monitor_set", "ok": ok,
                        "index": msg.get("index"),
                    })
                else:
                    if t == "mouse_move" or (msg.get("x") is not None and msg.get("y") is not None):
                        desktop._cursor_nx = float(msg.get("x", 0.5))
                        desktop._cursor_ny = float(msg.get("y", 0.5))
                    await loop.run_in_executor(
                        None, desktop.handle_command, msg
                    )

    except WebSocketDisconnect:
        logger.info(f"Desktop client {client_id} disconnected")
    except Exception as e:
        logger.error(f"Desktop WS error ({client_id}): {e}")
    finally:
        streaming = False
        frame_task.cancel()
        _desktop_clients.pop(client_id, None)
        if _control_owner == client_id:
            _control_owner = None
            for cid, c in _desktop_clients.items():
                _control_owner = cid
                c["role"] = "controller"
                try:
                    await c["ws"].send_json({"type": "control_granted"})
                except Exception:
                    pass
                break
        try:
            await _broadcast_clients()
        except Exception:
            pass
        logger.info(
            f"Desktop client {client_id} cleaned up, "
            f"remaining: {len(_desktop_clients)}"
        )


# ── Vision Control (structured UI element access) ──

_vision_ctrl = None
_vision_init = False


def _get_vision():
    global _vision_ctrl, _vision_init
    if _vision_init:
        return _vision_ctrl
    _vision_init = True
    try:
        from ..vision_control import VisionController
        _vision_ctrl = VisionController()
        _vision_ctrl.enable()
        logger.info("VisionController initialized")
    except Exception as e:
        logger.info(f"VisionController not available: {e}")
    return _vision_ctrl


@router.get("/api/vision-control/screen")
async def get_screen_state():
    """Structured screen state: UI elements with pixel bboxes."""
    vc = _get_vision()
    if not vc:
        return Response(
            content=json.dumps({"error": "VisionController not available"}),
            status_code=503,
        )
    loop = asyncio.get_running_loop()
    state = await loop.run_in_executor(None, vc.get_screen_state)
    if not state:
        return {"elements": [], "app": "", "error": "capture failed"}
    return {
        "app": state.foreground_app,
        "element_count": len(state.elements),
        "elements": [
            {
                "id": el.id,
                "label": el.label,
                "bbox": list(el.bbox),
                "type": el.element_type,
            }
            for el in state.elements[:100]
        ],
    }


@router.get("/api/vision-control/describe")
async def describe_screen():
    """Human-readable screen description."""
    vc = _get_vision()
    if not vc:
        return {"text": "VisionController not available"}
    loop = asyncio.get_running_loop()
    desc = await loop.run_in_executor(None, vc.describe_screen)
    return {"text": desc}


@router.post("/api/vision-control/execute")
async def execute_vision_action(request: Request):
    """Execute a UI action by type + target/coordinates.

    Body: { "type": "click"|"type"|"hotkey"|"scroll",
            "x": int, "y": int, "text": str, "key": str,
            "element_id": int }
    """
    vc = _get_vision()
    if not vc:
        return Response(
            content=json.dumps({"error": "VisionController not available"}),
            status_code=503,
        )
    body = await request.json()
    from ..vision_control import Action, UIElement

    action = Action(
        type=body.get("type", "click"),
        text=body.get("text", ""),
        key=body.get("key", ""),
        x=int(body.get("x", 0)),
        y=int(body.get("y", 0)),
    )

    elem_id = body.get("element_id")
    if elem_id is not None:
        state = vc.get_screen_state()
        if state:
            target = next((e for e in state.elements if e.id == elem_id), None)
            if target:
                action.target = target

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, vc.execute_action, action)
    return {"ok": ok, "action": body.get("type", "click")}
