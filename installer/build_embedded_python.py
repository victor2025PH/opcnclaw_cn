# -*- coding: utf-8 -*-
"""
Download Python 3.11 Embeddable Package and configure it for OpenClaw.

Creates installer/embedded/python/ with a self-contained Python environment.
Run this once before compiling the Inno Setup installer.

Usage:
    python build_embedded_python.py
"""

import os
import sys
import zipfile
import urllib.request
import shutil
import subprocess

PYTHON_VERSION = "3.11.11"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EMBEDDED_DIR = os.path.join(BASE_DIR, "embedded")
PYTHON_DIR = os.path.join(EMBEDDED_DIR, "python")
PROJECT_ROOT = os.path.dirname(BASE_DIR)


def download(url, dest):
    if os.path.exists(dest):
        print(f"  Already exists: {dest}")
        return
    print(f"  Downloading: {url}")
    urllib.request.urlretrieve(url, dest)
    size_mb = os.path.getsize(dest) / 1024 / 1024
    print(f"  Saved: {dest} ({size_mb:.1f} MB)")


def main():
    os.makedirs(EMBEDDED_DIR, exist_ok=True)

    # Step 1: Download Python embeddable
    py_zip = os.path.join(EMBEDDED_DIR, f"python-{PYTHON_VERSION}-embed-amd64.zip")
    print("=== Step 1: Download Python Embeddable ===")
    download(PYTHON_URL, py_zip)

    # Step 2: Extract
    print("\n=== Step 2: Extract Python ===")
    if os.path.exists(PYTHON_DIR):
        shutil.rmtree(PYTHON_DIR)
    os.makedirs(PYTHON_DIR)
    with zipfile.ZipFile(py_zip) as zf:
        zf.extractall(PYTHON_DIR)
    print(f"  Extracted to: {PYTHON_DIR}")

    # Step 3: Enable pip by editing python311._pth
    print("\n=== Step 3: Enable pip (edit _pth file) ===")
    pth_files = [f for f in os.listdir(PYTHON_DIR) if f.endswith("._pth")]
    if pth_files:
        pth_path = os.path.join(PYTHON_DIR, pth_files[0])
        with open(pth_path, "r") as f:
            lines = f.readlines()
        with open(pth_path, "w") as f:
            for line in lines:
                if line.strip() == "#import site":
                    f.write("import site\n")
                else:
                    f.write(line)
            f.write(".\n")
            f.write("..\\..\\src\n")
        print(f"  Updated: {pth_path}")
    else:
        print("  Warning: no ._pth file found!")

    # Step 4: Install pip
    print("\n=== Step 4: Install pip ===")
    get_pip = os.path.join(EMBEDDED_DIR, "get-pip.py")
    download(GET_PIP_URL, get_pip)
    python_exe = os.path.join(PYTHON_DIR, "python.exe")
    subprocess.run([python_exe, get_pip, "--no-warn-script-location"], check=True)
    print("  pip installed")

    # Step 5: Configure pip mirror (China)
    print("\n=== Step 5: Configure pip mirror ===")
    subprocess.run([python_exe, "-m", "pip", "config", "set",
                    "global.index-url", "https://mirrors.aliyun.com/pypi/simple/"],
                   check=True)
    subprocess.run([python_exe, "-m", "pip", "config", "set",
                    "global.trusted-host", "mirrors.aliyun.com"],
                   check=True)
    print("  Mirror configured: mirrors.aliyun.com")

    # Step 6: Install core dependencies
    print("\n=== Step 6: Install core dependencies ===")
    req_file = os.path.join(PROJECT_ROOT, "requirements.txt")
    if os.path.exists(req_file):
        subprocess.run([python_exe, "-m", "pip", "install", "--no-cache-dir",
                        "-r", req_file], check=True)
        print("  Core dependencies installed")
    else:
        print(f"  Warning: {req_file} not found!")

    # Step 7: Download VC++ Redistributable
    print("\n=== Step 7: Download VC++ Redistributable ===")
    vcredist_path = os.path.join(EMBEDDED_DIR, "vcredist_x64.exe")
    download(VCREDIST_URL, vcredist_path)

    # Step 8: Create pythonw.exe (copy from python.exe for windowless mode)
    print("\n=== Step 8: Verify pythonw.exe ===")
    pythonw = os.path.join(PYTHON_DIR, "pythonw.exe")
    if os.path.exists(pythonw):
        print(f"  pythonw.exe exists: {pythonw}")
    else:
        print("  Warning: pythonw.exe not found in embeddable package!")

    # Summary
    total_size = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, filenames in os.walk(PYTHON_DIR)
        for f in filenames
    ) / 1024 / 1024
    print(f"\n{'='*50}")
    print(f"Build complete!")
    print(f"  Python: {PYTHON_DIR}")
    print(f"  Total size: {total_size:.0f} MB")
    print(f"  VCRedist: {vcredist_path}")
    print(f"\nNext: compile installer/setup.iss with Inno Setup")


if __name__ == "__main__":
    main()
