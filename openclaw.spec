# -*- mode: python ; coding: utf-8 -*-
"""
OpenClaw PyInstaller 打包规格文件

构建命令：
  pyinstaller openclaw.spec --clean

注意事项：
  1. 首选使用 build_portable.py 的"Embedded Python"方案
  2. PyInstaller 方案适合"必须是单文件/文件夹"的场景
  3. AI 模型文件(model.bin)不打包进去，运行时下载

深度优化点：
  - 排除无用模块减小体积（numpy 测试、GUI 测试等）
  - 使用 --collect-data 而非 --add-data 避免路径问题
  - 用 UPX 压缩（如果安装了 UPX）
  - 关键 DLL（VC++ 运行库）自动收集
"""

import sys
from pathlib import Path

ROOT = Path(SPEC).parent

# ── 需要手动收集的数据文件 ──────────────────────────────
datas = [
    # 前端资源
    (str(ROOT / "src" / "client"), "src/client"),
    # 技能包
    (str(ROOT / "skills"), "skills"),
    # AI 路由器配置
    (str(ROOT / "src" / "router" / "providers.json"), "src/router"),
    # 环境变量模板（不打包真实的.env）
    (str(ROOT / ".env.example") if (ROOT / ".env.example").exists() else
     str(ROOT / ".env"), ".env.example"),
]

# ── 需要手动包含的隐式导入 ─────────────────────────────
hiddenimports = [
    # FastAPI 相关
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # pydantic
    "pydantic.deprecated.class_validators",
    "pydantic.v1",
    # edge-tts
    "edge_tts",
    "edge_tts.communicate",
    # 技能引擎
    "skills._engine",
    "skills._engine.registry",
    "skills._engine.matcher",
    "skills._engine.executor",
    # jieba
    "jieba",
    "jieba.analyse",
    # pystray
    "pystray",
    "pystray._win32",
    # customtkinter
    "customtkinter",
    "darkdetect",
]

# ── 排除的无用模块（减小体积）─────────────────────────
excludes = [
    # 测试框架
    "pytest", "unittest", "doctest",
    # 不需要的GUI框架（保留customtkinter和tkinter）
    "PyQt5", "PyQt6", "wx", "gi", "gtk",
    # Jupyter 相关
    "IPython", "jupyter", "notebook",
    # 不需要的ML包（保留torch/faster-whisper）
    "tensorflow", "keras", "sklearn", "cv2",
    # 编译工具
    "cython", "cffi._cffi_backend",
    # 调试工具
    "pdb", "profile", "cProfile",
    # 其他不需要的
    "email.mime", "xml.etree", "xmlrpc",
    "distutils", "setuptools", "pkg_resources",
]

block_cipher = None

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── 过滤掉不必要的二进制文件 ─────────────────────────
def exclude_binaries(binaries):
    """移除不必要的 DLL，减小体积"""
    exclude_patterns = [
        "Qt5",  # Qt 框架（我们用 tkinter）
        "libopenblas",  # 如果不需要 BLAS 加速
        "_test",  # 测试相关
    ]
    filtered = []
    for name, src, kind in binaries:
        should_exclude = any(pat.lower() in name.lower() for pat in exclude_patterns)
        if not should_exclude:
            filtered.append((name, src, kind))
    return filtered

a.binaries = exclude_binaries(a.binaries)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── 文件夹模式（推荐）─────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenClaw",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,        # 使用 UPX 压缩（需要安装 UPX）
    console=False,   # 不显示黑色命令行窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico") if (ROOT / "assets" / "icon.ico").exists() else None,
    version=str(ROOT / "assets" / "version.txt") if (ROOT / "assets" / "version.txt").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        "vcruntime140.dll",
        "python*.dll",
        "torch*.dll",
    ],
    name="OpenClaw",
)
