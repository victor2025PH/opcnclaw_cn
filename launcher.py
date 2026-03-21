"""
十三香小龙虾 统一启动器

功能：
1. 启动自检（缺包/缺文件 → 明确提示）
2. 启动 FastAPI 服务（子线程）
3. 启动系统托盘图标 + 上下文感知引擎
4. 轮询等待服务就绪 → 自动打开浏览器
5. S2S 模式自动检测 + 情感引擎初始化

用法：
  python launcher.py          # 正常启动
  python launcher.py --nogui  # 无GUI模式（服务器模式）
  python launcher.py --setup  # 强制进入设置向导
"""

import argparse
import os
import sys

# 强制 stdout/stderr 使用 UTF-8（修复 Windows GBK 控制台乱码/崩溃）
# pythonw.exe 没有 stdout，需要先判断是否为 None
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import asyncio
import threading
import time
import webbrowser
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

PORTABLE_MODE = (ROOT / "portable.flag").exists()

from loguru import logger

# ──────────────────────────────────────────────────────
# 日志配置
# 便携模式：所有数据严格在 ROOT 内，不写 APPDATA
# 普通模式：优先 ROOT/logs，只读目录时回退到 APPDATA
# ──────────────────────────────────────────────────────
def _log_dir():
    base = ROOT / "logs"
    try:
        base.mkdir(exist_ok=True)
        (base / ".write_test").write_text("")
        (base / ".write_test").unlink()
        return str(base)
    except (OSError, PermissionError):
        if PORTABLE_MODE:
            base.mkdir(parents=True, exist_ok=True)
            return str(base)
        fallback = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "ShisanXiang" / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return str(fallback)

_LOG_DIR = _log_dir()
_LOG_LEVEL = os.environ.get("OPENCLAW_LOG_LEVEL", "DEBUG").upper()
_LOG_ROTATION = os.environ.get("OPENCLAW_LOG_ROTATION", "5 MB")
_LOG_RETENTION = os.environ.get("OPENCLAW_LOG_RETENTION", "14 days")

logger.remove()
if sys.stdout:
    logger.add(sys.stdout, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:8}</level> | {message}")
logger.add(os.path.join(_LOG_DIR, "十三香小龙虾.log"), level=_LOG_LEVEL,
           rotation=_LOG_ROTATION, retention=_LOG_RETENTION,
           compression="zip", encoding="utf-8", enqueue=True)
logger.add(os.path.join(_LOG_DIR, "error.log"), level="ERROR",
           rotation="2 MB", retention="30 days",
           compression="zip", encoding="utf-8", enqueue=True)


def _read_version():
    vf = Path("version.txt")
    return vf.read_text(encoding="utf-8").strip() if vf.exists() else "3.2.0"


def _print_banner():
    ver = _read_version()
    try:
        print(f"""
+---------------------------------------+
|  十三香小龙虾  v{ver:<23s}|
|  全双工 · 多平台 · 技能增强           |
+---------------------------------------+
""")
    except UnicodeEncodeError:
        print(f"十三香小龙虾 v{ver} - Starting...")


def _self_check():
    """Startup diagnostics — catch missing packages before they crash the server."""
    issues = []

    import importlib
    required = {
        "fastapi": "pip install fastapi",
        "uvicorn": "pip install uvicorn",
        "openai": "pip install openai",
        "httpx": "pip install httpx",
        "dotenv": "pip install python-dotenv",
    }
    for mod, fix in required.items():
        pkg = "python-dotenv" if mod == "dotenv" else mod
        try:
            importlib.import_module(mod)
        except ImportError:
            issues.append(f"  缺少 {pkg} → 修复: {fix}")

    env_path = ROOT / ".env"
    if not env_path.exists():
        tpl = ROOT / ".env.template"
        if tpl.exists():
            import shutil
            shutil.copy(str(tpl), str(env_path))
            logger.info("已从 .env.template 自动创建 .env 文件")
        else:
            issues.append("  缺少 .env 文件 → 请从 .env.template 复制一份")

    if issues:
        logger.error("启动自检发现问题:\n" + "\n".join(issues))
        print("\n!!! 启动自检发现以下问题 !!!")
        for i in issues:
            print(i)
        print("\n请修复后重新启动。\n")
        return False
    logger.info("启动自检通过")
    return True


