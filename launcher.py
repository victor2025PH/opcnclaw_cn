"""
OpenClaw v3.0 统一启动器

功能：
1. 初始化配置（首次运行向导）
2. 启动 FastAPI 服务（子线程）
3. 启动系统托盘图标 + 上下文感知引擎
4. 管理生命周期（优雅退出）
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

from loguru import logger

# ──────────────────────────────────────────────────────
# 日志配置
# ──────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
_LOG_LEVEL = os.environ.get("OPENCLAW_LOG_LEVEL", "DEBUG").upper()
_LOG_ROTATION = os.environ.get("OPENCLAW_LOG_ROTATION", "5 MB")
_LOG_RETENTION = os.environ.get("OPENCLAW_LOG_RETENTION", "14 days")

logger.remove()
if sys.stdout:
    logger.add(sys.stdout, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:8}</level> | {message}")
logger.add("logs/openclaw.log", level=_LOG_LEVEL,
           rotation=_LOG_ROTATION, retention=_LOG_RETENTION,
           compression="zip", encoding="utf-8", enqueue=True)
logger.add("logs/error.log", level="ERROR",
           rotation="2 MB", retention="30 days",
           compression="zip", encoding="utf-8", enqueue=True)


def _print_banner():
    # 兼容 GBK 控制台（Windows CMD 默认编码）
    try:
        print("""
╔═══════════════════════════════════════╗
║   OpenClaw AI 语音助手  v3.0          ║
║   全双工 · 多平台 · 技能增强          ║
╚═══════════════════════════════════════╝
""")
    except UnicodeEncodeError:
        print("OpenClaw AI v3.0 - Starting...")


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

    enabled = set(cfg.shortcuts_enabled)

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

            async def _run_both():
                servers = []
                # HTTPS
                if ssl_cert and ssl_key and ssl_cert.exists() and ssl_key.exists():
                    https_config = Config(
                        app, host="0.0.0.0", port=https_port,
                        ssl_certfile=str(ssl_cert), ssl_keyfile=str(ssl_key),
                        loop="asyncio", log_level="warning",
                    )
                    servers.append(Server(https_config))

                # HTTP
                http_config = Config(
                    app, host="0.0.0.0", port=http_port,
                    loop="asyncio", log_level="warning",
                )
                servers.append(Server(http_config))

                await asyncio.gather(*[s.serve() for s in servers])

            asyncio.run(_run_both())

        except Exception as e:
            logger.error(f"服务器启动失败: {e}")
            if tray:
                tray.update_status(f"服务启动失败: {e}", "error")
                tray.show_notification("OpenClaw 启动失败", str(e))

    t = threading.Thread(target=_run, daemon=True, name="openclaw-server")
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
        root.title("欢迎使用 OpenClaw！")
        root.geometry("540x420")
        root.resizable(False, False)
        root.configure(bg="#1a1a2e")

        tk.Label(root, text="🦞 欢迎使用 OpenClaw", font=("", 20, "bold"),
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
            webbrowser.open(f"http://localhost:{cfg.http_port}/qr")
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

    parser = argparse.ArgumentParser(description="OpenClaw 启动器")
    parser.add_argument("--nogui", action="store_true", help="无GUI模式")
    parser.add_argument("--setup", action="store_true", help="强制设置向导")
    parser.add_argument("--port", type=int, default=None, help="覆盖 HTTP 端口")
    args = parser.parse_args()

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

    # 等待服务器就绪
    time.sleep(2.5)

    if tray:
        if active:
            tray.update_status(f"运行中 | {active}", "ok")
            tray.show_notification("OpenClaw 已启动",
                                    f"AI: {active}\n访问: http://localhost:{cfg.http_port}/app")
        else:
            tray.update_status("未配置 AI Key", "warning")
            tray.show_notification("OpenClaw 需要配置",
                                    "请点击托盘图标 → 打开设置 → 填写 AI Key")

    # 首次运行向导
    if not args.nogui:
        if cfg.first_run or args.setup:
            threading.Thread(target=lambda: _first_run_wizard(cfg), daemon=True).start()
        else:
            # 自动打开浏览器
            webbrowser.open(f"http://localhost:{cfg.http_port}/qr")

    # 保持主线程运行
    logger.info(f"✅ OpenClaw 就绪！网页版: http://localhost:{cfg.http_port}/app")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 OpenClaw 正在退出...")
        sys.exit(0)


if __name__ == "__main__":
    main()
