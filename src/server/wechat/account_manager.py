# -*- coding: utf-8 -*-
"""
微信多账号并行管理器

架构设计（v2: 真并行模式）：
  微信PC版支持同时多开（多个进程，多个窗口），因此本模块
  实现真正的「多实例并行」管理——每个微信号有独立的：
    - wxauto.WeChat() 连接（绑定到特定窗口句柄）
    - WxAutoReader 读取器
    - 自动回复配置
    - 朋友圈策略
    - 数据存储目录

  核心流程：
    1. discover_instances() — 扫描所有运行中的微信窗口
    2. bind_account(acct_id, hwnd) — 将账号绑定到指定窗口
    3. get_wx(acct_id) — 获取该账号的 wxauto 实例
    4. 各模块通过 account_id 参数路由到正确的实例

  窗口发现原理：
    用 uiautomation / ctypes 枚举所有 ClassName='WeChatMainWndForPC'
    的顶级窗口，每个窗口 = 一个微信实例。
"""

from __future__ import annotations

import ctypes
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger
from .. import db as _db

ACCOUNTS_DIR = Path("data/accounts")
_lock = threading.Lock()


def _get_conn():
    return _db.get_conn("wechat")


@dataclass
class WeChatInstance:
    """一个运行中的微信窗口实例"""
    hwnd: int = 0
    pid: int = 0
    title: str = ""
    wx_name: str = ""
    bound_account_id: str = ""


@dataclass
class WeChatAccount:
    id: str = ""
    name: str = ""
    wx_name: str = ""
    avatar_url: str = ""
    hwnd: int = 0
    pid: int = 0
    autoreply_config: Dict = field(default_factory=dict)
    moments_config: Dict = field(default_factory=dict)
    is_active: bool = True
    created_at: float = 0
    last_active: float = 0
    notes: str = ""
    status: str = "disconnected"

    def data_dir(self) -> Path:
        d = ACCOUNTS_DIR / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "name": self.name, "wx_name": self.wx_name,
            "avatar_url": self.avatar_url,
            "hwnd": self.hwnd, "pid": self.pid,
            "autoreply_config": self.autoreply_config,
            "moments_config": self.moments_config,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "notes": self.notes,
            "status": self.status,
        }


# ── 窗口发现 ──────────────────────────────────────────────────────────────────

# 微信主窗口的 Win32 类名
WX_CLASS_NAMES = ["WeChatMainWndForPC", "WeChat MainWndForPC", "WeChatMainWnd"]

EnumWindows = ctypes.windll.user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
GetWindowText = ctypes.windll.user32.GetWindowTextW
GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
GetClassName = ctypes.windll.user32.GetClassNameW
IsWindowVisible = ctypes.windll.user32.IsWindowVisible
GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId


def _get_window_title(hwnd: int) -> str:
    length = GetWindowTextLength(hwnd)
    if not length:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    GetWindowText(hwnd, buf, length + 1)
    return buf.value


def _get_window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    GetClassName(hwnd, buf, 256)
    return buf.value


def _get_window_pid(hwnd: int) -> int:
    pid = ctypes.c_ulong()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def discover_instances() -> List[WeChatInstance]:
    """
    扫描当前系统中所有运行的微信窗口。

    返回每个微信窗口的句柄、PID、标题（通常是微信昵称）。
    多开微信时会返回多个实例。
    """
    instances = []

    def _enum_callback(hwnd, _):
        if not IsWindowVisible(hwnd):
            return True
        cls = _get_window_class(hwnd)
        if cls in WX_CLASS_NAMES:
            title = _get_window_title(hwnd)
            pid = _get_window_pid(hwnd)
            instances.append(WeChatInstance(
                hwnd=hwnd, pid=pid, title=title,
                wx_name=title,
            ))
        return True

    EnumWindows(EnumWindowsProc(_enum_callback), 0)
    logger.info(f"[AccountMgr] 发现 {len(instances)} 个微信窗口")

    # 关联已绑定的账号
    conn = _get_conn()
    for inst in instances:
        row = conn.execute(
            "SELECT id FROM accounts WHERE hwnd = ? OR (pid = ? AND pid > 0)",
            (inst.hwnd, inst.pid),
        ).fetchone()
        if row:
            inst.bound_account_id = row["id"]

    return instances


# ── wxauto 多实例池 ───────────────────────────────────────────────────────────

_wx_pool: Dict[str, Any] = {}  # account_id → wxauto.WeChat() instance


def get_wx(account_id: str = "default") -> Optional[Any]:
    """获取指定账号的 wxauto 实例"""
    return _wx_pool.get(account_id)


