#!/usr/bin/env python3
"""
十三香小龙虾 — 统一构建脚本

用法:
    python build.py                    # 构建全部（Tauri + 安装包）
    python build.py --tauri            # 仅编译 Tauri 桌面端
    python build.py --installer        # 仅编译安装包（需先构建 Tauri）
    python build.py --bump 3.6.0       # 升级版本号并构建全部
    python build.py --bump patch       # 自动递增 patch 版本（3.5.2 → 3.5.3）

输出目录: dist/
    dist/十三香小龙虾.exe                  — Tauri 桌面客户端（~14MB）
    dist/十三香小龙虾-v{版本}-Setup.exe    — 完整安装包（~240MB）
"""

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
VERSION_FILE = ROOT / "version.txt"

VERSION_TARGETS = {
    "version.txt": None,
    "installer.iss": r'(#define\s+AppVersion\s+")[^"]*(")',
    "src-tauri/Cargo.toml": r'(^version\s*=\s*")[^"]*(")',
    "src-tauri/tauri.conf.json": None,
}

ISCC = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
CARGO = "cargo"


def read_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def bump_version(current: str, spec: str) -> str:
    if spec in ("major", "minor", "patch"):
        parts = [int(x) for x in current.split(".")]
        while len(parts) < 3:
            parts.append(0)
        idx = {"major": 0, "minor": 1, "patch": 2}[spec]
        parts[idx] += 1
        for i in range(idx + 1, 3):
            parts[i] = 0
        return ".".join(str(p) for p in parts)
    if re.match(r"^\d+\.\d+\.\d+$", spec):
        return spec
    print(f"  ❌ 无效版本号: {spec}")
    sys.exit(1)


def sync_version(version: str):
    print(f"\n📌 同步版本号 → {version}")

    # version.txt
    (ROOT / "version.txt").write_text(version + "\n", encoding="utf-8")
    print(f"  ✅ version.txt")

    # installer.iss
    iss = ROOT / "installer.iss"
    text = iss.read_text(encoding="utf-8")
    text = re.sub(
        r'(#define\s+AppVersion\s+")[^"]*(")',
        rf"\g<1>{version}\2",
        text,
    )
    iss.write_text(text, encoding="utf-8")
    print(f"  ✅ installer.iss")

    # Cargo.toml
    cargo = ROOT / "src-tauri" / "Cargo.toml"
    text = cargo.read_text(encoding="utf-8")
    text = re.sub(
        r'(^version\s*=\s*")[^"]*(")',
        rf"\g<1>{version}\2",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    cargo.write_text(text, encoding="utf-8")
    print(f"  ✅ src-tauri/Cargo.toml")

    # tauri.conf.json
    conf = ROOT / "src-tauri" / "tauri.conf.json"
    data = json.loads(conf.read_text(encoding="utf-8"))
    data["version"] = version
    conf.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  ✅ src-tauri/tauri.conf.json")


def ensure_cargo():
    cargo_bin = Path.home() / ".cargo" / "bin"
    if cargo_bin.exists():
        os.environ["PATH"] = str(cargo_bin) + os.pathsep + os.environ.get("PATH", "")
    try:
        r = subprocess.run(["cargo", "--version"], capture_output=True, text=True)
        if r.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    print("  ❌ 未找到 Rust/Cargo，请先安装: https://rustup.rs")
    return False


def build_tauri(version: str) -> bool:
    print(f"\n🔨 编译 Tauri 桌面端 v{version}...")
    t0 = time.time()

    r = subprocess.run(
        ["cargo", "build", "--release"],
        cwd=ROOT / "src-tauri",
        capture_output=False,
    )
    if r.returncode != 0:
        print("  ❌ Tauri 编译失败")
        return False

    src = ROOT / "src-tauri" / "target" / "release" / "shisanxiang.exe"
    if not src.exists():
        print(f"  ❌ 编译产物未找到: {src}")
        return False

    DIST.mkdir(exist_ok=True)
    dst = DIST / "十三香小龙虾.exe"
    shutil.copy2(src, dst)

    elapsed = time.time() - t0
    size_mb = dst.stat().st_size / 1024 / 1024
    print(f"  ✅ Tauri 编译完成 ({elapsed:.0f}s, {size_mb:.1f} MB)")
    print(f"     → {dst}")
    return True


def build_installer(version: str) -> bool:
    print(f"\n📦 编译安装包 v{version}...")

    tauri_exe = DIST / "十三香小龙虾.exe"
    if not tauri_exe.exists():
        print(f"  ❌ Tauri exe 未找到: {tauri_exe}")
        print(f"     请先运行: python build.py --tauri")
        return False

    if not ISCC.exists():
        print(f"  ❌ Inno Setup 未找到: {ISCC}")
        return False

    t0 = time.time()
    r = subprocess.run(
        [str(ISCC), str(ROOT / "installer.iss")],
        capture_output=False,
    )
    if r.returncode != 0:
        print("  ❌ 安装包编译失败")
        return False

    setup = DIST / f"十三香小龙虾-v{version}-Setup.exe"
    if not setup.exists():
        print(f"  ⚠️ 安装包路径预期: {setup}")
        for f in DIST.glob("*.exe"):
            if "Setup" in f.name:
                setup = f
                break

    elapsed = time.time() - t0
    size_mb = setup.stat().st_size / 1024 / 1024
    print(f"  ✅ 安装包编译完成 ({elapsed:.0f}s, {size_mb:.1f} MB)")
    print(f"     → {setup}")
    return True


def print_summary(version: str):
    print(f"\n{'='*60}")
    print(f"  十三香小龙虾 v{version} 构建完成")
    print(f"{'='*60}")
    print(f"  输出目录: {DIST}")
    print()
    for f in sorted(DIST.glob("*.exe")):
        size = f.stat().st_size / 1024 / 1024
        label = "安装包" if "Setup" in f.name else "桌面端"
        print(f"  [{label}] {f.name} ({size:.1f} MB)")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="十三香小龙虾 统一构建脚本")
    parser.add_argument("--tauri", action="store_true", help="仅编译 Tauri 桌面端")
    parser.add_argument("--installer", action="store_true", help="仅编译安装包")
    parser.add_argument("--bump", metavar="VER", help="升级版本号 (3.6.0 / major / minor / patch)")
    args = parser.parse_args()

    build_all = not args.tauri and not args.installer

    version = read_version()
    print(f"🦞 十三香小龙虾 构建系统")
    print(f"   当前版本: {version}")

    if args.bump:
        version = bump_version(version, args.bump)
        sync_version(version)

    if not ensure_cargo():
        if build_all or args.tauri:
            sys.exit(1)

    ok = True
    if build_all or args.tauri:
        ok = build_tauri(version) and ok
    if build_all or args.installer:
        ok = build_installer(version) and ok

    if ok:
        print_summary(version)
    else:
        print("\n⚠️ 构建过程中有错误，请检查上方日志。")
        sys.exit(1)


if __name__ == "__main__":
    main()
