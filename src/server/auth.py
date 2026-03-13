"""
Authentication, API key management, and rate limiting.

Sliding-window rate limiting for both API keys and IP addresses.
"""

import collections
import hashlib
import os
import secrets
import time
import threading
from typing import Optional, Dict, Any, Deque
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger


@dataclass
class APIKey:
    """API key with metadata and limits."""
    key_id: str
    key_hash: str
    name: str
    created_at: datetime

    rate_limit_per_minute: int = 60
    monthly_minutes: Optional[int] = None

    minutes_used: float = 0.0
    last_request_at: Optional[datetime] = None
    request_count_this_minute: int = 0

    features: Dict[str, bool] = field(default_factory=lambda: {
        "continuous_mode": True,
        "voice_cloning": False,
        "priority_queue": False,
    })

    active: bool = True
    tier: str = "free"


class SlidingWindowLimiter:
    """
    Sliding-window rate limiter.
    Tracks timestamps of recent requests in a deque; evicts entries older than
    the window. Thread-safe via a simple lock.
    """

    def __init__(self, default_limit: int = 120, window_seconds: float = 60.0):
        self._windows: Dict[str, Deque[float]] = {}
        self._limits: Dict[str, int] = {}
        self._default_limit = default_limit
        self._window = window_seconds
        self._lock = threading.Lock()

    def set_limit(self, key: str, limit: int):
        with self._lock:
            self._limits[key] = limit

    def allow(self, key: str, limit: int = 0) -> bool:
        now = time.monotonic()
        cap = limit or self._limits.get(key, self._default_limit)
        with self._lock:
            dq = self._windows.get(key)
            if dq is None:
                dq = collections.deque()
                self._windows[key] = dq
            cutoff = now - self._window
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= cap:
                return False
            dq.append(now)
            return True

    def remaining(self, key: str, limit: int = 0) -> int:
        now = time.monotonic()
        cap = limit or self._limits.get(key, self._default_limit)
        with self._lock:
            dq = self._windows.get(key)
            if not dq:
                return cap
            cutoff = now - self._window
            while dq and dq[0] < cutoff:
                dq.popleft()
            return max(0, cap - len(dq))

    def cleanup(self, max_idle: float = 300):
        """Remove keys that have had no requests in max_idle seconds."""
        cutoff = time.monotonic() - max_idle
        with self._lock:
            stale = [k for k, dq in self._windows.items() if not dq or dq[-1] < cutoff]
            for k in stale:
                del self._windows[k]


ip_limiter = SlidingWindowLimiter(
    default_limit=int(os.environ.get("OPENCLAW_IP_RATE_LIMIT", "120")),
    window_seconds=60.0,
)

key_limiter = SlidingWindowLimiter(default_limit=60, window_seconds=60.0)


class TokenManager:
    """
    Manage API tokens for voice connections.
    
    In production, this would be backed by a database.
    For MVP, we use in-memory storage + env vars.
    """
    
    def __init__(self):
        self._keys: Dict[str, APIKey] = {}
        self._key_to_id: Dict[str, str] = {}
    
    def generate_key(
        self,
        name: str,
        tier: str = "free",
        rate_limit: int = 60,
        monthly_minutes: Optional[int] = None,
    ) -> tuple[str, APIKey]:
        key_id = secrets.token_hex(8)
        plaintext_key = f"ocv_{secrets.token_urlsafe(32)}"
        key_hash = self._hash_key(plaintext_key)
        
        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            created_at=datetime.now(tz=None),
            rate_limit_per_minute=rate_limit,
            monthly_minutes=monthly_minutes,
            tier=tier,
        )
        
        self._keys[key_id] = api_key
        self._key_to_id[key_hash] = key_id
        key_limiter.set_limit(f"key:{key_id}", rate_limit)
        
        logger.info(f"Generated API key: {key_id} ({name}, tier={tier})")
        return plaintext_key, api_key
    
    def validate_key(self, plaintext_key: str) -> Optional[APIKey]:
        if not plaintext_key or not plaintext_key.startswith("ocv_"):
            return None
        key_hash = self._hash_key(plaintext_key)
        key_id = self._key_to_id.get(key_hash)
        if not key_id:
            return None
        api_key = self._keys.get(key_id)
        if not api_key or not api_key.active:
            return None
        return api_key
    
    def check_rate_limit(self, api_key: APIKey) -> bool:
        """Sliding-window rate limit check for an API key."""
        return key_limiter.allow(f"key:{api_key.key_id}", api_key.rate_limit_per_minute)

    @staticmethod
    def check_ip_rate_limit(ip: str) -> bool:
        """Sliding-window rate limit check per IP address."""
        return ip_limiter.allow(f"ip:{ip}")
    
    def check_monthly_quota(self, api_key: APIKey, minutes: float = 0) -> bool:
        if api_key.monthly_minutes is None:
            return True
        return (api_key.minutes_used + minutes) <= api_key.monthly_minutes
    
    def record_usage(self, api_key: APIKey, minutes: float):
        api_key.minutes_used += minutes
        logger.debug(f"Key {api_key.key_id}: used {minutes:.2f} min, total {api_key.minutes_used:.2f}")
    
    def get_usage(self, api_key: APIKey) -> Dict[str, Any]:
        return {
            "key_id": api_key.key_id,
            "name": api_key.name,
            "tier": api_key.tier,
            "minutes_used": round(api_key.minutes_used, 2),
            "monthly_limit": api_key.monthly_minutes,
            "rate_limit": api_key.rate_limit_per_minute,
            "remaining_this_minute": key_limiter.remaining(
                f"key:{api_key.key_id}", api_key.rate_limit_per_minute),
            "features": api_key.features,
        }
    
    def revoke_key(self, key_id: str) -> bool:
        if key_id in self._keys:
            self._keys[key_id].active = False
            logger.info(f"Revoked API key: {key_id}")
            return True
        return False
    
    def _hash_key(self, plaintext_key: str) -> str:
        return hashlib.sha256(plaintext_key.encode()).hexdigest()


token_manager = TokenManager()


def load_keys_from_env():
    master_key = os.getenv("OPENCLAW_MASTER_KEY")
    if master_key:
        key_hash = token_manager._hash_key(master_key)
        api_key = APIKey(
            key_id="master",
            key_hash=key_hash,
            name="Master Key",
            created_at=datetime.now(tz=None),
            rate_limit_per_minute=1000,
            monthly_minutes=None,
            tier="enterprise",
        )
        api_key.features = {
            "continuous_mode": True,
            "voice_cloning": True,
            "priority_queue": True,
        }
        token_manager._keys["master"] = api_key
        token_manager._key_to_id[key_hash] = "master"
        key_limiter.set_limit("key:master", 1000)
        logger.info("Loaded master API key from environment")


PRICING_TIERS = {
    "free": {
        "monthly_minutes": 60,
        "rate_limit": 30,
        "price": 0,
        "features": ["continuous_mode"],
    },
    "pro": {
        "monthly_minutes": 500,
        "rate_limit": 120,
        "price": 29,
        "features": ["continuous_mode", "voice_cloning"],
    },
    "enterprise": {
        "monthly_minutes": None,
        "rate_limit": 500,
        "price": 99,
        "features": ["continuous_mode", "voice_cloning", "priority_queue"],
    },
}
