# -*- coding: utf-8 -*-
"""
轨道A: 微信数据库直读器

原理：
  微信 PC 版所有聊天记录存储在本地 SQLite 数据库（SQLCipher 加密）。
  通过从微信进程内存提取密钥，解密后直接读取消息。

  完全不操作 UI，不切换窗口，不打断用户。
  支持微信 3.x 和 4.x 版本。

数据库位置：
  Windows: Documents\\WeChat Files\\<wxid>\\Msg\\
  - MicroMsg.db  → 联系人信息
  - Multi\\MSG*.db → 聊天记录（分片存储，单文件 ≤ 60MB）

加密参数（WeChat SQLCipher）：
  - Cipher: AES-256-CBC
  - KDF: PBKDF2-HMAC-SHA1, 64000 iterations
  - HMAC: SHA1
  - Page size: 4096
  - Reserve: 48 bytes (16 IV + 20 HMAC + 12 padding)
"""

import hashlib
import hmac
import os
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from .models import WxChat, WxMessage

IS_WINDOWS = sys.platform == "win32"

# SQLCipher 参数（微信专用）
PAGE_SIZE = 4096
RESERVE_SIZE = 48  # 16 IV + 20 HMAC-SHA1 + 12 padding
IV_SIZE = 16
HMAC_SIZE = 20
SALT_SIZE = 16
KDF_ITERATIONS = 64000
SQLITE_HEADER = b"SQLite format 3\x00"

# 密钥缓存文件
KEY_CACHE_FILE = "wechat_db_key.bin"


