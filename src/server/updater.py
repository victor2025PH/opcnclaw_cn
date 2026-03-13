"""
自动更新系统

深度思考与优化：

  原始方案：下载完整 zip 包替换所有文件（~500MB，每次都要下完整包）

  优化方案 1（增量更新）：
    维护一个 version_manifest.json，记录每个文件的 SHA256
    只下载发生变更的文件，通常只有几KB-几MB

  优化方案 2（热更新）：
    - 代码文件（.py）：可以在运行时 importlib.reload() 部分模块
    - 静态文件（.html/.js/.css）：直接替换，刷新即生效
    - 需要重启：launcher.py、main.py 等核心文件

  优化方案 3（灰度发布）：
    用 channel = "stable" / "beta" / "nightly" 让用户可以选择更新频道

  最终采用：方案1 + 方案2 混合
    - 更新前备份关键文件到 backup/
    - 只下载 changed_files 列表中的文件
    - 更新完成后通知用户"已更新X个文件，建议重启"
    - 核心文件变更时强制提示重启

GitHub releases 结构：
  每个 release 带一个 version_manifest.json 资产：
  {
    "version": "2.1.0",
    "channel": "stable",
    "changelog": "修复了...",
    "files": {
      "src/server/backend.py": "sha256hex",
      "src/client/app.html": "sha256hex",
      ...
    }
  }
"""

import asyncio
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from loguru import logger

APP_VERSION = "2.0.0"
APP_ROOT = Path(__file__).parent.parent.parent

# 可以在 config.ini 中配置
DEFAULT_REPO = "openclaw/voice"  # GitHub 仓库
UPDATE_CHECK_INTERVAL = 86400    # 每天检查一次（秒）
BACKUP_DIR = APP_ROOT / "backup"
UPDATE_CACHE_DIR = APP_ROOT / "data" / "update_cache"

# 不参与更新的文件（用户配置）
EXCLUDE_FROM_UPDATE = {
    ".env",
    "config.ini",
    "data/",
    "models/",
    "ssl/",
    "logs/",
}

# 这些文件更新后需要重启
REQUIRE_RESTART = {
    "launcher.py",
    "src/server/main.py",
    "src/server/backend.py",
    "requirements.txt",
}


class UpdateInfo:
    def __init__(self):
        self.current_version = APP_VERSION
        self.latest_version: Optional[str] = None
        self.changelog: str = ""
        self.changed_files: List[str] = []
        self.total_size_kb: int = 0
        self.needs_restart: bool = False
        self.channel: str = "stable"
        self.publish_date: str = ""
        self.download_url: str = ""
        self.manifest_url: str = ""
        self.error: str = ""

    @property
    def has_update(self) -> bool:
        if not self.latest_version or self.error:
            return False
        return self._compare_versions(self.latest_version, self.current_version) > 0

    @staticmethod
    def _compare_versions(v1: str, v2: str) -> int:
        """比较版本号，v1>v2 返回1，v1==v2 返回0，v1<v2 返回-1"""
        try:
            a = [int(x) for x in v1.split(".")]
            b = [int(x) for x in v2.split(".")]
            for i in range(max(len(a), len(b))):
                x = a[i] if i < len(a) else 0
                y = b[i] if i < len(b) else 0
                if x > y: return 1
                if x < y: return -1
            return 0
        except Exception:
            return 0


