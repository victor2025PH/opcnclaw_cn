"""
路由器配置管理 — 读写 config.ini，合并 providers.json
"""
import configparser
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

def _find_config_path() -> Path:
    """Resolve config.ini: check cwd first, then script's ancestor dirs."""
    cwd_path = Path("config.ini")
    if cwd_path.exists():
        return cwd_path
    root = Path(__file__).resolve().parent.parent.parent
    root_path = root / "config.ini"
    if root_path.exists():
        return root_path
    return cwd_path

CONFIG_PATH = _find_config_path()
PROVIDERS_JSON = Path(__file__).parent / "providers.json"


def _load_providers_meta() -> dict:
    with open(PROVIDERS_JSON, encoding="utf-8") as f:
        return json.load(f)


def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def save_config(cfg: configparser.ConfigParser):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)


def get_default_config() -> configparser.ConfigParser:
    """返回出厂默认配置（首次安装时使用）"""
    cfg = configparser.ConfigParser()
    cfg["router"] = {
        "mode": "cost_saving",
        "auto_switch": "true",
        "cooldown_seconds": "60",
        "max_errors": "3",
        "low_balance_alert": "true",
        "low_balance_threshold": "1.0",
    }
    cfg["providers"] = {
        "order": "openclaw,zhipu_flash,baidu_speed,siliconflow_free,deepseek,tongyi",
    }
    cfg["stt"] = {
        "model": "base",
        "language": "zh",
        "device": "cpu",
    }
    cfg["tts"] = {
        "provider": "edge_tts",
        "voice": "zh-CN-XiaoxiaoNeural",
    }
    cfg["system"] = {
        "autostart": "false",
        "minimize_to_tray": "true",
        "http_port": "8766",
        "https_port": "8765",
        "first_run": "true",
        "shortcuts_enabled": "settings,quit",
    }
    cfg["ui"] = {
        "theme": "dark",
        "language": "zh",
        "show_tray_tips": "true",
    }
    return cfg


def ensure_config() -> configparser.ConfigParser:
    """确保 config.ini 存在，不存在则写入默认值"""
    if not CONFIG_PATH.exists():
        cfg = get_default_config()
        save_config(cfg)
        return cfg
    return load_config()


