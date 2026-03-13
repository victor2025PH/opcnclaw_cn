"""
系统托盘图标 — OpenClaw 常驻后台

优化：使用 PIL 动态生成带状态颜色的托盘图标，
     不依赖外部图标文件。
"""
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    logger.warning("pystray/pillow 未安装，托盘功能不可用")


def _make_icon(color: str = "#6366f1", size: int = 64) -> "Image.Image":
    """动态生成托盘图标（紫色龙虾/麦克风图标）"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 圆形背景
    draw.ellipse([2, 2, size - 2, size - 2], fill=color)
    # 简单麦克风形状（白色）
    cx, cy = size // 2, size // 2
    w, h = size // 8, size // 4
    draw.rounded_rectangle([cx - w, cy - h, cx + w, cy + h // 2],
                           radius=w, fill="white")
    draw.arc([cx - w * 2, cy - h // 2, cx + w * 2, cy + h * 1.2],
             start=0, end=180, fill="white", width=max(2, size // 20))
    draw.line([cx, cy + h // 2, cx, cy + h], fill="white", width=max(2, size // 20))
    draw.line([cx - w, cy + h, cx + w, cy + h], fill="white", width=max(2, size // 20))
    return img


class TrayIcon:
    """OpenClaw 系统托盘图标"""

    def __init__(
        self,
        on_open_settings: Optional[Callable] = None,
        on_quit: Optional[Callable] = None,
        http_port: int = 8766,
        https_port: int = 8765,
    ):
        self.on_open_settings = on_open_settings
        self.on_quit = on_quit
        self.http_port = http_port
        self.https_port = https_port
        self._icon: Optional["pystray.Icon"] = None
        self._status = "正在启动..."
        self._server_running = False

    def _build_menu(self) -> "pystray.Menu":
        import pystray
        return pystray.Menu(
            pystray.MenuItem("🦞 OpenClaw AI 助手", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🌐 打开网页版",
                lambda _: webbrowser.open(f"https://localhost:{self.https_port}/app")),
            pystray.MenuItem("📱 手机扫码连接",
                lambda _: webbrowser.open(f"http://localhost:{self.http_port}/qr")),
            pystray.MenuItem("💬 聊天界面",
                lambda _: webbrowser.open(f"http://localhost:{self.http_port}/chat")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙️ 打开设置", self._open_settings),
            pystray.MenuItem("📋 查看日志",
                lambda _: subprocess.Popen(["notepad", str(Path("logs/server.log").absolute())]
                           if Path("logs/server.log").exists() else
                           ["notepad", str(Path("openclaw.log").absolute())])),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🔄 重启服务", self._restart),
            pystray.MenuItem("❌ 退出", self._quit),
        )

    def _open_settings(self, _=None):
        if self.on_open_settings:
            threading.Thread(target=self.on_open_settings, daemon=True).start()

    def _restart(self, _=None):
        logger.info("用户请求重启服务")
        self.update_status("正在重启...", "warning")
        # 重启主进程
        python = sys.executable
        args = sys.argv[:]
        subprocess.Popen([python] + args)
        if self.on_quit:
            self.on_quit()

    def _quit(self, _=None):
        logger.info("用户退出 OpenClaw")
        if self._icon:
            self._icon.stop()
        if self.on_quit:
            self.on_quit()

    def update_status(self, status: str, level: str = "ok"):
        """更新托盘提示文本和图标颜色"""
        self._status = status
        colors = {"ok": "#22c55e", "warning": "#f59e0b", "error": "#ef4444", "info": "#6366f1"}
        color = colors.get(level, "#6366f1")
        if self._icon:
            self._icon.icon = _make_icon(color)
            self._icon.title = f"OpenClaw — {status}"

    def show_notification(self, title: str, message: str):
        """显示气泡通知"""
        if self._icon:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass

    def run(self):
        """在后台线程启动托盘"""
        if not TRAY_AVAILABLE:
            logger.warning("托盘图标不可用，跳过")
            return
        try:
            import pystray
            icon_img = _make_icon("#6366f1")
            self._icon = pystray.Icon(
                "openclaw",
                icon_img,
                "OpenClaw — 正在启动",
                menu=self._build_menu(),
            )
            threading.Thread(target=self._icon.run, daemon=True).start()
            logger.info("✅ 系统托盘图标已启动")
        except Exception as e:
            logger.warning(f"托盘图标启动失败: {e}")