# ──────────────────────────────────────────────────────
# 全局快捷键（Windows RegisterHotKey，无第三方依赖）
# ──────────────────────────────────────────────────────

def _start_hotkeys(cfg, on_settings, on_quit):
    """Register global hotkeys via Windows API in a dedicated thread."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    _SHORTCUTS_MAP = {
        "settings": (1, 0x0002 | 0x0004, 0x4F),   # Ctrl+Shift+O
        "quit":     (2, 0x0002 | 0x0004, 0x58),   # Ctrl+Shift+X
    }
    _CALLBACKS = {"settings": on_settings, "quit": on_quit}

    enabled = set(getattr(cfg, 'shortcuts_enabled', ['settings', 'quit']))

    def _loop():
        user32 = ctypes.windll.user32
        registered = []
        for sid, (hid, mods, vk) in _SHORTCUTS_MAP.items():
            if sid in enabled:
                if user32.RegisterHotKey(None, hid, mods, vk):
                    registered.append((hid, sid))
                    logger.info(f"⌨️  快捷键已注册: {sid}")
                else:
                    logger.warning(f"快捷键注册失败: {sid} (可能已被占用)")

        if not registered:
            return

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                for hid, sid in registered:
                    if msg.wParam == hid:
                        cb = _CALLBACKS.get(sid)
                        if cb:
                            try:
                                cb()
                            except Exception as e:
                                logger.debug(f"快捷键回调异常: {e}")

        for hid, _ in registered:
            user32.UnregisterHotKey(None, hid)

    t = threading.Thread(target=_loop, name="hotkeys", daemon=True)
    t.start()
    return t


# ──────────────────────────────────────────────────────
# 服务启动
# ──────────────────────────────────────────────────────

def _start_server(cfg, tray=None) -> threading.Thread:
    """在后台线程启动 FastAPI 服务"""
    def _run():
        try:
            import uvicorn
            from src.server.main import app
            http_port = cfg.http_port
            https_port = cfg.https_port
            # 检查端口是否可用
            if not _check_port(http_port) or not _check_port(https_port):
                logger.error(f"端口 {http_port} 或 {https_port} 被占用，尝试终止占用进程...")
                _free_ports(http_port, https_port)
                time.sleep(1)

            logger.info(f"🚀 启动服务器 HTTP:{http_port} HTTPS:{https_port}")

            # 双端口配置 — 按优先级检查证书路径
            ssl_cert = ssl_key = None
            for cert_path, key_path in [
                (Path("certs/server.crt"), Path("certs/server.key")),
                (Path("ssl/server.crt"), Path("ssl/server.key")),
                (Path("ssl/cert.pem"), Path("ssl/key.pem")),
            ]:
                if cert_path.exists() and key_path.exists():
                    ssl_cert, ssl_key = cert_path, key_path
                    break

            if not ssl_cert:
                try:
                    from src.server.certs import ensure_certs
                    _, cert_str, key_str = ensure_certs("certs")
                    ssl_cert, ssl_key = Path(cert_str), Path(key_str)
                    logger.info(f"SSL certificates generated: {ssl_cert}")
                except Exception as e:
                    logger.warning(f"SSL cert generation failed: {e} — HTTPS disabled")
                    ssl_cert = ssl_key = None

            import asyncio
            from uvicorn import Config, Server
            import multiprocessing as mp

            _no_stdout = sys.stdout is None
            _uvi_log = None if _no_stdout else "warning"

            async def _run_both():
                servers = []
                # HTTPS
                if ssl_cert and ssl_key and ssl_cert.exists() and ssl_key.exists():
                    https_config = Config(
                        app, host="0.0.0.0", port=https_port,
                        ssl_certfile=str(ssl_cert), ssl_keyfile=str(ssl_key),
                        loop="asyncio", log_level=_uvi_log, log_config=None if _no_stdout else uvicorn.config.LOGGING_CONFIG,
                    )
                    servers.append(Server(https_config))

                # HTTP
                http_config = Config(
                    app, host="0.0.0.0", port=http_port,
                    loop="asyncio", log_level=_uvi_log, log_config=None if _no_stdout else uvicorn.config.LOGGING_CONFIG,
                )
                servers.append(Server(http_config))

                await asyncio.gather(*[s.serve() for s in servers])

            asyncio.run(_run_both())

        except Exception as e:
            logger.error(f"服务器启动失败: {e}")
            if tray:
                tray.update_status(f"服务启动失败: {e}", "error")
                tray.show_notification("十三香小龙虾 启动失败", str(e))

    t = threading.Thread(target=_run, daemon=True, name="十三香小龙虾-server")
    t.start()
    return t


def _check_port(port: int) -> bool:
    """检查端口是否可用"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _free_ports(*ports):
    """尝试释放被占用的端口（仅 Windows）"""
    try:
        import subprocess
        for port in ports:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = parts[-1]
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
                    logger.info(f"已终止占用端口 {port} 的进程 PID {pid}")
    except Exception as e:
        logger.warning(f"端口释放失败: {e}")