class WeChatDBReader:
    """
    微信数据库直读器

    使用方式：
        reader = WeChatDBReader()
        if reader.available:
            messages = reader.get_new_messages(since_ts=last_check)
            contacts = reader.get_contacts()
    """

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir: Optional[Path] = Path(data_dir) if data_dir else None
        self._key: Optional[bytes] = None
        self._decrypt_dir: Optional[Path] = None
        self._contacts_cache: Dict[str, str] = {}  # wxid → nickname
        self._last_decrypt_time: float = 0
        self._db_mtimes: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._initialized = False
        # watchdog 事件驱动
        self._observer = None
        self._wal_changed = threading.Event()
        self._watch_thread: Optional[threading.Thread] = None
        self._watching = False
        self._change_callbacks: List = []

    @property
    def available(self) -> bool:
        return self._initialized and self._key is not None

    def initialize(self) -> bool:
        """
        初始化：查找数据目录 → 提取密钥 → 首次解密。
        耗时可能较长（密钥提取 5~30 秒），建议在后台线程调用。
        """
        if self._initialized:
            return self.available

        try:
            # Step 1: 查找数据目录
            if not self._data_dir:
                self._data_dir = self._find_data_dir()
            if not self._data_dir or not self._data_dir.exists():
                logger.warning("[DB Reader] 未找到微信数据目录")
                return False
            logger.info(f"[DB Reader] 数据目录: {self._data_dir}")

            # Step 2: 提取密钥
            self._key = self._get_key()
            if not self._key:
                logger.warning("[DB Reader] 无法获取数据库密钥")
                return False
            logger.info("[DB Reader] ✅ 密钥已获取")

            # Step 3: 创建解密工作目录
            self._decrypt_dir = Path(tempfile.mkdtemp(prefix="openclaw_wxdb_"))
            logger.info(f"[DB Reader] 解密目录: {self._decrypt_dir}")

            # Step 4: 首次解密
            self._decrypt_all()
            self._load_contacts()
            self._initialized = True
            logger.info(f"[DB Reader] ✅ 初始化完成，联系人 {len(self._contacts_cache)} 个")
            return True

        except Exception as e:
            logger.error(f"[DB Reader] 初始化失败: {e}")
            return False

    def get_new_messages(self, since_ts: float = 0, limit: int = 50) -> List[WxMessage]:
        """
        获取指定时间戳之后的新消息。
        自动检测数据库变化并增量解密。
        """
        if not self.available:
            return []

        with self._lock:
            self._refresh_if_changed()

        messages = []
        try:
            msg_dbs = sorted(self._decrypt_dir.glob("MSG*.db"))
            for db_path in msg_dbs:
                try:
                    msgs = self._read_messages(db_path, since_ts, limit - len(messages))
                    messages.extend(msgs)
                    if len(messages) >= limit:
                        break
                except Exception as e:
                    logger.debug(f"[DB Reader] 读取 {db_path.name} 出错: {e}")
        except Exception as e:
            logger.error(f"[DB Reader] get_new_messages: {e}")

        return messages

    def get_contacts(self) -> Dict[str, str]:
        """返回 wxid → 昵称 映射"""
        if not self.available:
            return {}
        return dict(self._contacts_cache)

    def get_contact_name(self, wxid: str) -> str:
        """wxid → 昵称，未找到返回 wxid 本身"""
        return self._contacts_cache.get(wxid, wxid)

    def get_status(self) -> Dict:
        return {
            "available": self.available,
            "data_dir": str(self._data_dir) if self._data_dir else None,
            "has_key": self._key is not None,
            "contacts_count": len(self._contacts_cache),
            "last_decrypt": self._last_decrypt_time,
            "decrypt_dir": str(self._decrypt_dir) if self._decrypt_dir else None,
        }

    # ── 数据目录查找 ────────────────────────────────────────────────────────

    def _find_data_dir(self) -> Optional[Path]:
        """自动查找微信数据存储目录"""
        if not IS_WINDOWS:
            return None

        candidates = []

        # 策略1: 从注册表读取自定义路径
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Tencent\WeChat",
                0,
                winreg.KEY_READ,
            )
            path, _ = winreg.QueryValueEx(key, "FileSavePath")
            winreg.CloseKey(key)
            if path and path != "MyDocument:":
                candidates.append(Path(path))
        except Exception:
            pass

        # 策略2: 默认 Documents 路径
        docs = Path(os.path.expanduser("~")) / "Documents" / "WeChat Files"
        candidates.append(docs)

        # 策略3: D 盘常见路径
        for drive in ["D:", "E:", "C:"]:
            candidates.append(Path(drive) / "WeChat Files")

        # 找到包含 Msg 子目录的 wxid 目录
        for base in candidates:
            if not base.exists():
                continue
            for sub in base.iterdir():
                if sub.is_dir() and (sub / "Msg").exists():
                    msg_dir = sub / "Msg"
                    # 验证有加密数据库文件
                    multi_dir = msg_dir / "Multi"
                    if multi_dir.exists() and list(multi_dir.glob("MSG*.db")):
                        return msg_dir
                    if list(msg_dir.glob("*.db")):
                        return msg_dir

        return None

    # ── 密钥获取 ─────────────────────────────────────────────────────────

    def _get_key(self) -> Optional[bytes]:
        """获取数据库解密密钥"""
        # 策略1: 从缓存文件读取
        key = self._load_cached_key()
        if key and self._verify_key(key):
            logger.info("[DB Reader] 使用缓存密钥")
            return key

        # 策略2: 从进程内存提取
        key = self._extract_key_from_memory()
        if key:
            self._cache_key(key)
            return key

        # 策略3: 尝试 PyWxDump（如果安装了）
        key = self._try_pywxdump()
        if key:
            self._cache_key(key)
            return key

        return None

    def _extract_key_from_memory(self) -> Optional[bytes]:
        """从微信进程内存中提取 32 字节密钥"""
        if not IS_WINDOWS:
            return None

        try:
            import ctypes
            import ctypes.wintypes
            from ctypes import byref, c_size_t, c_ubyte, c_void_p, sizeof

            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_VM_READ = 0x0010
            MEM_COMMIT = 0x1000

            class MEMORY_BASIC_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BaseAddress", c_void_p),
                    ("AllocationBase", c_void_p),
                    ("AllocationProtect", ctypes.wintypes.DWORD),
                    ("RegionSize", c_size_t),
                    ("State", ctypes.wintypes.DWORD),
                    ("Protect", ctypes.wintypes.DWORD),
                    ("Type", ctypes.wintypes.DWORD),
                ]

            kernel32 = ctypes.windll.kernel32

            # 读取 DB 文件头获取 salt
            salt = self._get_db_salt()
            if not salt:
                logger.warning("[DB Reader] 无法读取数据库 salt")
                return None

            # 查找 WeChat 进程
            pid = self._find_wechat_pid()
            if not pid:
                logger.warning("[DB Reader] 未找到微信进程")
                return None
            logger.info(f"[DB Reader] 微信进程 PID: {pid}")

            # 打开进程
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
            )
            if not handle:
                logger.warning("[DB Reader] 无法打开微信进程（需要管理员权限？）")
                return None

            try:
                # 枚举内存区域，搜索密钥
                PAGE_READABLE = {0x02, 0x04, 0x06, 0x20, 0x40, 0x80}
                address = 0
                max_address = 0x7FFFFFFFFFFF
                candidates = []
                scanned_bytes = 0
                max_scan = 500 * 1024 * 1024  # 最多扫描 500MB

                mbi = MEMORY_BASIC_INFORMATION()

                while address < max_address and scanned_bytes < max_scan:
                    result = kernel32.VirtualQueryEx(
                        handle, c_void_p(address), byref(mbi), sizeof(mbi)
                    )
                    if result == 0:
                        break

                    region_size = mbi.RegionSize
                    if (
                        mbi.State == MEM_COMMIT
                        and mbi.Protect in PAGE_READABLE
                        and 4096 < region_size < 30 * 1024 * 1024
                    ):
                        try:
                            buffer = (c_ubyte * region_size)()
                            bytes_read = c_size_t()
                            if kernel32.ReadProcessMemory(
                                handle, c_void_p(mbi.BaseAddress),
                                buffer, region_size, byref(bytes_read)
                            ):
                                data = bytes(buffer[: bytes_read.value])
                                scanned_bytes += len(data)
                                # 每 32 字节对齐位置检查
                                found = self._scan_for_key_candidates(data)
                                candidates.extend(found)
                        except Exception:
                            pass

                    address = (mbi.BaseAddress or 0) + region_size
                    if address <= (mbi.BaseAddress or 0):
                        break

                logger.info(
                    f"[DB Reader] 扫描 {scanned_bytes / 1024 / 1024:.1f}MB，"
                    f"候选密钥 {len(candidates)} 个"
                )

                # 验证候选密钥
                for candidate in candidates[:200]:  # 最多验证 200 个
                    if self._verify_key(candidate):
                        logger.info("[DB Reader] ✅ 密钥验证通过")
                        return candidate

            finally:
                kernel32.CloseHandle(handle)

        except Exception as e:
            logger.error(f"[DB Reader] 内存提取密钥失败: {e}")

        return None

    def _scan_for_key_candidates(self, data: bytes) -> List[bytes]:
        """从内存块中扫描可能的 32 字节密钥"""
        candidates = []
        data_len = len(data)
        if data_len < 32:
            return candidates

        for offset in range(0, data_len - 31, 8):  # 8 字节对齐
            chunk = data[offset: offset + 32]
            if len(chunk) < 32:
                break

            # 快速过滤：跳过明显不是密钥的数据
            if chunk == b"\x00" * 32:
                continue
            if chunk == b"\xff" * 32:
                continue

            # 零字节不能太多（真密钥是高熵随机数据）
            zero_count = chunk.count(0)
            if zero_count > 8:
                continue

            # 同一字节不能占太多
            byte_freq = {}
            for b in chunk:
                byte_freq[b] = byte_freq.get(b, 0) + 1
            max_freq = max(byte_freq.values())
            if max_freq > 10:
                continue

            # 不同字节种类要足够多（高熵）
            if len(byte_freq) < 12:
                continue

            candidates.append(chunk)

        return candidates

    def _verify_key(self, raw_key: bytes) -> bool:
        """验证密钥是否能解密数据库第一页"""
        salt = self._get_db_salt()
        if not salt or len(raw_key) != 32:
            return False

        try:
            db_path = self._find_any_db()
            if not db_path:
                return False

            with open(db_path, "rb") as f:
                page1 = f.read(PAGE_SIZE)

            if len(page1) < PAGE_SIZE:
                return False

            # PBKDF2 推导加密密钥
            enc_key = hashlib.pbkdf2_hmac(
                "sha1", raw_key, salt, KDF_ITERATIONS, dklen=32
            )

            # PBKDF2 推导 HMAC 密钥
            hmac_key = hashlib.pbkdf2_hmac("sha1", enc_key, salt, 2, dklen=32)

            # 解密第一页（跳过 salt 的 16 字节）
            usable_size = PAGE_SIZE - RESERVE_SIZE  # 4048
            encrypted = page1[SALT_SIZE:usable_size]  # bytes 16 ~ 4047
            iv = page1[usable_size: usable_size + IV_SIZE]  # bytes 4048 ~ 4063
            stored_hmac = page1[
                usable_size + IV_SIZE: usable_size + IV_SIZE + HMAC_SIZE
            ]

            # HMAC 验证
            hmac_data = page1[SALT_SIZE:usable_size + IV_SIZE]
            page_no = struct.pack("<I", 1)
            h = hmac.new(hmac_key, hmac_data + page_no, hashlib.sha1)
            if h.digest() != stored_hmac:
                return False

            # AES-CBC 解密
            from Crypto.Cipher import AES

            cipher = AES.new(enc_key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted)

            # 解密后的数据应以 SQLite 头标识开始（偏移 0，对应原文件的偏移 16）
            # 原 SQLite 头 "SQLite format 3\0" 在被加密时位于 page1[0:16]，
            # 但该位置被 salt 覆盖了。解密后第一个有意义的字节应该是 page_size 等元信息。
            # 简单验证：解密数据不应全为零或全相同
            if decrypted[:16] == b"\x00" * 16:
                return False
            if len(set(decrypted[:64])) < 5:
                return False

            return True

        except ImportError:
            logger.warning("[DB Reader] 需要 pycryptodome: pip install pycryptodome")
            return False
        except Exception:
            return False

    def _get_db_salt(self) -> Optional[bytes]:
        """读取任意一个 DB 文件的前 16 字节作为 salt"""
        db = self._find_any_db()
        if not db:
            return None
        try:
            with open(db, "rb") as f:
                salt = f.read(SALT_SIZE)
            return salt if len(salt) == SALT_SIZE else None
        except Exception:
            return None

    def _find_any_db(self) -> Optional[Path]:
        """找到任意一个消息数据库文件"""
        if not self._data_dir:
            return None
        multi = self._data_dir / "Multi"
        if multi.exists():
            dbs = sorted(multi.glob("MSG*.db"))
            if dbs:
                return dbs[0]
        dbs = sorted(self._data_dir.glob("*.db"))
        return dbs[0] if dbs else None

    def _find_wechat_pid(self) -> Optional[int]:
        """查找 WeChat.exe 进程 PID"""
        if not IS_WINDOWS:
            return None
        try:
            import subprocess

            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq WeChat.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            for line in r.stdout.strip().split("\n"):
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2 and "WeChat" in parts[0]:
                    return int(parts[1])
        except Exception:
            pass
        return None

    def _try_pywxdump(self) -> Optional[bytes]:
        """尝试用 PyWxDump 获取密钥"""
        try:
            from pywxdump import get_wechat_info

            infos = get_wechat_info()
            if infos and isinstance(infos, list):
                for info in infos:
                    key_hex = info.get("key", "")
                    if key_hex and len(key_hex) == 64:
                        return bytes.fromhex(key_hex)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"PyWxDump key extraction: {e}")
        return None

    def _load_cached_key(self) -> Optional[bytes]:
        """从缓存文件加载密钥"""
        try:
            cache = Path(__file__).parent.parent.parent.parent / "data" / KEY_CACHE_FILE
            if cache.exists():
                data = cache.read_bytes()
                if len(data) == 32:
                    return data
        except Exception:
            pass
        return None

    def _cache_key(self, key: bytes):
        """缓存密钥到文件"""
        try:
            cache_dir = Path(__file__).parent.parent.parent.parent / "data"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / KEY_CACHE_FILE).write_bytes(key)
        except Exception:
            pass

    # ── 数据库解密 ───────────────────────────────────────────────────────

    def _decrypt_all(self):
        """解密所有消息数据库到临时目录"""
        if not self._data_dir or not self._key or not self._decrypt_dir:
            return

        try:
            from Crypto.Cipher import AES
        except ImportError:
            logger.error("[DB Reader] 需要 pycryptodome: pip install pycryptodome")
            return

        # 解密联系人数据库
        micro_msg = self._data_dir / "MicroMsg.db"
        if micro_msg.exists():
            out = self._decrypt_dir / "MicroMsg.db"
            self._decrypt_db(micro_msg, out)

        # 解密消息数据库
        multi = self._data_dir / "Multi"
        if multi.exists():
            for db_file in sorted(multi.glob("MSG*.db")):
                out = self._decrypt_dir / db_file.name
                self._decrypt_db(db_file, out)
                self._db_mtimes[str(db_file)] = db_file.stat().st_mtime

        self._last_decrypt_time = time.time()

    def _decrypt_db(self, src: Path, dst: Path) -> bool:
        """解密单个数据库文件"""
        try:
            from Crypto.Cipher import AES

            with open(src, "rb") as f:
                data = f.read()

            if len(data) < PAGE_SIZE:
                return False

            salt = data[:SALT_SIZE]
            enc_key = hashlib.pbkdf2_hmac("sha1", self._key, salt, KDF_ITERATIONS, dklen=32)

            total_pages = len(data) // PAGE_SIZE
            decrypted_pages = []

            for page_no in range(total_pages):
                page_offset = page_no * PAGE_SIZE
                page_data = data[page_offset: page_offset + PAGE_SIZE]

                usable_size = PAGE_SIZE - RESERVE_SIZE
                iv = page_data[usable_size: usable_size + IV_SIZE]

                if page_no == 0:
                    encrypted = page_data[SALT_SIZE:usable_size]
                    cipher = AES.new(enc_key, AES.MODE_CBC, iv)
                    decrypted = cipher.decrypt(encrypted)
                    # 还原 SQLite 文件头
                    decrypted_pages.append(
                        SQLITE_HEADER + decrypted[len(SQLITE_HEADER) - SALT_SIZE:]
                        if len(decrypted) > len(SQLITE_HEADER)
                        else SQLITE_HEADER + b"\x00" * (usable_size - SALT_SIZE - len(SQLITE_HEADER))
                    )
                else:
                    encrypted = page_data[:usable_size]
                    cipher = AES.new(enc_key, AES.MODE_CBC, iv)
                    decrypted = cipher.decrypt(encrypted)
                    decrypted_pages.append(decrypted)

                # 用零填充 reserve 区域
                decrypted_pages.append(b"\x00" * RESERVE_SIZE)

            with open(dst, "wb") as f:
                f.write(b"".join(decrypted_pages))

            return True

        except Exception as e:
            logger.debug(f"[DB Reader] 解密 {src.name} 失败: {e}")
            return False

    def _refresh_if_changed(self):
        """检查源数据库是否有变化，有则重新解密"""
        if not self._data_dir:
            return

        changed = False
        multi = self._data_dir / "Multi"
        if multi.exists():
            for db_file in multi.glob("MSG*.db"):
                key = str(db_file)
                try:
                    current_mtime = db_file.stat().st_mtime
                    # 也检查 WAL 文件
                    wal = db_file.with_suffix(".db-wal")
                    if wal.exists():
                        wal_mtime = wal.stat().st_mtime
                        current_mtime = max(current_mtime, wal_mtime)
                except Exception:
                    continue

                if key not in self._db_mtimes or self._db_mtimes[key] < current_mtime:
                    out = self._decrypt_dir / db_file.name
                    if self._decrypt_db(db_file, out):
                        self._db_mtimes[key] = current_mtime
                        changed = True

        if changed:
            self._last_decrypt_time = time.time()

    # ── 消息读取 ─────────────────────────────────────────────────────────

    def _read_messages(self, db_path: Path, since_ts: float, limit: int) -> List[WxMessage]:
        """从解密的 SQLite 读取消息"""
        messages = []
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 查询消息表（微信用 MSG 表）
            table_name = self._find_msg_table(cursor)
            if not table_name:
                conn.close()
                return []

            since_unix = int(since_ts) if since_ts > 0 else 0
            cursor.execute(
                f"SELECT * FROM {table_name} "
                f"WHERE CreateTime > ? "
                f"ORDER BY CreateTime DESC LIMIT ?",
                (since_unix, limit),
            )

            for row in cursor.fetchall():
                try:
                    msg = self._row_to_message(row)
                    if msg:
                        messages.append(msg)
                except Exception:
                    continue

            conn.close()
        except Exception as e:
            logger.debug(f"[DB Reader] read_messages({db_path.name}): {e}")

        return messages

    def _find_msg_table(self, cursor) -> Optional[str]:
        """查找消息表名"""
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            for candidate in ["MSG", "Message", "ChatMsg"]:
                if candidate in tables:
                    return candidate
            # 模糊匹配
            for t in tables:
                if "msg" in t.lower() or "message" in t.lower():
                    return t
        except Exception:
            pass
        return None

    def _row_to_message(self, row) -> Optional[WxMessage]:
        """将数据库行转换为 WxMessage"""
        try:
            keys = row.keys()
            wxid = row["StrTalker"] if "StrTalker" in keys else ""
            content = row["StrContent"] if "StrContent" in keys else ""
            create_time = row["CreateTime"] if "CreateTime" in keys else 0
            is_sender = row["IsSender"] if "IsSender" in keys else 0
            msg_type_raw = row["Type"] if "Type" in keys else 1
            msg_svr_id = str(row["MsgSvrID"]) if "MsgSvrID" in keys else ""

            if not content or not wxid:
                return None

            # 类型映射
            type_map = {
                1: "text",
                3: "image",
                34: "voice",
                43: "video",
                47: "emoji",
                49: "link",
                10000: "system",
                10002: "system",
            }
            msg_type = type_map.get(msg_type_raw, "text")

            # 联系人名称解析
            contact_name = self.get_contact_name(wxid)
            is_group = wxid.endswith("@chatroom")

            # 群聊时提取发送人
            sender = ""
            if is_group and not is_sender and ":\n" in content:
                parts = content.split(":\n", 1)
                sender = self.get_contact_name(parts[0])
                content = parts[1]

            at_me = "@所有人" in content or bool(re.search(r"@\S+", content))

            return WxMessage(
                contact=contact_name,
                sender=sender,
                content=content,
                msg_id=msg_svr_id,
                is_group=is_group,
                at_me=at_me,
                is_mine=bool(is_sender),
                timestamp=float(create_time),
                msg_type=msg_type,
                source="db",
            )
        except Exception:
            return None

    def _load_contacts(self):
        """从 MicroMsg.db 加载联系人映射"""
        if not self._decrypt_dir:
            return
        db_path = self._decrypt_dir / "MicroMsg.db"
        if not db_path.exists():
            return
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            cursor = conn.cursor()

            # 查找联系人表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]

            contact_table = None
            for t in ["Contact", "contact", "FTSContactTrans"]:
                if t in tables:
                    contact_table = t
                    break

            if contact_table:
                try:
                    cursor.execute(
                        f"SELECT UserName, NickName, Alias, Remark "
                        f"FROM {contact_table}"
                    )
                    for row in cursor.fetchall():
                        wxid = row[0] or ""
                        nickname = row[3] or row[1] or row[2] or wxid  # Remark > NickName > Alias
                        if wxid:
                            self._contacts_cache[wxid] = nickname
                except Exception:
                    pass

            conn.close()
        except Exception as e:
            logger.debug(f"[DB Reader] load_contacts: {e}")

    # ── 事件驱动监听（watchdog）────────────────────────────────────────────

    def on_change(self, callback):
        """注册数据库变化回调（有新消息时触发）"""
        self._change_callbacks.append(callback)

    def start_watching(self):
        """
        启动 WAL 文件变化监听。
        优先使用 watchdog 库（事件驱动，CPU 占用极低），
        降级到轻量级 mtime 轮询。
        """
        if self._watching:
            return
        if not self._data_dir:
            return

        self._watching = True
        watch_dir = self._data_dir / "Multi"
        if not watch_dir.exists():
            watch_dir = self._data_dir

        # 尝试 watchdog
        if self._start_watchdog(watch_dir):
            logger.info(f"[DB Reader] ✅ watchdog 事件监听已启动: {watch_dir}")
            return

        # 降级到轮询
        self._watch_thread = threading.Thread(
            target=self._poll_loop,
            args=(watch_dir,),
            name="DBReader-Poll",
            daemon=True,
        )
        self._watch_thread.start()
        logger.info(f"[DB Reader] ✅ 轮询监听已启动 (watchdog 不可用): {watch_dir}")

    def stop_watching(self):
        """停止监听"""
        self._watching = False
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=3)
            except Exception:
                pass
            self._observer = None
        if self._watch_thread:
            self._watch_thread = None

    def _start_watchdog(self, watch_dir: Path) -> bool:
        """尝试启动 watchdog 文件系统监听"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class WALHandler(FileSystemEventHandler):
                def __init__(self, reader):
                    self._reader = reader
                    self._last_event = 0

                def on_modified(self, event):
                    if event.is_directory:
                        return
                    path = event.src_path
                    if path.endswith((".db-wal", ".db-shm", ".db")):
                        now = time.time()
                        # 防抖：500ms 内多次事件只触发一次
                        if now - self._last_event < 0.5:
                            return
                        self._last_event = now
                        self._reader._on_wal_changed()

            self._observer = Observer()
            self._observer.schedule(
                WALHandler(self), str(watch_dir), recursive=False
            )
            self._observer.daemon = True
            self._observer.start()
            return True

        except ImportError:
            logger.debug("[DB Reader] watchdog 未安装，降级到轮询")
            return False
        except Exception as e:
            logger.debug(f"[DB Reader] watchdog 启动失败: {e}")
            return False

    def _poll_loop(self, watch_dir: Path):
        """轻量级 mtime 轮询（watchdog 不可用时的降级方案）"""
        known_mtimes: Dict[str, float] = {}
        while self._watching:
            try:
                changed = False
                for f in watch_dir.glob("*.db-wal"):
                    key = str(f)
                    try:
                        mt = f.stat().st_mtime
                    except Exception:
                        continue
                    if key in known_mtimes and known_mtimes[key] < mt:
                        changed = True
                    known_mtimes[key] = mt

                if changed:
                    self._on_wal_changed()

            except Exception:
                pass
            time.sleep(2.0)  # 2 秒轮询

    def _on_wal_changed(self):
        """WAL 变化时触发：增量解密 + 通知回调"""
        with self._lock:
            self._refresh_if_changed()
        for cb in self._change_callbacks:
            try:
                cb()
            except Exception:
                pass

    def cleanup(self):
        """清理临时解密文件并停止监听"""
        self.stop_watching()
        if self._decrypt_dir and self._decrypt_dir.exists():
            try:
                shutil.rmtree(self._decrypt_dir, ignore_errors=True)
            except Exception:
                pass
