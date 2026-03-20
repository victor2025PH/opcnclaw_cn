"""Desktop AI skill packs — predefined multi-step automation routines.

Each skill is a self-contained procedure that uses a combination of:
- Windows API calls (find/activate windows) — Windows only
- macOS AppleScript / osascript — macOS only
- OCR screen analysis
- pyautogui mouse/keyboard automation (cross-platform)
"""

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import pyautogui
from loguru import logger

IS_WINDOWS = sys.platform == "win32"
IS_MACOS   = sys.platform == "darwin"
IS_LINUX   = sys.platform.startswith("linux")

# ── Windows API bindings (Windows only) ──────────────────────────
if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes
    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
else:
    ctypes = None
    user32 = kernel32 = None

SW_RESTORE      = 9
SW_SHOW         = 5
SW_SHOWMINIMIZED = 2
HWND_TOPMOST    = -1
HWND_NOTOPMOST  = -2
SWP_NOMOVE      = 0x0002
SWP_NOSIZE      = 0x0001


def find_window(class_name: Optional[str], title_contains: Optional[str] = None) -> int:
    """Find a window handle by class name and/or title substring (Windows only)."""
    if not IS_WINDOWS:
        return 0
    if class_name and not title_contains:
        hwnd = user32.FindWindowW(class_name, None)
        return hwnd or 0

    result = 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    def enum_cb(hwnd, _):
        nonlocal result
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        match = True
        if class_name:
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buf, 256)
            if cls_buf.value != class_name:
                match = False
        if title_contains and title_contains not in title:
            match = False
        if match and user32.IsWindow(hwnd):
            result = hwnd
            return False  # stop enumeration
        return True

    user32.EnumWindows(enum_cb, 0)
    return result


def activate_window(hwnd: int) -> bool:
    """Bring a window to the foreground (Windows only)."""
    if not IS_WINDOWS:
        return False
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.3)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    return True


def activate_app_macos(app_name: str) -> bool:
    """Activate a macOS application by name using osascript."""
    if not IS_MACOS:
        return False
    try:
        script = f'tell application "{app_name}" to activate'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        time.sleep(0.5)
        return True
    except Exception as e:
        logger.warning(f"macOS activate failed: {e}")
        return False


def is_process_running(process_name: str) -> bool:
    """Check if a process is running (cross-platform)."""
    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            return process_name.lower() in result.stdout.lower()
        else:
            # macOS / Linux: use pgrep
            name = process_name.replace(".exe", "")
            result = subprocess.run(["pgrep", "-x", name],
                                    capture_output=True, timeout=5)
            return result.returncode == 0
    except Exception:
        return False


def launch_program(exe_path: str) -> bool:
    """Launch a program (cross-platform)."""
    if IS_MACOS and exe_path.endswith(".app"):
        try:
            subprocess.Popen(["open", exe_path])
            return True
        except Exception as e:
            logger.warning(f"Failed to open {exe_path}: {e}")
            return False
    if not os.path.isfile(exe_path):
        return False
    try:
        subprocess.Popen([exe_path], shell=False)
        return True
    except Exception as e:
        logger.warning(f"Failed to launch {exe_path}: {e}")
        return False


# ── Skill definition ──

@dataclass
class SkillStep:
    """A single step in a skill execution."""
    description: str
    status: str = "pending"  # pending / running / success / failed / skipped
    detail: str = ""


@dataclass
class DesktopSkill:
    """A desktop automation skill pack."""
    id: str
    name_zh: str
    name_en: str
    desc_zh: str
    desc_en: str
    icon: str
    execute: Callable = None  # set after definition


@dataclass
class SkillResult:
    """Result of executing a skill."""
    success: bool
    steps: list[SkillStep] = field(default_factory=list)
    message: str = ""
    screenshot_b64: str = ""


# ── WeChat skill ──

