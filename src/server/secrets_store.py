"""
Sensitive data encryption for config files.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256).
The machine key is derived from a combination of hostname + username,
giving per-machine binding without requiring a separate keyfile.
"""

import base64
import hashlib
import os
import platform
from pathlib import Path
from typing import Optional

from loguru import logger


def _derive_machine_key() -> bytes:
    """Derive a stable 32-byte key from machine-specific attributes."""
    raw = f"{platform.node()}:{os.environ.get('USERNAME', os.environ.get('USER', 'openclaw'))}"
    salt = b"openclaw-secrets-v1"
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt, iterations=100_000)
    return base64.urlsafe_b64encode(dk[:32])


_FERNET = None


def _get_fernet():
    global _FERNET
    if _FERNET is None:
        try:
            from cryptography.fernet import Fernet
            _FERNET = Fernet(_derive_machine_key())
        except ImportError:
            _FERNET = None
            logger.debug("cryptography not installed, secrets stored in plaintext")
    return _FERNET


_PREFIX = "ENC:"


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext value. Returns 'ENC:<base64>' or plaintext if crypto unavailable."""
    if not plaintext or plaintext.startswith(_PREFIX):
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext
    try:
        token = f.encrypt(plaintext.encode())
        return _PREFIX + token.decode()
    except Exception as e:
        logger.warning(f"Encryption failed: {e}")
        return plaintext


def decrypt_value(stored: str) -> str:
    """Decrypt an 'ENC:...' value. Returns plaintext on failure or if not encrypted."""
    if not stored or not stored.startswith(_PREFIX):
        return stored
    f = _get_fernet()
    if f is None:
        return stored[len(_PREFIX):]
    try:
        token = stored[len(_PREFIX):].encode()
        return f.decrypt(token).decode()
    except Exception as e:
        logger.warning(f"Decryption failed (wrong machine?): {e}")
        return stored[len(_PREFIX):]


def is_encrypted(value: str) -> bool:
    return value.startswith(_PREFIX) if value else False


_SENSITIVE_KEYS = {
    "openai_api_key", "api_key", "app_secret", "token", "encoding_aes_key",
    "api_token", "master_key", "ha_token", "dashscope_api_key",
    "zhipu_vision_api_key", "gateway_token",
}


def protect_config(config_path: str = "config.ini") -> int:
    """
    Scan config.ini and encrypt any plaintext sensitive values in-place.
    Returns count of values encrypted.
    """
    import configparser

    path = Path(config_path)
    if not path.exists():
        return 0

    cfg = configparser.ConfigParser()
    cfg.read(str(path), encoding="utf-8")

    count = 0
    for section in cfg.sections():
        for key, val in cfg.items(section):
            if key in _SENSITIVE_KEYS and val and not is_encrypted(val):
                cfg.set(section, key, encrypt_value(val))
                count += 1

    if count > 0:
        with open(str(path), "w", encoding="utf-8") as fp:
            cfg.write(fp)
        logger.info(f"Encrypted {count} sensitive values in {config_path}")

    return count


def read_config_secret(config_path: str, section: str, key: str, fallback: str = "") -> str:
    """Read a config value, decrypting transparently if needed."""
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")
    raw = cfg.get(section, key, fallback=fallback)
    return decrypt_value(raw) if raw else fallback
