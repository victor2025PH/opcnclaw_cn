"""
Model on-demand download manager.

Lets cloud-mode users upgrade to local models without reinstalling.
Tracks download progress and supports resume.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger

MODELS_DIR = Path("models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

STATUS_FILE = MODELS_DIR / "status.json"


@dataclass
class ModelInfo:
    id: str
    name: str
    description: str
    size_mb: int
    pip_packages: List[str]
    category: str
    requires_gpu: bool = False
    min_vram_gb: float = 0
    installed: bool = False


AVAILABLE_MODELS: List[ModelInfo] = [
    ModelInfo(
        id="sensevoice",
        name="SenseVoice STT",
        description="阿里语音识别，15x 快于 Whisper，带情感检测",
        size_mb=1200,
        pip_packages=["funasr"],
        category="stt",
        requires_gpu=True,
        min_vram_gb=1.0,
    ),
    ModelInfo(
        id="faster-whisper",
        name="Faster Whisper STT",
        description="本地语音识别（GPU/CPU），多语言支持",
        size_mb=800,
        pip_packages=["faster-whisper"],
        category="stt",
    ),
    ModelInfo(
        id="torch-cpu",
        name="PyTorch (CPU)",
        description="深度学习运行时 — CPU 版，本地模型必需",
        size_mb=200,
        pip_packages=["torch --index-url https://download.pytorch.org/whl/cpu"],
        category="runtime",
    ),
    ModelInfo(
        id="torch-cuda",
        name="PyTorch (CUDA GPU)",
        description="深度学习运行时 — GPU 加速版",
        size_mb=2500,
        pip_packages=["torch"],
        category="runtime",
        requires_gpu=True,
    ),
    ModelInfo(
        id="silero-vad",
        name="Silero VAD",
        description="语音活动检测，用于判断是否在说话",
        size_mb=50,
        pip_packages=["silero-vad"],
        category="vad",
    ),
    ModelInfo(
        id="vision",
        name="视觉控制套件",
        description="OCR + 屏幕识别 + 自动化操作",
        size_mb=150,
        pip_packages=[
            "rapidocr-onnxruntime", "mss", "pyautogui", "uiautomation"],
        category="vision",
    ),
    ModelInfo(
        id="transformers",
        name="Transformers",
        description="HuggingFace 模型框架 — GLM-4-Voice 等需要",
        size_mb=300,
        pip_packages=["transformers", "torchaudio"],
        category="runtime",
        requires_gpu=True,
    ),
]


def _load_status() -> Dict[str, dict]:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_status(status: Dict[str, dict]):
    STATUS_FILE.write_text(
        json.dumps(status, indent=2, ensure_ascii=False),
        encoding="utf-8")


def get_models() -> List[ModelInfo]:
    status = _load_status()
    for m in AVAILABLE_MODELS:
        m.installed = status.get(m.id, {}).get("installed", False)
    return AVAILABLE_MODELS


def check_installed(model_id: str) -> bool:
    model = next((m for m in AVAILABLE_MODELS if m.id == model_id), None)
    if not model:
        return False
    for pkg in model.pip_packages:
        pkg_name = pkg.split()[0].split(">=")[0].split("==")[0]
        try:
            __import__(pkg_name.replace("-", "_"))
        except ImportError:
            return False
    return True


def is_online(timeout: float = 3.0) -> bool:
    import socket
    try:
        sock = socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


def install_model(
    model_id: str,
    on_progress: Optional[Callable[[str, int], None]] = None,
    python_exe: Optional[str] = None,
) -> bool:
    model = next((m for m in AVAILABLE_MODELS if m.id == model_id), None)
    if not model:
        logger.error(f"Unknown model: {model_id}")
        return False

    if not is_online():
        logger.error("No network — cannot download model")
        if on_progress:
            on_progress("❌ 无网络连接，无法下载模型", -1)
        return False

    py = python_exe or sys.executable
    status = _load_status()

    if on_progress:
        on_progress(f"正在安装 {model.name}...", 0)

    total = len(model.pip_packages)
    for i, pkg in enumerate(model.pip_packages):
        if on_progress:
            pct = int((i / total) * 100)
            on_progress(f"安装 {pkg.split()[0]}...", pct)

        cmd = [py, "-m", "pip", "install"] + pkg.split()
        logger.info(f"pip install: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                logger.error(
                    f"pip install {pkg} failed: {result.stderr[:500]}")
                if on_progress:
                    on_progress(f"安装 {pkg} 失败", -1)
                return False
        except subprocess.TimeoutExpired:
            logger.error(f"pip install {pkg} timed out")
            if on_progress:
                on_progress(f"安装 {pkg} 超时", -1)
            return False
        except Exception as e:
            logger.error(f"pip install error: {e}")
            return False

    status[model_id] = {
        "installed": True,
        "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "packages": [p.split()[0] for p in model.pip_packages],
    }
    _save_status(status)

    if on_progress:
        on_progress(f"{model.name} 安装完成", 100)

    logger.info(f"Model installed: {model.name}")
    return True


def uninstall_model(model_id: str) -> bool:
    model = next((m for m in AVAILABLE_MODELS if m.id == model_id), None)
    if not model:
        return False

    for pkg in model.pip_packages:
        pkg_name = pkg.split()[0]
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", pkg_name, "-y"],
                capture_output=True, timeout=120)
        except Exception:
            pass

    status = _load_status()
    status.pop(model_id, None)
    _save_status(status)
    logger.info(f"Model uninstalled: {model.name}")
    return True


def get_gpu_info() -> dict:
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {
                "available": True,
                "name": props.name,
                "vram_gb": round(props.total_mem / 1024**3, 1),
            }
    except Exception:
        pass
    return {"available": False, "name": "", "vram_gb": 0}


def get_install_mode() -> str:
    status = _load_status()
    has_torch = status.get("torch-cpu", {}).get("installed", False) or \
                status.get("torch-cuda", {}).get("installed", False)
    has_stt = status.get("sensevoice", {}).get("installed", False) or \
              status.get("faster-whisper", {}).get("installed", False)
    if has_torch and has_stt:
        return "full"
    return "minimal"


def get_disk_space() -> dict:
    try:
        total, used, free = shutil.disk_usage(Path.cwd())
        return {
            "total_gb": round(total / 1024**3, 1),
            "free_gb": round(free / 1024**3, 1),
        }
    except Exception:
        return {"total_gb": 0, "free_gb": 0}


def get_installed_summary() -> dict:
    models = get_models()
    installed = [m for m in models if m.installed]
    total_size = sum(m.size_mb for m in installed)
    return {
        "installed_count": len(installed),
        "total_count": len(models),
        "installed_size_mb": total_size,
        "mode": get_install_mode(),
    }