class RouterConfig:
    """统一配置对象，合并 config.ini + providers.json"""

    def __init__(self):
        self._cfg = ensure_config()
        self._meta = _load_providers_meta()
        self._providers_meta: Dict[str, dict] = {
            p["id"]: p for p in self._meta["providers"]
        }

    def reload(self):
        self._cfg = load_config()

    def save(self):
        save_config(self._cfg)

    # ── Router 设置 ──────────────────────────────────
    @property
    def routing_mode(self) -> str:
        return self._cfg.get("router", "mode", fallback="cost_saving")

    @routing_mode.setter
    def routing_mode(self, v: str):
        self._cfg.setdefault("router", {})
        self._cfg["router"]["mode"] = v

    @property
    def auto_switch(self) -> bool:
        return self._cfg.getboolean("router", "auto_switch", fallback=True)

    @property
    def cooldown_seconds(self) -> int:
        return self._cfg.getint("router", "cooldown_seconds", fallback=60)

    @property
    def provider_order(self) -> List[str]:
        raw = self._cfg.get("providers", "order", fallback="")
        return [p.strip() for p in raw.split(",") if p.strip()]

    # ── 单个 Provider 设置 ──────────────────────────
    def get_provider_key(self, pid: str) -> Optional[str]:
        section = f"provider.{pid}"
        if self._cfg.has_section(section):
            return self._cfg.get(section, "api_key", fallback=None)
        # 降级读环境变量
        meta = self._providers_meta.get(pid, {})
        env_key = meta.get("key_env", "")
        return os.getenv(env_key) if env_key else None

    def set_provider_key(self, pid: str, key: str):
        section = f"provider.{pid}"
        if not self._cfg.has_section(section):
            self._cfg.add_section(section)
        self._cfg[section]["api_key"] = key

    def get_provider_model(self, pid: str) -> str:
        section = f"provider.{pid}"
        if self._cfg.has_section(section):
            return self._cfg.get(section, "model",
                fallback=self._providers_meta.get(pid, {}).get("default_model", ""))
        return self._providers_meta.get(pid, {}).get("default_model", "")

    def set_provider_model(self, pid: str, model: str):
        section = f"provider.{pid}"
        if not self._cfg.has_section(section):
            self._cfg.add_section(section)
        self._cfg[section]["model"] = model

    def get_provider_url(self, pid: str) -> str:
        section = f"provider.{pid}"
        if self._cfg.has_section(section):
            return self._cfg.get(section, "base_url",
                fallback=self._providers_meta.get(pid, {}).get("base_url", ""))
        return self._providers_meta.get(pid, {}).get("base_url", "")

    def set_provider_url(self, pid: str, url: str):
        section = f"provider.{pid}"
        if not self._cfg.has_section(section):
            self._cfg.add_section(section)
        self._cfg[section]["base_url"] = url

    def is_provider_enabled(self, pid: str) -> bool:
        section = f"provider.{pid}"
        if self._cfg.has_section(section):
            return self._cfg.getboolean(section, "enabled", fallback=True)
        return self._providers_meta.get(pid, {}).get("enabled", False)

    def set_provider_enabled(self, pid: str, enabled: bool):
        section = f"provider.{pid}"
        if not self._cfg.has_section(section):
            self._cfg.add_section(section)
        self._cfg[section]["enabled"] = str(enabled).lower()

    def get_provider_meta(self, pid: str) -> dict:
        return self._providers_meta.get(pid, {})

    def all_providers_meta(self) -> List[dict]:
        return self._meta["providers"]

    def tts_providers_meta(self) -> List[dict]:
        return self._meta.get("tts_providers", [])

    # ── STT 设置 ─────────────────────────────────────
    @property
    def stt_model(self) -> str:
        return self._cfg.get("stt", "model", fallback="base")

    @stt_model.setter
    def stt_model(self, v: str):
        if not self._cfg.has_section("stt"):
            self._cfg.add_section("stt")
        self._cfg["stt"]["model"] = v

    @property
    def stt_language(self) -> str:
        return self._cfg.get("stt", "language", fallback="zh")

    # ── TTS 设置 ─────────────────────────────────────
    @property
    def tts_voice(self) -> str:
        return self._cfg.get("tts", "voice", fallback="zh-CN-XiaoxiaoNeural")

    @tts_voice.setter
    def tts_voice(self, v: str):
        if not self._cfg.has_section("tts"):
            self._cfg.add_section("tts")
        self._cfg["tts"]["voice"] = v

    # ── 系统设置 ──────────────────────────────────────
    @property
    def autostart(self) -> bool:
        return self._cfg.getboolean("system", "autostart", fallback=False)

    @autostart.setter
    def autostart(self, v: bool):
        if not self._cfg.has_section("system"):
            self._cfg.add_section("system")
        self._cfg["system"]["autostart"] = str(v).lower()

    @property
    def minimize_to_tray(self) -> bool:
        return self._cfg.getboolean("system", "minimize_to_tray", fallback=True)

    @property
    def first_run(self) -> bool:
        return self._cfg.getboolean("system", "first_run", fallback=True)

    def mark_first_run_done(self):
        if not self._cfg.has_section("system"):
            self._cfg.add_section("system")
        self._cfg["system"]["first_run"] = "false"
        self.save()

    @property
    def http_port(self) -> int:
        return self._cfg.getint("system", "http_port", fallback=8766)

    @property
    def https_port(self) -> int:
        return self._cfg.getint("system", "https_port", fallback=8765)

    # ── 主题/语言 ─────────────────────────────────────
    @property
    def ui_theme(self) -> str:
        return self._cfg.get("ui", "theme", fallback="dark")

    @property
    def ui_language(self) -> str:
        return self._cfg.get("ui", "language", fallback="zh")

    # ── 快捷键 ─────────────────────────────────────
    @property
    def shortcuts_enabled(self) -> List[str]:
        raw = self._cfg.get("system", "shortcuts_enabled", fallback="settings,quit")
        return [s.strip() for s in raw.split(",") if s.strip()]
