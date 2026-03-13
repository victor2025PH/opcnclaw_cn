"""
微信公众号桥接 — 接收/回复消息，支持文字和语音。

接入方式：
  1. 在微信公众平台 (mp.weixin.qq.com) 注册公众号
  2. 设置 → 开发 → 基本配置 → 获取 AppID / AppSecret
  3. 设置 → 开发 → 基本配置 → 服务器配置：
     URL = http://你的域名:8766/wechat/callback
     Token = 自定义字符串
     EncodingAESKey = 自动生成
  4. 在 OpenClaw 设置中填入以上配置

消息流程：
  用户发送消息 → 微信服务器 → OpenClaw HTTP 回调
  → AI 生成回复 → 被动回复 / 客服接口主动推送
"""

import base64
import hashlib
import struct
import time
import xml.etree.ElementTree as ET
from typing import Optional

import httpx
from loguru import logger

from .manager import BaseBridge


class WeChatMPBridge(BaseBridge):
    """
    微信公众号（订阅号/服务号）桥接。

    支持：
    - 文本消息接收与回复
    - 语音消息接收（自动转文字，需开通语音识别功能）
    - 图片消息接收
    - 通过客服接口主动推送消息
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        token: str,
        encoding_aes_key: str = "",
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.token = token
        self.encoding_aes_key = encoding_aes_key
        self._access_token: Optional[str] = None
        self._token_expires: float = 0

    # ------------------------------------------------------------------
    #  Token 管理
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires - 300:
            return self._access_token

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.weixin.qq.com/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self.app_id,
                    "secret": self.app_secret,
                },
            )
            data = resp.json()
            if "access_token" in data:
                self._access_token = data["access_token"]
                self._token_expires = time.time() + data.get(
                    "expires_in", 7200)
                return self._access_token
            else:
                logger.error(f"WeChat token error: {data}")
                raise Exception(
                    f"获取 access_token 失败: {data.get('errmsg', '')}")

    # ------------------------------------------------------------------
    #  消息验证（服务器配置验证）
    # ------------------------------------------------------------------

    def verify_signature(
        self, signature: str, timestamp: str, nonce: str
    ) -> bool:
        items = sorted([self.token, timestamp, nonce])
        sha1 = hashlib.sha1("".join(items).encode()).hexdigest()
        return sha1 == signature

    # ------------------------------------------------------------------
    #  AES 加密消息解密（安全模式）
    # ------------------------------------------------------------------

    def decrypt_message(
        self, msg_encrypt: str, msg_signature: str,
        timestamp: str, nonce: str
    ) -> Optional[str]:
        if not self.encoding_aes_key:
            return None
        try:
            from cryptography.hazmat.primitives.ciphers import (
                Cipher, algorithms, modes)
            from cryptography.hazmat.backends import default_backend

            items = sorted([self.token, timestamp, nonce, msg_encrypt])
            check_sha1 = hashlib.sha1("".join(items).encode()).hexdigest()
            if check_sha1 != msg_signature:
                logger.error("WeChat AES: signature mismatch")
                return None

            aes_key = base64.b64decode(self.encoding_aes_key + "=")
            iv = aes_key[:16]

            cipher = Cipher(
                algorithms.AES(aes_key),
                modes.CBC(iv),
                backend=default_backend())
            decryptor = cipher.decryptor()
            encrypted = base64.b64decode(msg_encrypt)
            decrypted = decryptor.update(encrypted) + decryptor.finalize()

            pad_len = decrypted[-1]
            content = decrypted[:-pad_len]

            xml_len = struct.unpack("!I", content[16:20])[0]
            xml_content = content[20:20 + xml_len].decode("utf-8")
            return xml_content

        except ImportError:
            logger.warning(
                "WeChat AES: cryptography not installed, "
                "run: pip install cryptography")
            return None
        except Exception as e:
            logger.error(f"WeChat AES decrypt error: {e}")
            return None

    def encrypt_message(self, reply_xml: str, nonce: str) -> Optional[str]:
        if not self.encoding_aes_key:
            return None
        try:
            import os as _os
            from cryptography.hazmat.primitives.ciphers import (
                Cipher, algorithms, modes)
            from cryptography.hazmat.backends import default_backend

            aes_key = base64.b64decode(self.encoding_aes_key + "=")
            iv = aes_key[:16]

            reply_bytes = reply_xml.encode("utf-8")
            random_bytes = _os.urandom(16)
            text_len = struct.pack("!I", len(reply_bytes))
            app_id_bytes = self.app_id.encode("utf-8")

            plaintext = random_bytes + text_len + reply_bytes + app_id_bytes

            pad_n = 32 - (len(plaintext) % 32)
            plaintext += bytes([pad_n] * pad_n)

            cipher = Cipher(
                algorithms.AES(aes_key),
                modes.CBC(iv),
                backend=default_backend())
            encryptor = cipher.encryptor()
            encrypted = encryptor.update(plaintext) + encryptor.finalize()
            encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

            timestamp = str(int(time.time()))
            items = sorted([self.token, timestamp, nonce, encrypted_b64])
            signature = hashlib.sha1("".join(items).encode()).hexdigest()

            return (
                f"<xml>"
                f"<Encrypt><![CDATA[{encrypted_b64}]]></Encrypt>"
                f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
                f"<TimeStamp>{timestamp}</TimeStamp>"
                f"<Nonce><![CDATA[{nonce}]]></Nonce>"
                f"</xml>"
            )
        except ImportError:
            logger.warning("WeChat AES: cryptography not installed")
            return None
        except Exception as e:
            logger.error(f"WeChat AES encrypt error: {e}")
            return None

    # ------------------------------------------------------------------
    #  消息解析
    # ------------------------------------------------------------------

    @staticmethod
    def parse_message(xml_body: str) -> dict:
        try:
            root = ET.fromstring(xml_body)
            msg = {
                "to_user": root.findtext("ToUserName", ""),
                "from_user": root.findtext("FromUserName", ""),
                "create_time": root.findtext("CreateTime", ""),
                "msg_type": root.findtext("MsgType", ""),
                "msg_id": root.findtext("MsgId", ""),
            }
            msg_type = msg["msg_type"]

            if msg_type == "text":
                msg["content"] = root.findtext("Content", "")
            elif msg_type == "voice":
                msg["media_id"] = root.findtext("MediaId", "")
                msg["format"] = root.findtext("Format", "")
                msg["recognition"] = root.findtext("Recognition", "")
            elif msg_type == "image":
                msg["pic_url"] = root.findtext("PicUrl", "")
                msg["media_id"] = root.findtext("MediaId", "")
            elif msg_type == "event":
                msg["event"] = root.findtext("Event", "")
                msg["event_key"] = root.findtext("EventKey", "")

            return msg
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return {}

    # ------------------------------------------------------------------
    #  被动回复
    # ------------------------------------------------------------------

    @staticmethod
    def build_text_reply(from_user: str, to_user: str, content: str) -> str:
        return (
            f"<xml>"
            f"<ToUserName><![CDATA[{from_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{to_user}]]></FromUserName>"
            f"<CreateTime>{int(time.time())}</CreateTime>"
            f"<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{content}]]></Content>"
            f"</xml>"
        )

    # ------------------------------------------------------------------
    #  主动推送（客服接口）
    # ------------------------------------------------------------------

    async def send_text(self, text: str, title: str = "",
                        to_user: str = "") -> bool:
        if not to_user:
            logger.warning("WeChat MP: no target user for send_text")
            return False
        try:
            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.weixin.qq.com/cgi-bin/message/"
                    "custom/send",
                    params={"access_token": token},
                    json={
                        "touser": to_user,
                        "msgtype": "text",
                        "text": {"content": text},
                    },
                )
                data = resp.json()
                if data.get("errcode", 0) != 0:
                    logger.error(f"WeChat send error: {data}")
                    return False
                return True
        except Exception as e:
            logger.error(f"WeChat MP send failed: {e}")
            return False

    async def send_markdown(self, content: str, title: str = "",
                            to_user: str = "") -> bool:
        return await self.send_text(content, title, to_user)

    # ------------------------------------------------------------------
    #  语音消息回复 — 先上传临时素材，再以语音消息推送
    # ------------------------------------------------------------------

    async def upload_voice(self, audio_bytes: bytes,
                           filename: str = "reply.mp3") -> Optional[str]:
        try:
            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.weixin.qq.com/cgi-bin/media/upload",
                    params={"access_token": token, "type": "voice"},
                    files={"media": (filename, audio_bytes,
                                     "audio/mpeg")},
                )
                data = resp.json()
                if "media_id" in data:
                    logger.info(f"WeChat voice upload OK: {data['media_id']}")
                    return data["media_id"]
                logger.error(f"WeChat voice upload error: {data}")
        except Exception as e:
            logger.error(f"WeChat voice upload failed: {e}")
        return None

    async def send_voice(self, audio_bytes: bytes,
                         to_user: str = "") -> bool:
        if not to_user:
            return False
        media_id = await self.upload_voice(audio_bytes)
        if not media_id:
            return False
        try:
            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.weixin.qq.com/cgi-bin/message/"
                    "custom/send",
                    params={"access_token": token},
                    json={
                        "touser": to_user,
                        "msgtype": "voice",
                        "voice": {"media_id": media_id},
                    },
                )
                data = resp.json()
                if data.get("errcode", 0) != 0:
                    logger.error(f"WeChat voice send error: {data}")
                    return False
                return True
        except Exception as e:
            logger.error(f"WeChat voice send failed: {e}")
            return False

    @staticmethod
    def build_voice_reply(from_user: str, to_user: str,
                          media_id: str) -> str:
        return (
            f"<xml>"
            f"<ToUserName><![CDATA[{from_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{to_user}]]></FromUserName>"
            f"<CreateTime>{int(time.time())}</CreateTime>"
            f"<MsgType><![CDATA[voice]]></MsgType>"
            f"<Voice><MediaId><![CDATA[{media_id}]]></MediaId></Voice>"
            f"</xml>"
        )

    # ------------------------------------------------------------------
    #  语音消息下载
    # ------------------------------------------------------------------

    async def download_media(self, media_id: str) -> Optional[bytes]:
        try:
            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    "https://api.weixin.qq.com/cgi-bin/media/get",
                    params={
                        "access_token": token,
                        "media_id": media_id,
                    },
                )
                if resp.status_code == 200 and \
                        "application/json" not in resp.headers.get(
                            "content-type", ""):
                    return resp.content
                logger.warning(
                    f"WeChat media download failed: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"WeChat media error: {e}")
        return None