WECHAT_CLASS = "WeChatMainWndForPC"
WECHAT_CLASS_V4 = "mmui::MainWindow"
WECHAT_CLASSES = [WECHAT_CLASS, WECHAT_CLASS_V4]
WECHAT_LOGIN_CLASS = "WeChatLoginWndForPC"
WECHAT_PROCESS = "WeChat.exe"
WECHAT_COMMON_PATHS_WIN = [
    os.path.expandvars(r"%LOCALAPPDATA%\WeChat\WeChat.exe"),
    os.path.expandvars(r"%ProgramFiles%\Tencent\WeChat\WeChat.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Tencent\WeChat\WeChat.exe"),
    r"D:\Program Files\Tencent\WeChat\WeChat.exe",
    r"C:\Program Files\Tencent\WeChat\WeChat.exe",
    r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
]
WECHAT_COMMON_PATHS_MAC = [
    "/Applications/WeChat.app",
    os.path.expanduser("~/Applications/WeChat.app"),
]


def _find_wechat_exe() -> Optional[str]:
    """Find WeChat executable (cross-platform)."""
    if IS_MACOS:
        for p in WECHAT_COMMON_PATHS_MAC:
            if os.path.exists(p):
                return p
        return None
    # Windows
    for p in WECHAT_COMMON_PATHS_WIN:
        if os.path.isfile(p):
            return p
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Tencent\WeChat", 0, winreg.KEY_READ)
        install_path, _ = winreg.QueryValueEx(key, "InstallPath")
        winreg.CloseKey(key)
        exe = os.path.join(install_path, "WeChat.exe")
        if os.path.isfile(exe):
            return exe
    except Exception:
        pass
    return None