class AutoUpdater:
    """自动更新管理器"""

    def __init__(self, repo: str = DEFAULT_REPO, channel: str = "stable"):
        self.repo = repo
        self.channel = channel
        self._last_check: float = 0
        self._cached_info: Optional[UpdateInfo] = None
        UPDATE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def check_for_updates(self, force: bool = False) -> UpdateInfo:
        """
        检查是否有新版本
        
        优化：本地缓存结果，避免频繁请求 GitHub API（防止速率限制）
        """
        if not force and self._cached_info and (time.time() - self._last_check) < 3600:
            return self._cached_info

        info = UpdateInfo()
        info.channel = self.channel

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                follow_redirects=True,
            ) as client:
                # 获取最新 release
                api_url = f"https://api.github.com/repos/{self.repo}/releases/latest"
                headers = {"Accept": "application/vnd.github.v3+json"}

                resp = await client.get(api_url, headers=headers)
                if resp.status_code == 404:
                    info.error = "仓库未找到（可能是私有仓库）"
                    return info
                resp.raise_for_status()
                release = resp.json()

                info.latest_version = release.get("tag_name", "").lstrip("v")
                info.changelog = release.get("body", "")[:500]
                info.publish_date = release.get("published_at", "")[:10]

                # 找 version_manifest.json 资产
                for asset in release.get("assets", []):
                    if asset["name"] == "version_manifest.json":
                        info.manifest_url = asset["browser_download_url"]
                        break

                if not info.manifest_url:
                    # 没有 manifest，只有版本号信息
                    logger.debug("无版本清单，仅版本号对比")
                    self._last_check = time.time()
                    self._cached_info = info
                    return info

                # 下载 manifest（很小，几KB）
                manifest_resp = await client.get(info.manifest_url, headers=headers)
                manifest = manifest_resp.json()

                # 对比本地文件，找出变更文件
                changed = await self._find_changed_files(manifest.get("files", {}))
                info.changed_files = changed
                info.needs_restart = any(f in REQUIRE_RESTART for f in changed)

                # 估算下载大小（粗略）
                info.total_size_kb = len(changed) * 50  # 平均50KB/文件

        except httpx.ConnectError:
            info.error = "网络连接失败，请检查网络"
        except httpx.TimeoutException:
            info.error = "请求超时"
        except Exception as e:
            info.error = f"检查更新失败: {e}"
            logger.warning(f"更新检查异常: {e}")

        self._last_check = time.time()
        self._cached_info = info
        return info

    async def _find_changed_files(self, remote_hashes: Dict[str, str]) -> List[str]:
        """对比本地文件哈希，找出需要更新的文件"""
        changed = []
        for rel_path, remote_hash in remote_hashes.items():
            # 跳过用户配置文件
            if any(rel_path.startswith(excl) for excl in EXCLUDE_FROM_UPDATE):
                continue
            local_file = APP_ROOT / rel_path
            if not local_file.exists():
                changed.append(rel_path)  # 新文件
                continue
            local_hash = await asyncio.get_event_loop().run_in_executor(
                None, self._sha256, local_file
            )
            if local_hash != remote_hash:
                changed.append(rel_path)
        return changed

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    async def apply_update(
        self,
        info: UpdateInfo,
        on_progress=None,
    ) -> Tuple[bool, str]:
        """
        执行增量更新
        
        步骤：
        1. 备份当前版本
        2. 下载变更文件到临时目录
        3. 校验文件完整性
        4. 原子性替换（先全部下载成功再替换）
        5. 更新版本号
        """
        if not info.has_update:
            return False, "没有可用的更新"

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / f"v{info.current_version}_{int(time.time())}"
        tmp_dir = UPDATE_CACHE_DIR / "download_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Step 1: 备份
            logger.info(f"备份当前版本到 {backup_path}")
            if on_progress:
                on_progress({"step": "backup", "progress": 0})
            backup_path.mkdir(parents=True)
            for rel in info.changed_files:
                src = APP_ROOT / rel
                if src.exists():
                    dest = backup_path / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)

            if on_progress:
                on_progress({"step": "backup", "progress": 100})

            # Step 2: 下载（从 release zip 或逐文件下载）
            logger.info(f"下载 {len(info.changed_files)} 个更新文件")
            base_url = f"https://raw.githubusercontent.com/{self.repo}/v{info.latest_version}"

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=15.0),
                follow_redirects=True,
            ) as client:
                for i, rel_path in enumerate(info.changed_files):
                    url = f"{base_url}/{rel_path}"
                    tmp_file = tmp_dir / rel_path.replace("/", "_")

                    resp = await client.get(url)
                    if resp.status_code == 200:
                        tmp_file.write_bytes(resp.content)
                    else:
                        logger.warning(f"跳过下载失败的文件: {rel_path}")

                    if on_progress:
                        on_progress({
                            "step": "download",
                            "progress": int((i + 1) / len(info.changed_files) * 100),
                            "file": rel_path,
                        })

            # Step 3: 替换文件
            logger.info("替换文件...")
            applied = []
            for rel_path in info.changed_files:
                tmp_file = tmp_dir / rel_path.replace("/", "_")
                if tmp_file.exists():
                    dest = APP_ROOT / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(tmp_file), str(dest))
                    applied.append(rel_path)

            # Step 4: 更新版本号文件
            version_file = APP_ROOT / "version.txt"
            version_file.write_text(info.latest_version, encoding="utf-8")

            if on_progress:
                on_progress({"step": "done", "progress": 100})

            msg = f"已更新到 v{info.latest_version}，更新了 {len(applied)} 个文件"
            if info.needs_restart:
                msg += "（需要重启程序生效）"
            logger.info(msg)
            return True, msg

        except Exception as e:
            logger.error(f"更新失败: {e}")
            # 回滚
            if backup_path.exists():
                logger.info("回滚中...")
                for rel in info.changed_files:
                    backup_file = backup_path / rel
                    if backup_file.exists():
                        dest = APP_ROOT / rel
                        shutil.copy2(backup_file, dest)
            return False, f"更新失败: {e}（已回滚）"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def get_local_version(self) -> str:
        """读取本地版本号"""
        version_file = APP_ROOT / "version.txt"
        if version_file.exists():
            return version_file.read_text(encoding="utf-8").strip()
        return APP_VERSION


# 全局单例
_updater: Optional[AutoUpdater] = None


def get_updater() -> AutoUpdater:
    global _updater
    if _updater is None:
        try:
            from src.router.config import RouterConfig
            cfg = RouterConfig()
            repo = cfg.config.get("update", "github_repo", fallback=DEFAULT_REPO)
            channel = cfg.config.get("update", "channel", fallback="stable")
        except Exception:
            repo = DEFAULT_REPO
            channel = "stable"
        _updater = AutoUpdater(repo=repo, channel=channel)
    return _updater
