"""
环境检测与自动修复模块

在程序启动时检测运行环境，
自动安装缺失的依赖，引导用户解决系统层问题。

检测项：
  ① Python 版本
  ② VC++ 运行库（torch 需要）
  ③ 麦克风权限（Windows 隐私设置）
  ④ 防火墙（端口 8765/8766）
  ⑤ AI 模型文件
  ⑥ API Key 配置
  ⑦ 磁盘空间
  ⑧ 内存（torch 需要 2GB+）
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger


class CheckResult:
    def __init__(self, name: str, ok: bool, message: str,
                 fix: Optional[str] = None, critical: bool = False):
        self.name = name
        self.ok = ok
        self.message = message
        self.fix = fix                  # 自动修复命令（如果支持）
        self.critical = critical        # 是否阻止程序运行


class EnvironmentChecker:
    """系统环境检测器"""

    def run_all(self) -> List[CheckResult]:
        checks = [
            self.check_python_version(),
            self.check_disk_space(),
            self.check_memory(),
            self.check_vcredist(),
            self.check_mic_permission(),
            self.check_ports(),
            self.check_api_keys(),
            self.check_models(),
        ]
        return checks

    def check_python_version(self) -> CheckResult:
        ver = sys.version_info
        if ver >= (3, 10):
            return CheckResult("Python版本", True,
                               f"Python {ver.major}.{ver.minor}.{ver.micro} ✓")
        return CheckResult("Python版本", False,
                           f"Python {ver.major}.{ver.minor} 版本过低，需要 3.10+",
                           critical=True,
                           fix="https://www.python.org/downloads/")

    def check_disk_space(self) -> CheckResult:
        """检查磁盘空间"""
        try:
            usage = shutil.disk_usage(".")
            free_gb = usage.free / (1024 ** 3)
            if free_gb >= 3.0:
                return CheckResult("磁盘空间", True,
                                   f"可用空间 {free_gb:.1f} GB ✓")
            elif free_gb >= 1.0:
                return CheckResult("磁盘空间", True,
                                   f"可用空间 {free_gb:.1f} GB（建议 3GB+，AI 模型需要空间）")
            else:
                return CheckResult("磁盘空间", False,
                                   f"磁盘空间严重不足！仅剩 {free_gb:.1f} GB，无法下载 AI 模型",
                                   critical=True)
        except Exception as e:
            return CheckResult("磁盘空间", True, f"检查失败: {e}（忽略）")

    def check_memory(self) -> CheckResult:
        """检查内存"""
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            total_gb = mem.ullTotalPhys / (1024 ** 3)
            avail_gb = mem.ullAvailPhys / (1024 ** 3)

            if total_gb >= 8:
                return CheckResult("系统内存", True,
                                   f"内存 {total_gb:.0f}GB，可用 {avail_gb:.1f}GB ✓")
            elif total_gb >= 4:
                return CheckResult("系统内存", True,
                                   f"内存 {total_gb:.0f}GB（medium 模型较慢，建议用 base 模型）")
            else:
                return CheckResult("系统内存", False,
                                   f"内存仅 {total_gb:.0f}GB，可能影响 AI 模型运行。建议使用 tiny 模型")
        except Exception:
            return CheckResult("系统内存", True, "内存检查失败（忽略）")

    def check_vcredist(self) -> CheckResult:
        """检查 VC++ 运行库（torch 需要 MSVC 2015-2022）"""
        if sys.platform != "win32":
            return CheckResult("VC++运行库", True, "非 Windows 系统，跳过")
        try:
            import winreg
            keys_to_check = [
                r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                r"SOFTWARE\Microsoft\VC141.CRT",
            ]
            for key_path in keys_to_check:
                try:
                    winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                    return CheckResult("VC++运行库", True, "Visual C++ 运行库已安装 ✓")
                except FileNotFoundError:
                    continue

            return CheckResult(
                "VC++运行库", False,
                "未检测到 Visual C++ 运行库，torch 可能无法运行",
                fix="download_vcredist",
                critical=False,  # 不阻止启动，让用户决定
            )
        except Exception:
            return CheckResult("VC++运行库", True, "检查失败（忽略）")

    def check_mic_permission(self) -> CheckResult:
        """检查麦克风权限（Windows 10/11 隐私设置）"""
        if sys.platform != "win32":
            return CheckResult("麦克风权限", True, "非 Windows，跳过")
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone",
            )
            value, _ = winreg.QueryValueEx(key, "Value")
            if value == "Allow":
                return CheckResult("麦克风权限", True, "麦克风权限已开启 ✓")
            else:
                return CheckResult(
                    "麦克风权限", False,
                    "麦克风权限被禁止！语音功能无法使用",
                    fix="open_mic_settings",
                )
        except Exception:
            # 可能是 Win10 旧版本，跳过
            return CheckResult("麦克风权限", True, "无法检测麦克风权限（请手动确认）")

    def check_ports(self) -> CheckResult:
        """检查端口 8765/8766 是否可用"""
        import socket
        occupied = []
        for port in [8765, 8766]:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                except OSError:
                    occupied.append(port)

        if not occupied:
            return CheckResult("端口占用", True, "端口 8765/8766 可用 ✓")

        return CheckResult(
            "端口占用", False,
            f"端口 {', '.join(map(str, occupied))} 已被占用，可能是上次程序未退出",
            fix="kill_ports",
        )

    def check_api_keys(self) -> CheckResult:
        """检查是否配置了 AI API Key"""
        try:
            from src.router.config import RouterConfig
            cfg = RouterConfig()
            has_any = any(
                cfg.get_provider_key(p["id"])
                for p in cfg.all_providers_meta()
            )
            if has_any:
                active = cfg.provider_order[0] if cfg.provider_order else "unknown"
                return CheckResult("AI平台配置", True, f"已配置 AI Key ✓")
            else:
                return CheckResult(
                    "AI平台配置", False,
                    "未配置任何 AI 平台 Key，对话功能不可用",
                    fix="open_settings",
                )
        except Exception as e:
            return CheckResult("AI平台配置", True, f"检查失败（忽略）: {e}")

    def check_models(self) -> CheckResult:
        """检查 Whisper 模型是否已下载"""
        try:
            from src.server.model_manager import get_model_manager
            mgr = get_model_manager()
            # 检查 base 模型
            if mgr.get_model_path("whisper-base"):
                return CheckResult("STT模型", True, "Whisper Base 模型已下载 ✓")
            else:
                return CheckResult(
                    "STT模型", False,
                    "Whisper 语音识别模型未下载，首次使用会自动下载（约145MB）",
                    fix="download_model",
                )
        except Exception:
            return CheckResult("STT模型", True, "模型检查失败（忽略）")

    # ──────────────────────────────────────────────────────
    # 自动修复函数
    # ──────────────────────────────────────────────────────

    def fix(self, result: CheckResult) -> Tuple[bool, str]:
        """执行自动修复"""
        if result.fix == "open_mic_settings":
            return self._open_mic_settings()
        elif result.fix == "kill_ports":
            return self._kill_ports()
        elif result.fix == "download_vcredist":
            return self._download_vcredist()
        elif result.fix == "open_settings":
            return True, "请打开托盘 → 设置 → AI 平台配置"
        elif result.fix == "download_model":
            return True, "首次语音识别时会自动下载模型"
        return False, "没有自动修复方案"

    def _open_mic_settings(self) -> Tuple[bool, str]:
        """打开 Windows 麦克风隐私设置"""
        try:
            subprocess.Popen(
                ["ms-settings:privacy-microphone"],
                shell=True,
            )
            return True, "已打开麦克风隐私设置，请开启'允许应用访问麦克风'"
        except Exception as e:
            return False, f"无法打开设置: {e}"

    def _kill_ports(self) -> Tuple[bool, str]:
        """释放被占用的端口"""
        killed = []
        for port in [8765, 8766]:
            try:
                result = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True, text=True,
                )
                for line in result.stdout.splitlines():
                    if f":{port}" in line and "LISTENING" in line:
                        pid = line.split()[-1]
                        subprocess.run(
                            ["taskkill", "/PID", pid, "/F"],
                            capture_output=True,
                        )
                        killed.append(f"PID {pid}（端口{port}）")
            except Exception:
                pass
        if killed:
            return True, f"已终止: {', '.join(killed)}"
        return False, "端口清理失败，请手动重启电脑"

    def _download_vcredist(self) -> Tuple[bool, str]:
        """引导下载 VC++ 运行库"""
        import webbrowser
        url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
        webbrowser.open(url)
        return True, "已打开 VC++ 运行库下载页，安装后重启 OpenClaw"


def run_checks_and_fix() -> Dict:
    """
    运行所有检查，自动修复可修复的问题。
    返回检查报告（供首次运行向导显示）。
    """
    checker = EnvironmentChecker()
    results = checker.run_all()

    report = {
        "all_ok": True,
        "critical_issues": [],
        "warnings": [],
        "fixed": [],
    }

    for r in results:
        if r.ok:
            continue
        report["all_ok"] = False
        if r.critical:
            report["critical_issues"].append(r.message)
            logger.error(f"❌ {r.name}: {r.message}")
        else:
            # 尝试自动修复
            if r.fix and r.fix in ("kill_ports",):
                success, msg = checker.fix(r)
                if success:
                    report["fixed"].append(f"{r.name}: {msg}")
                    logger.info(f"🔧 自动修复: {msg}")
                    continue
            report["warnings"].append({
                "name": r.name,
                "message": r.message,
                "fix": r.fix,
            })
            logger.warning(f"⚠️ {r.name}: {r.message}")

    return report


def check_and_log():
    """启动时快速检查（不阻塞启动）"""
    try:
        report = run_checks_and_fix()
        if report["all_ok"]:
            logger.info("✅ 环境检查通过")
        else:
            if report["critical_issues"]:
                for issue in report["critical_issues"]:
                    logger.error(f"❌ 致命问题: {issue}")
            if report["warnings"]:
                logger.warning(f"⚠️ {len(report['warnings'])} 个警告，程序仍可运行")
            if report["fixed"]:
                logger.info(f"🔧 已自动修复: {len(report['fixed'])} 个问题")
        return report
    except Exception as e:
        logger.debug(f"环境检查异常（忽略）: {e}")
        return {"all_ok": True}