# ──────────────────────────────────────────────────────
# 首次运行向导
# ──────────────────────────────────────────────────────

def _first_run_wizard(cfg):
    """首次运行时显示的简单欢迎向导"""
    try:
        import tkinter as tk
        import tkinter.ttk as ttk
        import webbrowser

        root = tk.Tk()
        root.title("欢迎使用十三香小龙虾！")
        root.geometry("540x420")
        root.resizable(False, False)
        root.configure(bg="#1a1a2e")

        tk.Label(root, text="🦞 欢迎使用十三香小龙虾", font=("", 20, "bold"),
                 bg="#1a1a2e", fg="#a78bfa").pack(pady=20)
        tk.Label(root, text="全双工 AI 语音助手 | 本地部署 | 隐私安全",
                 font=("", 12), bg="#1a1a2e", fg="#9ca3af").pack()

        # 步骤提示
        frame = tk.Frame(root, bg="#1a1a2e")
        frame.pack(pady=20, padx=30, fill="x")

        steps = [
            ("✅", "服务已启动", "#22c55e"),
            ("🔑", "配置 AI 平台 Key（推荐智谱免费）", "#a78bfa"),
            ("🎙️", "允许麦克风权限", "#f59e0b"),
            ("📱", "手机扫码使用 / 打开网页版", "#06b6d4"),
        ]
        for icon, text, color in steps:
            row = tk.Frame(frame, bg="#1a1a2e")
            row.pack(anchor="w", pady=4)
            tk.Label(row, text=f"{icon} {text}", font=("", 12),
                     bg="#1a1a2e", fg=color).pack(side="left")

        # 按钮
        btn_frame = tk.Frame(root, bg="#1a1a2e")
        btn_frame.pack(pady=10)

        def _open_settings():
            root.destroy()
            from src.gui.settings import open_settings
            open_settings()

        def _open_web():
            webbrowser.open(f"https://localhost:{cfg.https_port}/app")
            root.destroy()

        def _open_qr():
            webbrowser.open(f"https://localhost:{cfg.https_port}/qr")
            root.destroy()

        tk.Button(btn_frame, text="⚙️ 去配置 AI Key", font=("", 12),
                  bg="#6366f1", fg="white", relief="flat", padx=16, pady=8,
                  command=_open_settings).grid(row=0, column=0, padx=6)
        tk.Button(btn_frame, text="🌐 打开网页版", font=("", 12),
                  bg="#374151", fg="white", relief="flat", padx=16, pady=8,
                  command=_open_web).grid(row=0, column=1, padx=6)
        tk.Button(btn_frame, text="📱 手机扫码", font=("", 12),
                  bg="#374151", fg="white", relief="flat", padx=16, pady=8,
                  command=_open_qr).grid(row=0, column=2, padx=6)

        tk.Button(root, text="以后再说，直接使用", font=("", 10),
                  bg="#1a1a2e", fg="#6b7280", relief="flat",
                  command=root.destroy).pack()

        cfg.mark_first_run_done()
        root.mainloop()
    except Exception as e:
        logger.warning(f"向导窗口启动失败: {e}，跳过")


# ──────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────