def bind_account(account_id: str, hwnd: int) -> bool:
    """
    将账号绑定到指定的微信窗口。

    通过 UIAutomation 定位到具体窗口句柄，创建 wxauto 连接。
    wxauto 的 WeChat() 默认连接第一个找到的窗口，
    我们通过先置顶目标窗口再初始化来绑定到正确的实例。
    """
    try:
        import uiautomation as uia

        # 找到目标窗口
        ctrl = uia.ControlFromHandle(hwnd)
        if not ctrl:
            logger.warning(f"[AccountMgr] 找不到窗口 hwnd={hwnd}")
            return False

        # 置顶目标窗口以确保 wxauto 连接到它
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)

        try:
            import wxauto as _wxauto
            wx = _wxauto.WeChat()
            _wx_pool[account_id] = wx
        except Exception as e:
            logger.warning(f"[AccountMgr] wxauto 连接失败: {e}")
            return False

        title = _get_window_title(hwnd)
        pid = _get_window_pid(hwnd)

        # 更新数据库
        conn = _get_conn()
        with _lock:
            conn.execute(
                "UPDATE accounts SET hwnd=?, pid=?, wx_name=?, status='connected', last_active=? WHERE id=?",
                (hwnd, pid, title, time.time(), account_id),
            )
            conn.commit()

        logger.info(f"[AccountMgr] 账号 {account_id} 已绑定到微信窗口: {title} (hwnd={hwnd}, pid={pid})")
        return True

    except ImportError:
        logger.warning("[AccountMgr] uiautomation 未安装")
        return False
    except Exception as e:
        logger.error(f"[AccountMgr] 绑定失败: {e}")
        return False


def auto_bind_all() -> Dict[str, str]:
    """
    自动发现所有微信窗口，为未绑定的窗口创建新账号。

    返回 {account_id: wx_name} 映射。
    """
    instances = discover_instances()
    result = {}

    for inst in instances:
        if inst.bound_account_id:
            # 已绑定，重新连接
            bind_account(inst.bound_account_id, inst.hwnd)
            result[inst.bound_account_id] = inst.wx_name
        else:
            # 未绑定，创建新账号
            import uuid
            acct_id = str(uuid.uuid4())[:8]
            acct = WeChatAccount(
                id=acct_id,
                name=inst.wx_name or f"微信-{acct_id}",
                wx_name=inst.wx_name,
                hwnd=inst.hwnd,
                pid=inst.pid,
                is_active=True,
                status="connected",
                created_at=time.time(),
                last_active=time.time(),
            )
            save_account(acct)
            bind_account(acct_id, inst.hwnd)
            result[acct_id] = inst.wx_name

    return result


def disconnect_account(account_id: str):
    """断开账号的微信连接"""
    _wx_pool.pop(account_id, None)
    conn = _get_conn()
    with _lock:
        conn.execute(
            "UPDATE accounts SET status='disconnected', hwnd=0, pid=0 WHERE id=?",
            (account_id,),
        )
        conn.commit()
    logger.info(f"[AccountMgr] 账号 {account_id} 已断开连接")


def get_all_connected() -> List[str]:
    """返回所有已连接的账号ID"""
    return list(_wx_pool.keys())


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_account(acct: WeChatAccount):
    import uuid
    if not acct.id:
        acct.id = str(uuid.uuid4())[:8]
    if not acct.created_at:
        acct.created_at = time.time()

    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO accounts "
            "(id,name,wx_name,avatar_url,hwnd,pid,autoreply_config,moments_config,"
            "is_active,created_at,last_active,notes,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (acct.id, acct.name, acct.wx_name, acct.avatar_url,
             acct.hwnd, acct.pid,
             json.dumps(acct.autoreply_config, ensure_ascii=False),
             json.dumps(acct.moments_config, ensure_ascii=False),
             1 if acct.is_active else 0,
             acct.created_at, acct.last_active, acct.notes, acct.status),
        )
        conn.commit()


def list_accounts() -> List[WeChatAccount]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM accounts ORDER BY last_active DESC").fetchall()
    return [_row_to_acct(r) for r in rows]


def get_account(acct_id: str) -> Optional[WeChatAccount]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (acct_id,)).fetchone()
    return _row_to_acct(row) if row else None


def delete_account(acct_id: str) -> bool:
    disconnect_account(acct_id)
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM accounts WHERE id = ?", (acct_id,))
        conn.commit()
    return True


def ensure_default_account():
    """确保至少有一个默认账号"""
    accts = list_accounts()
    if not accts:
        default = WeChatAccount(
            id="default",
            name="默认账号",
            wx_name="",
            is_active=True,
            created_at=time.time(),
        )
        save_account(default)


def _row_to_acct(row) -> WeChatAccount:
    try:
        ar_cfg = json.loads(row["autoreply_config"] or "{}")
    except Exception:
        ar_cfg = {}
    try:
        m_cfg = json.loads(row["moments_config"] or "{}")
    except Exception:
        m_cfg = {}
    return WeChatAccount(
        id=row["id"], name=row["name"],
        wx_name=row["wx_name"] or "",
        avatar_url=row["avatar_url"] or "",
        hwnd=row["hwnd"] or 0,
        pid=row["pid"] or 0,
        autoreply_config=ar_cfg,
        moments_config=m_cfg,
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        last_active=row["last_active"],
        notes=row["notes"] or "",
        status=row["status"] or "disconnected",
    )