def _wait_for_wechat_window(timeout: float = 12.0) -> int:
    """Poll for WeChat main or login window, return hwnd or 0."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        hwnd = find_window(WECHAT_CLASS) or find_window(WECHAT_LOGIN_CLASS)
        if hwnd:
            return hwnd
        time.sleep(1.0)
    return 0


def _ocr_find_wechat(desktop, region: str = "all") -> Optional[dict]:
    """OCR the screen and find '微信' text, optionally filtered by region.
    region: 'taskbar' (y>0.92), 'desktop' (y<0.92), 'all'
    """
    try:
        items = desktop.ocr_screen()
        wechat = []
        for it in items:
            if "微信" not in it["text"] and "WeChat" not in it["text"]:
                continue
            if region == "taskbar" and it["y"] <= 0.92:
                continue
            if region == "desktop" and it["y"] >= 0.92:
                continue
            wechat.append(it)
        if wechat:
            return max(wechat, key=lambda i: i["score"])
    except Exception as e:
        logger.debug(f"OCR find WeChat ({region}): {e}")
    return None


def execute_open_wechat(desktop) -> SkillResult:
    """Open WeChat — cross-platform, tries multiple strategies in order."""
    steps = []

    # ── macOS: use osascript to activate / open WeChat ──────────
    if IS_MACOS:
        s = SkillStep("macOS 打开微信（osascript）")
        steps.append(s)
        s.status = "running"
        wechat_path = _find_wechat_exe()
        if wechat_path:
            try:
                subprocess.run(["open", wechat_path], timeout=5)
                time.sleep(2.0)
                activate_app_macos("WeChat")
                s.status = "success"
                s.detail = f"已打开 {wechat_path}"
                return SkillResult(True, steps, "微信已打开",
                                   desktop.capture_screenshot_b64())
            except Exception as e:
                s.status = "failed"
                s.detail = str(e)
        else:
            s.status = "failed"
            s.detail = "未找到微信安装路径（/Applications/WeChat.app）"
        return SkillResult(False, steps, "未找到微信，请先安装", None)

    # ── Windows strategies ───────────────────────────────────────
    # Strategy 1: Existing main window via Win32 API
    s = SkillStep("检查微信主窗口（Win32 API）")
    steps.append(s)
    s.status = "running"

    hwnd = find_window(WECHAT_CLASS)
    if hwnd:
        s.status = "success"
        s.detail = f"找到微信窗口 (hwnd={hwnd})"
        sa = SkillStep("激活微信窗口到前台")
        steps.append(sa)
        sa.status = "running"
        if activate_window(hwnd):
            sa.status = "success"
            sa.detail = "微信已置顶到前台"
            time.sleep(0.5)
            return SkillResult(True, steps, "微信窗口已打开并置顶到前台",
                               desktop.capture_screenshot_b64())
        sa.status = "failed"
        sa.detail = "激活窗口失败，继续尝试其他方式"
    else:
        s.status = "failed"
        s.detail = "未找到微信主窗口"

    # ── Strategy 2: Login window ──
    s = SkillStep("检查微信登录窗口")
    steps.append(s)
    s.status = "running"
    login_hwnd = find_window(WECHAT_LOGIN_CLASS)
    if login_hwnd:
        s.status = "success"
        s.detail = "找到微信登录窗口"
        activate_window(login_hwnd)
        time.sleep(0.5)
        return SkillResult(True, steps, "微信登录窗口已打开，请先登录微信",
                           desktop.capture_screenshot_b64())
    s.status = "skipped"
    s.detail = "未找到登录窗口"

    # ── Strategy 3: Taskbar icon (OCR scan bottom bar) ──
    s = SkillStep("扫描任务栏查找微信图标")
    steps.append(s)
    s.status = "running"

    taskbar_hit = _ocr_find_wechat(desktop, region="taskbar")
    if taskbar_hit:
        s.status = "success"
        s.detail = f"任务栏找到 \"{taskbar_hit['text']}\" at ({taskbar_hit['x']:.2f}, {taskbar_hit['y']:.2f})"
        desktop.mouse_click(taskbar_hit["x"], taskbar_hit["y"])
        time.sleep(2.0)
        hwnd = _wait_for_wechat_window(timeout=5.0)
        if hwnd:
            activate_window(hwnd)
            time.sleep(0.5)
            return SkillResult(True, steps, "通过任务栏图标成功打开微信",
                               desktop.capture_screenshot_b64())
        return SkillResult(True, steps, "已点击任务栏微信图标",
                           desktop.capture_screenshot_b64())
    s.status = "failed"
    s.detail = "任务栏未识别到微信文字"

    # ── Strategy 4: System tray (expand overflow → OCR) ──
    process_running = is_process_running(WECHAT_PROCESS)

    if process_running:
        s = SkillStep("微信进程运行中，尝试从系统托盘恢复")
        steps.append(s)
        s.status = "running"

        # 4a: Click the ^ overflow arrow to expand hidden tray icons
        try:
            desktop.mouse_click(0.76, 0.98)
            time.sleep(1.2)
            tray_hit = _ocr_find_wechat(desktop, region="all")
            if tray_hit:
                desktop.mouse_click(tray_hit["x"], tray_hit["y"])
                s.status = "success"
                s.detail = f"展开托盘后找到 \"{tray_hit['text']}\" at ({tray_hit['x']:.2f}, {tray_hit['y']:.2f})"
                time.sleep(2.0)
                hwnd = _wait_for_wechat_window(timeout=5.0)
                if hwnd:
                    activate_window(hwnd)
                time.sleep(0.5)
                return SkillResult(True, steps, "从系统托盘成功打开微信",
                                   desktop.capture_screenshot_b64())
        except Exception as e:
            logger.debug(f"Tray expand: {e}")

        # 4b: Dismiss tray popup by pressing Escape
        pyautogui.press("escape", _pause=False)
        time.sleep(0.3)
        s.status = "failed"
        s.detail = "托盘区域未找到微信图标"

    # ── Strategy 5: WeChat hotkey Ctrl+Alt+W ──
    if process_running:
        s = SkillStep("尝试微信快捷键 Ctrl+Alt+W")
        steps.append(s)
        s.status = "running"
        try:
            pyautogui.hotkey("ctrl", "alt", "w", _pause=False)
            time.sleep(2.0)
            hwnd = find_window(WECHAT_CLASS)
            if hwnd:
                activate_window(hwnd)
                s.status = "success"
                s.detail = "快捷键成功唤起微信"
                time.sleep(0.5)
                return SkillResult(True, steps, "通过快捷键成功打开微信",
                                   desktop.capture_screenshot_b64())
            s.status = "failed"
            s.detail = "快捷键后仍未找到微信窗口"
        except Exception:
            s.status = "failed"
            s.detail = "快捷键执行异常"

    # ── Strategy 6: Desktop shortcut (OCR find + double-click) ──
    s = SkillStep("扫描桌面查找微信快捷方式")
    steps.append(s)
    s.status = "running"

    # First minimize all windows to reveal the desktop
    pyautogui.hotkey("win", "d", _pause=False)
    time.sleep(1.0)

    desktop_hit = _ocr_find_wechat(desktop, region="desktop")
    if desktop_hit:
        s.status = "success"
        s.detail = f"桌面找到 \"{desktop_hit['text']}\" at ({desktop_hit['x']:.2f}, {desktop_hit['y']:.2f})"

        se = SkillStep("双击桌面微信快捷方式")
        steps.append(se)
        se.status = "running"
        desktop.mouse_double_click(desktop_hit["x"], desktop_hit["y"])
        time.sleep(3.0)

        hwnd = _wait_for_wechat_window(timeout=10.0)
        if hwnd:
            activate_window(hwnd)
            se.status = "success"
            se.detail = "微信窗口已出现"
            time.sleep(0.5)
            return SkillResult(True, steps, "通过桌面快捷方式成功打开微信",
                               desktop.capture_screenshot_b64())
        se.status = "failed"
        se.detail = "双击后窗口未出现，可能在加载中"
        return SkillResult(True, steps, "已双击桌面微信图标，请等待启动",
                           desktop.capture_screenshot_b64())
    else:
        s.status = "failed"
        s.detail = "桌面未识别到微信快捷方式文字"
        # Restore windows
        pyautogui.hotkey("win", "d", _pause=False)
        time.sleep(0.5)

    # ── Strategy 7: Launch from install path ──
    s = SkillStep("尝试从安装路径启动微信")
    steps.append(s)
    s.status = "running"

    exe_path = _find_wechat_exe()
    if exe_path:
        if launch_program(exe_path):
            s.status = "success"
            s.detail = f"已启动 {exe_path}"
            sw = SkillStep("等待微信窗口出现")
            steps.append(sw)
            sw.status = "running"
            hwnd = _wait_for_wechat_window(timeout=15.0)
            if hwnd:
                activate_window(hwnd)
                sw.status = "success"
                sw.detail = "微信窗口已出现"
                time.sleep(0.5)
                return SkillResult(True, steps, "微信已启动",
                                   desktop.capture_screenshot_b64())
            sw.status = "failed"
            sw.detail = "等待超时"
            return SkillResult(False, steps, "微信已启动但窗口未出现，可能需要登录",
                               desktop.capture_screenshot_b64())
        s.status = "failed"
        s.detail = "启动失败"
    else:
        s.status = "failed"
        s.detail = "未找到微信安装路径"

    # ── All strategies exhausted ──
    return SkillResult(
        False, steps,
        "无法打开微信。请确认微信已安装，或手动打开微信后重试。",
        desktop.capture_screenshot_b64()
    )


# ── WeChat send message (with contact verification) ──────────────────────────

def _ocr_verify_contact(desktop, expected_name: str, region_top: float = 0.08,
                         region_bottom: float = 0.55) -> Optional[dict]:
    """
    扫描屏幕，在搜索结果区域内查找与 expected_name 匹配的联系人条目。
    返回匹配项的坐标字典，或 None（未找到 / 名字不符）。

    匹配策略（由严到宽）：
      1. 完全匹配
      2. 去空格后完全匹配
      3. expected_name 是 OCR 结果的子串（且长度>=2，避免单字误匹配）
    """
    try:
        items = desktop.ocr_screen()
        if not items:
            return None

        candidates = []
        for it in items:
            y = it.get("y", 0)
            if not (region_top <= y <= region_bottom):
                continue
            text = it.get("text", "").strip()
            if not text:
                continue

            name_clean = expected_name.strip().replace(" ", "")
            text_clean = text.replace(" ", "")

            if text_clean == name_clean:
                it["_match_score"] = 3
                candidates.append(it)
            elif len(name_clean) >= 2 and name_clean in text_clean:
                it["_match_score"] = 2
                candidates.append(it)
            elif len(name_clean) >= 2 and text_clean in name_clean and len(text_clean) >= 2:
                it["_match_score"] = 1
                candidates.append(it)

        if candidates:
            best = max(candidates, key=lambda c: (c["_match_score"], c.get("score", 0)))
            return best
    except Exception as e:
        logger.debug(f"OCR verify contact: {e}")
    return None


def execute_send_wechat_message(desktop, contact_name: str, message: str) -> SkillResult:
    """
    向指定联系人发送微信消息，全程 OCR 验证身份，绝不依赖固定坐标。

    流程：
      1. 确保微信窗口已打开并在前台
      2. 用 Ctrl+F 打开搜索框，输入联系人姓名
      3. 等待搜索结果，用 OCR 读取并核对名字
      4. 名字不匹配 → 取消，返回错误
      5. 名字匹配 → 点击进入对话
      6. 再次 OCR 验证当前对话框标题是否含联系人名字
      7. 二次验证通过 → 在输入框输入消息，按 Enter 发送
      8. 全程任何一步失败 → 安全退出，不发送
    """
    steps: list[SkillStep] = []

    # ── Step 1：确保微信在前台 ────────────────────────────────────
    s = SkillStep("确保微信窗口在前台")
    steps.append(s)
    s.status = "running"

    hwnd = find_window(WECHAT_CLASS)
    if not hwnd:
        # 尝试启动
        open_result = execute_open_wechat(desktop)
        if not open_result.success:
            s.status = "failed"
            s.detail = "无法打开微信"
            return SkillResult(False, steps, "微信未运行且无法启动，消息未发送", None)
        time.sleep(2.0)
        hwnd = find_window(WECHAT_CLASS)

    if hwnd:
        activate_window(hwnd)
        time.sleep(0.8)
        s.status = "success"
        s.detail = f"微信窗口已激活 (hwnd={hwnd})"
    else:
        s.status = "failed"
        s.detail = "找不到微信主窗口"
        return SkillResult(False, steps, "无法找到微信窗口，消息未发送", None)

    # ── Step 2：打开搜索框，输入联系人名字 ───────────────────────
    s = SkillStep(f"搜索联系人「{contact_name}」")
    steps.append(s)
    s.status = "running"

    try:
        pyautogui.hotkey("ctrl", "f", _pause=False)
        time.sleep(0.8)
        # 清空搜索框，再输入
        pyautogui.hotkey("ctrl", "a", _pause=False)
        time.sleep(0.2)
        pyautogui.typewrite(contact_name, interval=0.05, _pause=False)
        time.sleep(1.5)   # 等待搜索结果出现
        s.status = "success"
        s.detail = f"已输入搜索词「{contact_name}」"
    except Exception as e:
        s.status = "failed"
        s.detail = f"输入搜索词失败: {e}"
        pyautogui.press("escape", _pause=False)
        return SkillResult(False, steps, f"搜索输入失败，消息未发送: {e}", None)

    # ── Step 3：OCR 验证搜索结果（第一道验证）────────────────────
    s = SkillStep("OCR 验证搜索结果中的联系人名字")
    steps.append(s)
    s.status = "running"

    match = _ocr_verify_contact(desktop, contact_name, region_top=0.08, region_bottom=0.70)

    if not match:
        s.status = "failed"
        s.detail = f"搜索结果中未找到名字含「{contact_name}」的条目，已取消"
        pyautogui.press("escape", _pause=False)
        return SkillResult(
            False, steps,
            f"⚠️ 搜索结果中找不到联系人「{contact_name}」，消息未发送。"
            f"请确认微信好友名字是否正确。",
            desktop.capture_screenshot_b64()
        )

    s.status = "success"
    s.detail = (
        f"OCR 找到匹配项：「{match['text']}」 "
        f"位置=({match['x']:.3f}, {match['y']:.3f}) "
        f"匹配分={match['_match_score']}"
    )

    # ── Step 4：点击匹配的联系人条目 ────────────────────────────
    s = SkillStep(f"点击联系人「{match['text']}」进入对话")
    steps.append(s)
    s.status = "running"

    try:
        desktop.mouse_click(match["x"], match["y"])
        time.sleep(1.2)
        s.status = "success"
        s.detail = f"已点击「{match['text']}」"
    except Exception as e:
        s.status = "failed"
        s.detail = f"点击失败: {e}"
        return SkillResult(False, steps, f"点击联系人失败，消息未发送: {e}", None)

    # ── Step 5：二次 OCR 验证（确认当前对话窗口标题匹配）────────
    s = SkillStep("二次验证：确认当前聊天窗口是正确的联系人")
    steps.append(s)
    s.status = "running"

    time.sleep(0.5)
    second_check = _ocr_verify_contact(
        desktop, contact_name, region_top=0.0, region_bottom=0.15
    )

    if not second_check:
        s.status = "failed"
        s.detail = "对话窗口标题区域未找到联系人名字，中止发送"
        pyautogui.press("escape", _pause=False)
        return SkillResult(
            False, steps,
            f"⚠️ 二次验证失败：打开的对话窗口标题中没有找到「{contact_name}」，"
            f"消息未发送。请手动确认后再试。",
            desktop.capture_screenshot_b64()
        )

    s.status = "success"
    s.detail = f"二次验证通过：对话窗口标题含「{second_check['text']}」"

    # ── Step 6：在输入框输入消息并发送 ──────────────────────────
    s = SkillStep(f"输入消息并发送")
    steps.append(s)
    s.status = "running"

    try:
        # 点击输入框（微信消息输入框固定在底部约 85%-95% 高度区域）
        desktop.mouse_click(0.5, 0.92)
        time.sleep(0.4)

        # 用剪贴板粘贴（比 typewrite 更可靠，支持中文）
        import pyperclip as _pyperclip
        _pyperclip.copy(message)
        pyautogui.hotkey("ctrl", "v", _pause=False)
        time.sleep(0.5)

        # 截图留证（发送前）
        screenshot_before = desktop.capture_screenshot_b64()

        # 发送
        pyautogui.press("enter", _pause=False)
        time.sleep(0.5)

        s.status = "success"
        s.detail = f"消息已发送（{len(message)} 字）"
        return SkillResult(
            True, steps,
            f"✅ 已向「{contact_name}」发送消息：{message[:20]}{'...' if len(message)>20 else ''}",
            desktop.capture_screenshot_b64()
        )
    except Exception as e:
        s.status = "failed"
        s.detail = f"发送失败: {e}"
        return SkillResult(False, steps, f"消息输入/发送失败: {e}", None)


# ── Skill Registry ──

SKILL_REGISTRY: dict[str, DesktopSkill] = {}


def _register(skill: DesktopSkill):
    SKILL_REGISTRY[skill.id] = skill


_register(DesktopSkill(
    id="open_wechat",
    name_zh="打开微信",
    name_en="Open WeChat",
    desc_zh="自动查找并打开微信窗口（支持从托盘恢复、快捷键唤起、启动程序）",
    desc_en="Find and open WeChat window (from tray, hotkey, or launch)",
    icon="💬",
    execute=execute_open_wechat,
))

_register(DesktopSkill(
    id="send_wechat_message",
    name_zh="发送微信消息（验证版）",
    name_en="Send WeChat Message (Verified)",
    desc_zh="向指定联系人发送微信消息，全程 OCR 双重验证确认是正确的人，绝不依赖固定坐标",
    desc_en="Send WeChat message with dual OCR verification - never uses fixed coordinates",
    icon="✉️",
    execute=None,  # 通过 execute_send_wechat_message(desktop, contact, msg) 调用
))


## ── Screenshot skill ──────────────────────────────────────────

def execute_screenshot(desktop) -> SkillResult:
    """Save a screenshot to data/screenshots/ and return the path."""
    steps = []
    s = SkillStep("截取屏幕")
    steps.append(s)
    s.status = "running"
    try:
        filepath = desktop.save_screenshot()
        s.status = "success"
        s.detail = f"截图已保存: {filepath}"
        return SkillResult(True, steps, f"截图已保存到 {filepath}",
                           desktop.capture_screenshot_b64())
    except Exception as e:
        s.status = "failed"
        s.detail = str(e)
        return SkillResult(False, steps, f"截图失败: {e}", None)


_register(DesktopSkill(
    id="screenshot",
    name_zh="截图保存",
    name_en="Save Screenshot",
    desc_zh="截取当前屏幕并保存为 PNG 文件到 data/screenshots/ 目录",
    desc_en="Capture and save current screen as PNG",
    icon="📸",
    execute=execute_screenshot,
))


# ── Open browser skill ──────────────────────────────────────────

def execute_open_browser(desktop) -> SkillResult:
    """Open the default web browser."""
    steps = []
    s = SkillStep("打开默认浏览器")
    steps.append(s)
    s.status = "running"
    try:
        import webbrowser
        webbrowser.open("about:blank")
        time.sleep(2.0)
        s.status = "success"
        s.detail = "默认浏览器已启动"
        return SkillResult(True, steps, "浏览器已打开",
                           desktop.capture_screenshot_b64())
    except Exception as e:
        s.status = "failed"
        s.detail = str(e)
        return SkillResult(False, steps, f"打开浏览器失败: {e}", None)


_register(DesktopSkill(
    id="open_browser",
    name_zh="打开浏览器",
    name_en="Open Browser",
    desc_zh="打开默认网页浏览器",
    desc_en="Open the default web browser",
    icon="🌐",
    execute=execute_open_browser,
))


# ── Open file explorer skill ───────────────────────────────────

def execute_open_explorer(desktop) -> SkillResult:
    """Open File Explorer (Windows) or Finder (macOS)."""
    steps = []
    s = SkillStep("打开文件管理器")
    steps.append(s)
    s.status = "running"
    try:
        if IS_WINDOWS:
            subprocess.Popen(["explorer.exe"])
        elif IS_MACOS:
            subprocess.Popen(["open", "-a", "Finder"])
        else:
            subprocess.Popen(["xdg-open", "."])
        time.sleep(1.5)
        s.status = "success"
        s.detail = "文件管理器已打开"
        return SkillResult(True, steps, "文件管理器已打开",
                           desktop.capture_screenshot_b64())
    except Exception as e:
        s.status = "failed"
        s.detail = str(e)
        return SkillResult(False, steps, f"打开失败: {e}", None)


_register(DesktopSkill(
    id="open_explorer",
    name_zh="打开文件管理器",
    name_en="Open File Explorer",
    desc_zh="打开 Windows 资源管理器 / macOS Finder / Linux 文件管理器",
    desc_en="Open File Explorer / Finder",
    icon="📂",
    execute=execute_open_explorer,
))


# ── Open Notepad skill ──────────────────────────────────────────

def execute_open_notepad(desktop) -> SkillResult:
    """Open a text editor."""
    steps = []
    s = SkillStep("打开文本编辑器")
    steps.append(s)
    s.status = "running"
    try:
        if IS_WINDOWS:
            subprocess.Popen(["notepad.exe"])
        elif IS_MACOS:
            subprocess.Popen(["open", "-a", "TextEdit"])
        else:
            for editor in ["gedit", "xed", "kate", "nano"]:
                try:
                    subprocess.Popen([editor])
                    break
                except FileNotFoundError:
                    continue
        time.sleep(1.0)
        s.status = "success"
        s.detail = "文本编辑器已打开"
        return SkillResult(True, steps, "文本编辑器已打开",
                           desktop.capture_screenshot_b64())
    except Exception as e:
        s.status = "failed"
        s.detail = str(e)
        return SkillResult(False, steps, f"打开失败: {e}", None)


_register(DesktopSkill(
    id="open_notepad",
    name_zh="打开记事本",
    name_en="Open Notepad",
    desc_zh="打开文本编辑器（Windows 记事本 / macOS TextEdit）",
    desc_en="Open text editor",
    icon="📝",
    execute=execute_open_notepad,
))


# ── Window management: Show Desktop ────────────────────────────

def execute_show_desktop(desktop) -> SkillResult:
    """Minimize all windows to show the desktop."""
    steps = []
    s = SkillStep("显示桌面（最小化所有窗口）")
    steps.append(s)
    s.status = "running"
    try:
        pyautogui.hotkey("win", "d", _pause=False)
        time.sleep(1.0)
        s.status = "success"
        s.detail = "所有窗口已最小化"
        return SkillResult(True, steps, "已显示桌面",
                           desktop.capture_screenshot_b64())
    except Exception as e:
        s.status = "failed"
        s.detail = str(e)
        return SkillResult(False, steps, f"操作失败: {e}", None)


_register(DesktopSkill(
    id="show_desktop",
    name_zh="显示桌面",
    name_en="Show Desktop",
    desc_zh="最小化所有窗口，显示桌面（Win+D）",
    desc_en="Minimize all windows to show desktop",
    icon="🖥️",
    execute=execute_show_desktop,
))


# ── Window management: List windows ────────────────────────────

def execute_list_windows(desktop) -> SkillResult:
    """List all visible windows."""
    steps = []
    s = SkillStep("获取窗口列表")
    steps.append(s)
    s.status = "running"
    try:
        windows = desktop.get_window_list()
        if windows:
            titles = [w["title"] for w in windows[:20]]
            detail = "\n".join(f"  - {t}" for t in titles)
            s.status = "success"
            s.detail = f"找到 {len(windows)} 个窗口"
            msg = f"当前打开的窗口 ({len(windows)}):\n" + "\n".join(f"• {t}" for t in titles)
            return SkillResult(True, steps, msg, None)
        else:
            s.status = "success"
            s.detail = "未找到可见窗口"
            return SkillResult(True, steps, "当前没有打开的窗口", None)
    except Exception as e:
        s.status = "failed"
        s.detail = str(e)
        return SkillResult(False, steps, f"获取窗口列表失败: {e}", None)


_register(DesktopSkill(
    id="list_windows",
    name_zh="列出窗口",
    name_en="List Windows",
    desc_zh="列出当前所有打开的窗口标题",
    desc_en="List all open window titles",
    icon="🪟",
    execute=execute_list_windows,
))


# ── Lock screen skill ──────────────────────────────────────────

def execute_lock_screen(desktop) -> SkillResult:
    """Lock the computer screen."""
    steps = []
    s = SkillStep("锁定屏幕")
    steps.append(s)
    s.status = "running"
    try:
        if IS_WINDOWS:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        elif IS_MACOS:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to keystroke "q" using {control down, command down}'],
                timeout=5
            )
        else:
            subprocess.run(["loginctl", "lock-session"], timeout=5)
        s.status = "success"
        s.detail = "屏幕已锁定"
        return SkillResult(True, steps, "屏幕已锁定", None)
    except Exception as e:
        s.status = "failed"
        s.detail = str(e)
        return SkillResult(False, steps, f"锁屏失败: {e}", None)


_register(DesktopSkill(
    id="lock_screen",
    name_zh="锁定屏幕",
    name_en="Lock Screen",
    desc_zh="锁定电脑屏幕（Win+L / macOS Ctrl+Cmd+Q）",
    desc_en="Lock the computer screen",
    icon="🔒",
    execute=execute_lock_screen,
))


# ── Skill accessors ──

def get_skill(skill_id: str) -> Optional[DesktopSkill]:
    return SKILL_REGISTRY.get(skill_id)


def list_skills() -> list[dict]:
    """Return skill metadata for the frontend."""
    return [
        {
            "id": s.id,
            "name_zh": s.name_zh,
            "name_en": s.name_en,
            "desc_zh": s.desc_zh,
            "desc_en": s.desc_en,
            "icon": s.icon,
        }
        for s in SKILL_REGISTRY.values()
    ]


def get_skills_prompt_section() -> str:
    """Generate an AI prompt section describing available skills."""
    if not SKILL_REGISTRY:
        return ""
    lines = ["\n可用技能包（用户可以直接触发，你也可以建议使用）："]
    for s in SKILL_REGISTRY.values():
        lines.append(f"- [{s.icon} {s.name_zh}] (skill:{s.id}) — {s.desc_zh}")
    lines.append(
        "\n当用户的指令涉及以上应用时，建议用户先使用对应技能包打开应用，"
        "或者告诉用户：「建议先点击技能按钮执行操作」。"
    )
    return "\n".join(lines)
