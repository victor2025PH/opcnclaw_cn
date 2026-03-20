"""
Pre-bundle pip dependencies into the embedded Python for USB/portable mode.

Usage:
    python installer/prebundle_deps.py

This installs requirements.txt + desktop control packages into the embedded
Python's site-packages so the USB installer doesn't need internet access.
"""
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
EMBEDDED_PYTHON = SCRIPT_DIR / "embedded" / "python" / "python.exe"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"

DESKTOP_PACKAGES = [
    "pyautogui", "mss", "rapidocr-onnxruntime", "pyperclip", "psutil"
]


def main():
    if not EMBEDDED_PYTHON.exists():
        print(f"ERROR: Embedded Python not found at {EMBEDDED_PYTHON}")
        print("Run build_embedded_python.py first.")
        sys.exit(1)

    python = str(EMBEDDED_PYTHON)

    print("=== Pre-bundling dependencies for USB/portable mode ===")
    print(f"Python: {python}")
    print(f"Requirements: {REQUIREMENTS}")
    print()

    print("[1/3] Configuring pip mirror...")
    subprocess.run([python, "-m", "pip", "config", "set",
                    "global.index-url", "https://mirrors.aliyun.com/pypi/simple/"],
                   check=False)
    subprocess.run([python, "-m", "pip", "config", "set",
                    "global.trusted-host", "mirrors.aliyun.com"],
                   check=False)

    print("\n[2/3] Installing core requirements...")
    result = subprocess.run(
        [python, "-m", "pip", "install", "--no-cache-dir",
         "--timeout", "120", "-r", str(REQUIREMENTS)],
        check=False
    )
    if result.returncode != 0:
        print("WARNING: Some core deps may have failed")

    print("\n[3/3] Installing desktop control packages...")
    result = subprocess.run(
        [python, "-m", "pip", "install", "--no-cache-dir",
         "--timeout", "120"] + DESKTOP_PACKAGES,
        check=False
    )
    if result.returncode != 0:
        print("WARNING: Some desktop deps may have failed")

    print("\n[3/3] Installing silero-vad...")
    subprocess.run(
        [python, "-m", "pip", "install", "--no-cache-dir",
         "--timeout", "120", "silero-vad"],
        check=False
    )

    site_packages = SCRIPT_DIR / "embedded" / "python" / "Lib" / "site-packages"
    pkg_count = sum(1 for p in site_packages.iterdir() if p.is_dir()) if site_packages.exists() else 0
    size_mb = sum(f.stat().st_size for f in site_packages.rglob("*") if f.is_file()) / (1024 * 1024) if site_packages.exists() else 0

    print(f"\n=== Done! {pkg_count} packages, {size_mb:.0f} MB in site-packages ===")
    print("You can now compile the installer — USB mode will work offline.")


if __name__ == "__main__":
    main()
