"""
OpenClaw 便携式打包工具

策略(深度思考后的最优方案)：
═══════════════════════════════════════════════════════════

【方案选择：为什么用"Embedded Python"而不是单文件 PyInstaller？】

1. PyInstaller 单文件(.exe) 的问题：
   - 每次启动需要解压到 %TEMP%，冷启动 30-60 秒
   - torch/faster-whisper 依赖解压会触发杀毒软件误报
   - 文件总大小 2-3GB，对用户不友好
   - 模型文件(.bin)无法打包进去，还需要额外下载

2. Embedded Python 方案的优势：
   - 启动速度快(直接运行Python，无解压)
   - 杀毒软件误报率低(标准 .py 文件)
   - 文件分离清晰(程序/模型/配置互不干扰)
   - 可以做增量更新(只更新代码，不重新下载依赖)
   - 总大小 400-800MB(不含AI模型)，压缩后约 200-400MB

3. 最终打包结构：
   OpenClaw-v2.0/
   ├── OpenClaw.exe           ← 3KB 小启动器(Go/VBScript生成)
   ├── openclaw.bat           ← 命令行启动(调试用)
   ├── python/                ← Embedded Python 3.11 (~30MB)
   │   ├── python.exe
   │   ├── pythonw.exe
   │   └── Lib/site-packages/ ← 所有pip包
   ├── app/                   ← OpenClaw 程序文件
   │   ├── launcher.py
   │   ├── src/
   │   ├── skills/
   │   └── config.ini
   ├── models/                ← AI 模型(首次下载后缓存)
   │   ├── whisper/           ← faster-whisper 模型
   │   └── silero/            ← VAD 模型
   └── _install/              ← 安装辅助文件(安装后可删)

═══════════════════════════════════════════════════════════
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

# Windows GBK 控制台兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent

# ── 配置 ──────────────────────────────────────────────────
PYTHON_VERSION = "3.11.9"   # 推荐 3.11(比3.13更稳定，torch支持更好)
PYTHON_EMBED_URL = f"https://mirrors.huaweicloud.com/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_EMBED_URL_ALT = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
GET_PIP_URL_ALT = "https://mirrors.aliyun.com/pypi/packages/get-pip.py"
OUTPUT_DIR = ROOT / "dist" / "OpenClaw-v2.0"
INSTALLER_DIR = ROOT / "dist" / "installer"

# pip 镜像(国内加速)
PIP_MIRROR = "https://mirrors.aliyun.com/pypi/simple/"

# 需要安装的包(按需分组)
PACKAGES_CORE = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "websockets>=12.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "python-multipart>=0.0.6",
    "httpx>=0.26.0",
    "openai>=1.6.0",
    "python-dotenv>=1.0.0",
    "loguru>=0.7.2",
    "pystray>=0.19.5",
    "customtkinter>=5.2.0",
    "pillow>=10.0.0",
    "jieba>=0.42.1",
    "qrcode[pil]>=7.4.2",
    "numpy>=1.26.0",
    "soundfile>=0.12.1",
    "edge-tts>=6.1.0",
    "pyperclip>=1.8.0",
]

PACKAGES_AI = [
    "torch>=2.1.0",        # ~500MB，最大的包
    "faster-whisper>=1.0.0",
    "silero-vad>=6.0.0",
    "torchaudio>=2.1.0",
]

PACKAGES_OPTIONAL = [
    "rapidocr-onnxruntime>=1.2.0",  # OCR
]


def download_file(url: str, dest: Path, alt_url: str = None, desc: str = "") -> bool:
    """下载文件，带重试和镜像切换"""
    urls = [url]
    if alt_url:
        urls.append(alt_url)

    for attempt_url in urls:
        try:
            print(f"  下载 {desc or dest.name}...")
            print(f"  地址: {attempt_url[:80]}...")
            dest.parent.mkdir(parents=True, exist_ok=True)

            def _progress(count, block_size, total):
                if total > 0:
                    pct = min(100, count * block_size * 100 // total)
                    mb = count * block_size // (1024 * 1024)
                    total_mb = total // (1024 * 1024)
                    print(f"\r  进度: {pct}% ({mb}/{total_mb}MB)", end="", flush=True)

            urllib.request.urlretrieve(attempt_url, dest, _progress)
            print()
            return True
        except Exception as e:
            print(f"\n  ⚠️ 下载失败: {e}，尝试备用地址...")
    return False


def setup_embedded_python(target_dir: Path) -> bool:
    """下载并配置 Embedded Python"""
    py_dir = target_dir / "python"
    py_exe = py_dir / "python.exe"

    if py_exe.exists():
        print("  ✅ Python 已存在，跳过下载")
        return True

    zip_path = target_dir / "_temp" / "python-embed.zip"

    if not download_file(
        PYTHON_EMBED_URL, zip_path,
        alt_url=PYTHON_EMBED_URL_ALT,
        desc=f"Python {PYTHON_VERSION} 嵌入包"
    ):
        print("  ❌ Python 下载失败！")
        return False

    print("  正在解压 Python...")
    py_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(py_dir)

    # 启用 site-packages(embedded Python 默认禁用)
    pth_file = py_dir / f"python{PYTHON_VERSION.replace('.', '')[:2]}.pth"
    pth_files = list(py_dir.glob("python3*.._pth"))
    if not pth_files:
        pth_files = list(py_dir.glob("python*._pth"))

    for pth in pth_files:
        content = pth.read_text()
        if "#import site" in content:
            pth.write_text(content.replace("#import site", "import site"))
            print(f"  ✅ 已启用 site-packages: {pth.name}")
            break

    # 安装 pip
    get_pip_path = target_dir / "_temp" / "get-pip.py"
    if download_file(GET_PIP_URL, get_pip_path, alt_url=GET_PIP_URL_ALT, desc="pip 安装器"):
        subprocess.run([str(py_exe), str(get_pip_path), "--quiet"], check=False)
        print("  ✅ pip 安装完成")

    return py_exe.exists()


def install_packages(py_dir: Path, packages: list, label: str = ""):
    """用嵌入式 Python 的 pip 安装包"""
    pip_exe = py_dir / "Scripts" / "pip.exe"
    py_exe = py_dir / "python.exe"

    if not pip_exe.exists():
        pip_exe = py_exe  # 使用 python -m pip

    print(f"\n  安装 {label} ({len(packages)} 个包)...")
    cmd = [
        str(py_exe), "-m", "pip", "install",
        "-i", PIP_MIRROR,
        "--trusted-host", "mirrors.aliyun.com",
        "--quiet", "--progress-bar", "off",
    ] + packages

    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def copy_app_files(source_dir: Path, target_dir: Path):
    """复制应用文件(排除不必要文件)"""
    app_dir = target_dir / "app"

    EXCLUDE = {
        ".git", ".github", "__pycache__", "*.pyc",
        "dist", "build", "*.egg-info",
        "node_modules", ".venv", "venv",
        "tests", "test_*", "*.test.py",
        ".env", "*.log",  # 不打包密钥和日志
    }

    def should_copy(p: Path) -> bool:
        for excl in EXCLUDE:
            if excl.startswith("*"):
                if p.name.endswith(excl[1:]):
                    return False
            elif p.name == excl:
                return False
        return True

    print("  复制应用文件...")
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)

    items = ["src", "skills", "assets", "launcher.py",
             "requirements.txt", "README.md"]
    for item in items:
        src = source_dir / item
        if src.exists():
            if src.is_dir():
                shutil.copytree(src, app_dir / item,
                                ignore=lambda d, f: [x for x in f if not should_copy(Path(d)/x)])
            else:
                shutil.copy2(src, app_dir / item)

    # 创建空 data 和 logs 目录
    (app_dir / "data").mkdir(exist_ok=True)
    (app_dir / "logs").mkdir(exist_ok=True)
    (app_dir / "models").mkdir(exist_ok=True)
    (app_dir / "ssl").mkdir(exist_ok=True)

    print(f"  ✅ 应用文件复制完成")


def create_launcher_exe(target_dir: Path):
    """
    生成 OpenClaw.exe 启动器
    
    优化：用 VBScript 生成一个无黑框 .vbs，再包装成 .bat 引导
    最终用户看到的是一个真实的 .exe(需要 go 或 nsis)
    
    暂时方案：创建无黑窗的 .vbs 启动器 + .lnk 快捷方式
    """
    # 无窗口 VBS 启动器
    vbs_content = r'''
Set oWS = WScript.CreateObject("WScript.Shell")
sDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
sPy = sDir & "python\pythonw.exe"
sScript = sDir & "app\launcher.py"
oWS.CurrentDirectory = sDir & "app"
oWS.Run """" & sPy & """ """ & sScript & """, 0, False
'''
    vbs_path = target_dir / "OpenClaw.vbs"
    vbs_path.write_text(vbs_content.strip(), encoding="utf-8")

    # 命令行版本(调试用)
    bat_content = """@echo off
chcp 65001 >nul
cd /d "%~dp0app"
"%~dp0python\\python.exe" launcher.py %*
if errorlevel 1 pause
"""
    (target_dir / "openclaw_debug.bat").write_text(bat_content, encoding="utf-8")

    # 生成桌面快捷方式脚本
    shortcut_vbs = f"""
Set oWS = WScript.CreateObject("WScript.Shell")
sDesktop = oWS.SpecialFolders("Desktop")
Set oLink = oWS.CreateShortcut(sDesktop & "\\OpenClaw AI助手.lnk")
oLink.TargetPath = "{target_dir}\\OpenClaw.vbs"
oLink.WorkingDirectory = "{target_dir}\\app"
oLink.Description = "OpenClaw AI 语音助手"
oLink.WindowStyle = 7
oLink.Save
MsgBox "桌面快捷方式已创建！", 64, "OpenClaw"
"""
    (target_dir / "创建桌面快捷方式.vbs").write_text(shortcut_vbs.strip(), encoding="utf-8")

    print("  ✅ 启动器文件已生成")


def create_first_run_config(target_dir: Path):
    """创建首次运行配置(告知使用嵌入式Python路径)"""
    config_content = """[system]
# 便携版配置
portable_mode = true
python_path = .\\python\\python.exe
app_path = .\\app
models_path = .\\models
first_run = true

[router]
mode = cost_saving
auto_switch = true

[stt]
model = base
language = zh

[tts]
voice = zh-CN-XiaoxiaoNeural
"""
    (target_dir / "app" / "config.ini").write_text(config_content, encoding="utf-8")

    # 模型下载清单
    models_manifest = {
        "whisper": {
            "base": {
                "size_mb": 145,
                "description": "Whisper Base 模型(推荐，平衡速度和准确率)",
                "url": "https://huggingface.co/Systran/faster-whisper-base/resolve/main/",
                "files": ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"],
            },
            "small": {
                "size_mb": 461,
                "description": "Whisper Small 模型(更准确)",
                "url": "https://huggingface.co/Systran/faster-whisper-small/resolve/main/",
                "files": ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"],
            },
            "medium": {
                "size_mb": 1468,
                "description": "Whisper Medium 模型(最准确，较慢)",
                "url": "https://huggingface.co/Systran/faster-whisper-medium/resolve/main/",
                "files": ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"],
            },
        },
        "silero_vad": {
            "v6": {
                "size_mb": 2,
                "description": "Silero VAD 语音检测模型",
                "auto_install": True,
            }
        }
    }
    models_dir = target_dir / "app" / "models"
    models_dir.mkdir(exist_ok=True)
    with open(models_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(models_manifest, f, ensure_ascii=False, indent=2)

    print("  ✅ 首次运行配置已创建")


def create_readme(target_dir: Path):
    """生成使用说明"""
    readme = """# OpenClaw AI 语音助手 v2.0
> 全双工本地部署 AI 语音助手

## 🚀 启动方式
- **双击** `OpenClaw.vbs`(无黑窗，推荐)
- 或 双击 `openclaw_debug.bat`(有日志窗口，调试用)

## 📋 首次使用
1. 运行 OpenClaw，等待服务启动(约 10-30 秒)
2. 浏览器会自动打开 http://localhost:8766/app
3. 点击设置图标 → 填写 AI 平台 API Key
4. 推荐免费平台：**智谱 AI**(无限免费)

## 🔑 推荐 AI 平台(免费)
| 平台 | 免费额度 | 注册 |
|------|---------|------|
| 智谱 GLM-4-Flash | 永久免费 | open.bigmodel.cn |
| 硅基流动 | 永久免费 | cloud.siliconflow.cn |
| DeepSeek | 注册送500万Token | platform.deepseek.com |

## 🔧 常见问题
**Q: 启动后没有声音**
A: 检查浏览器是否允许麦克风权限(地址栏左侧锁形图标)

**Q: 识别不准确**
A: 打开设置 → 语音设置 → 将模型改为 small 或 medium

**Q: AI 没有响应**
A: 检查是否填写了 API Key(设置 → AI 平台)

## 📞 技术支持
- 日志文件：`app/logs/openclaw.log`
- 命令行调试：双击 `openclaw_debug.bat`
"""
    (target_dir / "使用说明.txt").write_text(readme, encoding="utf-8")
    (target_dir / "README.md").write_text(readme, encoding="utf-8")
    print("  ✅ 使用说明已生成")


def build_portable(include_ai_packages: bool = True, output_dir: Path = None):
    """主打包流程"""
    target = output_dir or OUTPUT_DIR
    target.mkdir(parents=True, exist_ok=True)
    temp_dir = target / "_temp"
    temp_dir.mkdir(exist_ok=True)

    print(f"""
╔══════════════════════════════════════════╗
║  OpenClaw 便携包构建工具                 ║
║  输出目录: {str(target)[:30]}...
╚══════════════════════════════════════════╝
""")

    # Step 1: 嵌入式 Python
    print("[1/6] 配置嵌入式 Python...")
    py_dir = target / "python"
    if not setup_embedded_python(target):
        print("❌ 无法配置 Python，请检查网络")
        return False

    # Step 2: 安装核心包
    print("\n[2/6] 安装核心依赖...")
    if not install_packages(py_dir, PACKAGES_CORE, "核心包"):
        print("  ⚠️ 部分核心包安装失败，继续...")

    # Step 3: 安装 AI 包(可选，因为很大)
    if include_ai_packages:
        print("\n[3/6] 安装 AI 相关包(torch 约 500MB，请耐心等待)...")
        if not install_packages(py_dir, PACKAGES_AI, "AI包"):
            print("  ⚠️ AI 包安装失败，将在首次运行时安装")
    else:
        print("\n[3/6] 跳过 AI 包(将在首次运行时下载)")

    # Step 4: 复制应用文件
    print("\n[4/6] 复制应用文件...")
    copy_app_files(ROOT, target)

    # Step 5: 创建启动器和配置
    print("\n[5/6] 创建启动器和配置...")
    create_launcher_exe(target)
    create_first_run_config(target)
    create_readme(target)

    # Step 6: 清理临时文件
    print("\n[6/6] 清理临时文件...")
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    # 计算目录大小
    total_size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    size_mb = total_size // (1024 * 1024)

    print(f"""
╔══════════════════════════════════════════╗
║  ✅ 便携包构建完成！                     ║
║  输出：{str(target)[:36]}...
║  大小：约 {size_mb} MB                  ║
║  启动：双击 OpenClaw.vbs               ║
╚══════════════════════════════════════════╝
""")
    return True


def build_pyinstaller(mode: str = "folder"):
    """
    PyInstaller 打包(作为备用方案)
    
    mode:
    - "folder"  → 文件夹模式(推荐，快速启动)
    - "onefile" → 单文件模式(慢，但只有1个exe)
    """
    spec_file = ROOT / "openclaw.spec"
    if not spec_file.exists():
        print("❌ openclaw.spec 不存在，请先生成")
        return False

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        str(spec_file),
    ]
    if mode == "onefile":
        cmd.extend(["--onefile"])
    else:
        cmd.extend(["--onedir"])

    print("运行 PyInstaller...")
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenClaw 打包工具")
    parser.add_argument("--mode", choices=["portable", "pyinstaller"], default="portable",
                        help="打包模式：portable=便携包(推荐), pyinstaller=单文件exe")
    parser.add_argument("--no-ai", action="store_true",
                        help="不预装AI包(在首次运行时下载，减小安装包体积)")
    parser.add_argument("--output", type=Path, default=None,
                        help="输出目录")
    args = parser.parse_args()

    if args.mode == "portable":
        build_portable(
            include_ai_packages=not args.no_ai,
            output_dir=args.output,
        )
    else:
        build_pyinstaller()
