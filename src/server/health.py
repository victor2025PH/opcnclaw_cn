"""
Startup health checker — validates all critical components.

Used by:
  1. /api/health endpoint for monitoring
  2. Settings UI "诊断信息" panel
  3. Startup self-check log
"""

import importlib
import os
import platform
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from loguru import logger


@dataclass
class ComponentStatus:
    name: str
    ok: bool
    version: str = ""
    detail: str = ""
    latency_ms: int = 0


_CORE_PACKAGES = [
    "fastapi", "uvicorn", "websockets", "httpx", "numpy",
    "pydantic", "loguru", "customtkinter",
]

_OPTIONAL_PACKAGES = [
    ("torch", "PyTorch"),
    ("funasr", "SenseVoice"),
    ("faster_whisper", "Faster Whisper"),
    ("edge_tts", "Edge TTS"),
    ("rapidocr_onnxruntime", "RapidOCR"),
]


class HealthChecker:

    def __init__(self, base_dir: Optional[str] = None):
        self._base = Path(base_dir) if base_dir else Path.cwd()

    def check_python(self) -> ComponentStatus:
        v = platform.python_version()
        major, minor = sys.version_info[:2]
        ok = major == 3 and minor >= 10
        return ComponentStatus(
            name="Python",
            ok=ok,
            version=v,
            detail="" if ok else f"需要 Python 3.10+，当前 {v}",
        )

    def check_core_packages(self) -> ComponentStatus:
        missing = []
        for pkg in _CORE_PACKAGES:
            try:
                importlib.import_module(pkg)
            except ImportError:
                missing.append(pkg)
        ok = len(missing) == 0
        return ComponentStatus(
            name="核心依赖",
            ok=ok,
            version=f"{len(_CORE_PACKAGES) - len(missing)}/{len(_CORE_PACKAGES)}",
            detail=f"缺失: {', '.join(missing)}" if missing else "全部就绪",
        )

    def check_optional_packages(self) -> ComponentStatus:
        installed = []
        for pkg, label in _OPTIONAL_PACKAGES:
            try:
                importlib.import_module(pkg)
                installed.append(label)
            except Exception:
                pass
        return ComponentStatus(
            name="可选组件",
            ok=True,
            version=f"{len(installed)}/{len(_OPTIONAL_PACKAGES)}",
            detail=", ".join(installed) if installed else "无（纯云端模式）",
        )

    def check_ssl(self) -> ComponentStatus:
        for cert_dir, cert_name, key_name in [
            ("certs", "server.crt", "server.key"),
            ("ssl", "server.crt", "server.key"),
            ("ssl", "cert.pem", "key.pem"),
        ]:
            cert = self._base / cert_dir / cert_name
            key = self._base / cert_dir / key_name
            if cert.exists() and key.exists():
                return ComponentStatus(
                    name="SSL 证书",
                    ok=True,
                    detail=f"就绪 ({cert_dir}/{cert_name})",
                )
        return ComponentStatus(
            name="SSL 证书",
            ok=False,
            detail="缺失 — HTTPS 不可用，运行 install_full.bat 生成",
        )

    def check_config(self) -> ComponentStatus:
        env_file = self._base / ".env"
        ini_file = self._base / "config.ini"
        has_env = env_file.exists()
        has_ini = ini_file.exists()
        ok = has_env or has_ini
        parts = []
        if has_env:
            parts.append(".env")
        if has_ini:
            parts.append("config.ini")
        return ComponentStatus(
            name="配置文件",
            ok=ok,
            detail=", ".join(parts) if parts else "未找到配置文件",
        )

    def check_network(self) -> ComponentStatus:
        t0 = time.perf_counter()
        try:
            sock = socket.create_connection(("8.8.8.8", 53), timeout=3)
            sock.close()
            ms = int((time.perf_counter() - t0) * 1000)
            return ComponentStatus(
                name="网络连接",
                ok=True,
                latency_ms=ms,
                detail=f"延迟 {ms}ms",
            )
        except (OSError, socket.timeout):
            return ComponentStatus(
                name="网络连接",
                ok=False,
                detail="无法连接 — 云端 STT/TTS/AI 不可用",
            )

    def check_ports(self) -> ComponentStatus:
        ports_to_check = [8765, 8766]
        occupied = []
        for port in ports_to_check:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                result = s.connect_ex(("127.0.0.1", port))
                s.close()
                if result == 0:
                    occupied.append(port)
            except Exception:
                pass
        if occupied:
            return ComponentStatus(
                name="端口",
                ok=False,
                detail=f"端口 {', '.join(map(str, occupied))} 已被占用",
            )
        return ComponentStatus(name="端口", ok=True, detail="8765/8766 可用")

    def check_disk_space(self) -> ComponentStatus:
        import shutil
        try:
            total, used, free = shutil.disk_usage(self._base)
            free_gb = round(free / 1024**3, 1)
            ok = free_gb >= 0.5
            return ComponentStatus(
                name="磁盘空间",
                ok=ok,
                version=f"{free_gb} GB 剩余",
                detail="" if ok else "磁盘空间不足 500MB",
            )
        except Exception:
            return ComponentStatus(name="磁盘空间", ok=True, detail="无法检测")

    def run_all(self) -> List[ComponentStatus]:
        checks = [
            self.check_python(),
            self.check_core_packages(),
            self.check_optional_packages(),
            self.check_ssl(),
            self.check_config(),
            self.check_network(),
            self.check_disk_space(),
        ]
        return checks

    def summary(self) -> dict:
        checks = self.run_all()
        failed = [c for c in checks if not c.ok]
        return {
            "healthy": len(failed) == 0,
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "checks": [
                {
                    "name": c.name,
                    "ok": c.ok,
                    "version": c.version,
                    "detail": c.detail,
                    "latency_ms": c.latency_ms,
                }
                for c in checks
            ],
        }

    def log_report(self):
        checks = self.run_all()
        logger.info("═══ OpenClaw 启动健康检查 ═══")
        for c in checks:
            icon = "✅" if c.ok else "❌"
            extra = f" [{c.version}]" if c.version else ""
            note = f" — {c.detail}" if c.detail else ""
            logger.info(f"  {icon} {c.name}{extra}{note}")
        failed = [c for c in checks if not c.ok]
        if failed:
            logger.warning(
                f"  ⚠️ {len(failed)} 项检查未通过，部分功能可能不可用")
        else:
            logger.info("  🎉 所有检查通过")