def main():
    _print_banner()

    parser = argparse.ArgumentParser(description="十三香小龙虾启动器")
    parser.add_argument("--nogui", action="store_true", help="无GUI模式")
    parser.add_argument("--setup", action="store_true", help="强制设置向导")
    parser.add_argument("--port", type=int, default=None, help="覆盖 HTTP 端口")
    args = parser.parse_args()

    # 启动自检：缺包/缺文件在这里拦截，而不是启动后崩溃
    if not _self_check():
        input("按回车键退出...")
        sys.exit(1)

    # 环境检查（启动时自动修复常见问题）
    try:
        from src.server.env_check import check_and_log
        env_report = check_and_log()
    except Exception:
        env_report = {"all_ok": True}

    # 加载配置
    from src.router.config import RouterConfig
    cfg = RouterConfig()
    logger.info(f"⚙️  配置已加载 | 调度模式: {cfg.routing_mode}")

    # 初始化路由器
    from src.router.router import AIRouter
    router = AIRouter(cfg)
    active = router.get_active_provider()
    if active:
        logger.info(f"🤖 当前 AI 平台: {active}")
    else:
        logger.warning("⚠️  未配置 AI 平台，请打开设置填写 API Key")

    # 初始化技能引擎
    try:
        from skills._engine import SkillExecutor
        executor = SkillExecutor()
        logger.info("🧩 技能引擎已就绪")
    except Exception as e:
        logger.warning(f"技能引擎初始化失败: {e}")

    # 系统托盘
    tray = None
    if not args.nogui:
        from src.gui.tray import TrayIcon
        from src.gui.settings import open_settings

        tray = TrayIcon(
            on_open_settings=lambda: open_settings(router=router),
            on_quit=lambda: os._exit(0),
            http_port=cfg.http_port,
            https_port=cfg.https_port,
        )
        tray.run()

    # 全局快捷键
    if not args.nogui:
        _start_hotkeys(
            cfg,
            on_settings=lambda: open_settings(router=router),
            on_quit=lambda: os._exit(0),
        )

    # 上下文感知引擎
    try:
        from src.server.context import ContextEngine
        ctx_engine = ContextEngine()

        def _on_ctx_event(ev):
            logger.info(f"💡 Context: [{ev.type}] {ev.message}")
        ctx_engine.on_event(_on_ctx_event)
        import threading as _threading
        _threading.Thread(target=lambda: asyncio.run(ctx_engine.start()),
                          daemon=True).start()
        logger.info("🧠 上下文感知引擎已启动")
    except Exception as e:
        logger.debug(f"Context engine not started: {e}")

    # S2S 模式检测
    if getattr(router, 's2s_available', False):
        logger.info(f"⚡ S2S 端到端语音模式可用: {router.s2s.backend_name}")
    else:
        logger.info("📡 使用 STT → LLM → TTS 管道模式")

    # 启动服务器
    logger.info("🚀 正在启动服务器...")
    _start_server(cfg, tray)

    # 轮询等待服务器 HTTP 端口就绪（模型在后台异步加载，ping 通常 3 秒内就绪）
    import urllib.request
    server_ok = False
    for _ in range(60):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{cfg.http_port}/api/ping", timeout=2)
            server_ok = True
            break
        except Exception:
            pass

    if not server_ok:
        logger.warning("服务器 HTTP 端口未响应，但进程仍在运行")

    if tray:
        if active:
            tray.update_status(f"运行中 | {active}", "ok")
            tray.show_notification("十三香小龙虾 已启动",
                                    f"AI: {active}\n访问: http://localhost:{cfg.http_port}/app")
        else:
            tray.update_status("未配置 AI Key", "warning")
            tray.show_notification("十三香小龙虾 需要配置",
                                    "请点击托盘图标 → 打开设置 → 填写 AI Key")

    # 始终打开浏览器（页面有自己的加载屏，可以等待模型就绪）
    if not args.nogui:
        setup_done = os.environ.get("OPENCLAW_SETUP_DONE", "").lower() == "true"
        if cfg.first_run or args.setup or not setup_done:
            webbrowser.open(f"https://localhost:{cfg.https_port}/setup")
        else:
            webbrowser.open(f"https://localhost:{cfg.https_port}/app")
            # 启动桌宠（小窗口）
            try:
                import threading
                def _open_pet():
                    import time as _t; _t.sleep(2)
                    webbrowser.open(f"https://localhost:{cfg.https_port}/pet")
                threading.Thread(target=_open_pet, daemon=True).start()
            except Exception:
                pass

    # 保持主线程运行
    logger.info(f"✅ 十三香小龙虾就绪！打开: https://localhost:{cfg.https_port}/app")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 十三香小龙虾正在退出...")
        sys.exit(0)


if __name__ == "__main__":
    main()
