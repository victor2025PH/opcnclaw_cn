# -*- coding: utf-8 -*-
"""
文件双向传输 — 手机 ↔ 电脑

功能：
  - 手机上传文件到电脑（multipart/form-data）
  - 电脑推送文件到手机（下载链接）
  - 大文件分片上传（>10MB 自动分片）
  - 传输历史 + 24h 自动清理
  - AI 辅助传输（"把桌面的报告发到手机"）
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

TRANSFER_DIR = Path("data/transfers")
TRANSFER_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
AUTO_CLEANUP_HOURS = 24


class TransferRecord:
    """传输记录"""
    def __init__(self, file_id: str, filename: str, size: int,
                 direction: str, path: str):
        self.file_id = file_id
        self.filename = filename
        self.size = size
        self.direction = direction  # upload / push
        self.path = path
        self.created_at = time.time()
        self.downloaded = False

    def to_dict(self) -> dict:
        return {
            "id": self.file_id,
            "filename": self.filename,
            "size": self.size,
            "size_human": self._human_size(),
            "direction": self.direction,
            "created_at": round(self.created_at, 1),
            "downloaded": self.downloaded,
            "download_url": f"/api/files/{self.file_id}/download",
        }

    def _human_size(self) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if self.size < 1024:
                return f"{self.size:.1f}{unit}"
            self.size /= 1024
        return f"{self.size:.1f}TB"


class FileTransferManager:
    """文件传输管理器"""

    def __init__(self):
        self._records: Dict[str, TransferRecord] = {}
        self._cleanup_old_files()

    def upload(self, filename: str, content: bytes) -> TransferRecord:
        """手机上传文件到电脑"""
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"文件过大（上限 {MAX_FILE_SIZE // 1024 // 1024}MB）")

        self._check_total_size()

        file_id = str(uuid.uuid4())[:12]
        safe_name = self._safe_filename(filename)
        file_path = TRANSFER_DIR / f"{file_id}_{safe_name}"
        file_path.write_bytes(content)

        record = TransferRecord(
            file_id=file_id, filename=safe_name,
            size=len(content), direction="upload",
            path=str(file_path),
        )
        self._records[file_id] = record

        # 同时保存到桌面（用户友好）
        try:
            desktop = Path.home() / "Desktop" / safe_name
            if not desktop.exists():
                shutil.copy2(str(file_path), str(desktop))
                logger.info(f"[FileTransfer] 已保存到桌面: {safe_name}")
        except Exception:
            pass

        logger.info(f"[FileTransfer] 上传: {safe_name} ({len(content)} bytes)")
        return record

    def push(self, source_path: str) -> Optional[TransferRecord]:
        """电脑推送文件到手机（创建下载链接）"""
        p = Path(source_path)
        if not p.exists():
            return None

        file_id = str(uuid.uuid4())[:12]
        safe_name = p.name
        dest = TRANSFER_DIR / f"{file_id}_{safe_name}"
        shutil.copy2(str(p), str(dest))

        record = TransferRecord(
            file_id=file_id, filename=safe_name,
            size=dest.stat().st_size, direction="push",
            path=str(dest),
        )
        self._records[file_id] = record
        logger.info(f"[FileTransfer] 推送: {safe_name}")
        return record

    def get_file_path(self, file_id: str) -> Optional[Path]:
        """获取文件路径（用于下载）"""
        record = self._records.get(file_id)
        if not record:
            return None
        p = Path(record.path)
        if p.exists():
            record.downloaded = True
            return p
        return None

    def list_records(self, limit: int = 20) -> List[dict]:
        records = sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in records[:limit]]

    def delete(self, file_id: str) -> bool:
        record = self._records.pop(file_id, None)
        if record:
            try:
                Path(record.path).unlink(missing_ok=True)
            except Exception:
                pass
            return True
        return False

    def _safe_filename(self, filename: str) -> str:
        """安全文件名"""
        name = "".join(c for c in filename if c.isalnum() or c in "._-()（）中文 ")
        return name[:200] or "unnamed"

    def _check_total_size(self):
        """检查总空间"""
        total = sum(f.stat().st_size for f in TRANSFER_DIR.iterdir() if f.is_file())
        if total > MAX_TOTAL_SIZE:
            self._cleanup_old_files(force=True)

    def _cleanup_old_files(self, force: bool = False):
        """清理过期文件"""
        if not TRANSFER_DIR.exists():
            TRANSFER_DIR.mkdir(parents=True, exist_ok=True)
            return
        cutoff = time.time() - (AUTO_CLEANUP_HOURS * 3600)
        for f in TRANSFER_DIR.iterdir():
            if f.is_file():
                if force or f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
        # 清理记录
        expired = [fid for fid, r in self._records.items()
                   if r.created_at < cutoff]
        for fid in expired:
            del self._records[fid]


# 全局单例
_manager: Optional[FileTransferManager] = None

def get_transfer_manager() -> FileTransferManager:
    global _manager
    if _manager is None:
        _manager = FileTransferManager()
    return _manager
