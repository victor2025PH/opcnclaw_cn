# -*- coding: utf-8 -*-
"""
声纹识别模块 — 通过声音特征识别说话人

技术方案：
  - resemblyzer (d-vector) 提取 256 维声纹嵌入
  - 余弦相似度匹配（阈值 0.75）
  - 每个用户注册 3 句话，取平均 embedding
  - 实时识别：0.5s 音频片段提取 → 匹配最近用户

使用方式：
  encoder = get_speaker_encoder()
  embedding = encoder.encode(audio_array)  # numpy float32, 16kHz
  user_id = identify(embedding)
"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger


# ── 常量 ──────────────────────────────────────────────────────

EMBED_DIM = 40                   # MFCC 特征维度（轻量方案）
MATCH_THRESHOLD = 0.80           # 余弦相似度阈值（MFCC 需要更高阈值）
MIN_AUDIO_SECONDS = 1.0          # 最短音频长度
SAMPLE_RATE = 16000              # 采样率
USERS_DB_FILE = "data/speaker_profiles.json"  # 声纹存储文件
N_MFCC = 40                     # MFCC 系数数
N_FFT = 512                     # FFT 窗口大小
HOP_LENGTH = 160                # 帧移（10ms @ 16kHz）


# ── 轻量声纹提取（MFCC，纯 numpy/scipy，零额外模型）──────────

def extract_embedding(audio: np.ndarray, sr: int = SAMPLE_RATE) -> np.ndarray:
    """从音频提取声纹嵌入（MFCC 均值+方差，40维）

    轻量方案：不需要 torch/resemblyzer/speechbrain，
    纯 numpy 实现，内存占用 <10MB，提取速度 <50ms。
    """
    if len(audio) < int(MIN_AUDIO_SECONDS * sr):
        raise ValueError(f"音频太短（需要至少 {MIN_AUDIO_SECONDS}s）")

    # 归一化
    audio = audio.astype(np.float32)
    if np.max(np.abs(audio)) > 0:
        audio = audio / np.max(np.abs(audio))

    # 预加重
    audio = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])

    # 分帧 + 加窗
    frame_len = N_FFT
    frames = []
    for i in range(0, len(audio) - frame_len, HOP_LENGTH):
        frame = audio[i:i + frame_len] * np.hamming(frame_len)
        frames.append(frame)

    if not frames:
        return np.zeros(N_MFCC, dtype=np.float32)

    frames = np.array(frames)

    # FFT → 功率谱
    power_spectrum = np.abs(np.fft.rfft(frames, n=N_FFT)) ** 2

    # Mel 滤波器组
    n_filters = N_MFCC * 2
    mel_filters = _mel_filterbank(n_filters, N_FFT, sr)
    mel_spectrum = np.dot(power_spectrum, mel_filters.T)
    mel_spectrum = np.where(mel_spectrum == 0, np.finfo(float).eps, mel_spectrum)
    log_mel = np.log(mel_spectrum)

    # DCT → MFCC
    from scipy.fft import dct
    mfcc = dct(log_mel, type=2, axis=1, norm='ortho')[:, :N_MFCC]

    # 取每帧 MFCC 的均值作为声纹嵌入（简单但有效）
    embedding = np.mean(mfcc, axis=0).astype(np.float32)

    # 归一化
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding


def _mel_filterbank(n_filters: int, n_fft: int, sr: int) -> np.ndarray:
    """构建 Mel 滤波器组"""
    low_freq = 0
    high_freq = sr // 2
    low_mel = 2595 * np.log10(1 + low_freq / 700)
    high_mel = 2595 * np.log10(1 + high_freq / 700)
    mel_points = np.linspace(low_mel, high_mel, n_filters + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bins = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    fbank = np.zeros((n_filters, n_fft // 2 + 1))
    for i in range(n_filters):
        for j in range(bins[i], bins[i + 1]):
            fbank[i, j] = (j - bins[i]) / max(bins[i + 1] - bins[i], 1)
        for j in range(bins[i + 1], bins[i + 2]):
            fbank[i, j] = (bins[i + 2] - j) / max(bins[i + 2] - bins[i + 1], 1)
    return fbank


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算余弦相似度"""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ── 用户声纹管理 ─────────────────────────────────────────────

class SpeakerProfile:
    """单个用户的声纹档案"""

    def __init__(self, user_id: str, name: str, avatar: str = "",
                 embedding: np.ndarray = None, preferences: dict = None):
        self.user_id = user_id
        self.name = name
        self.avatar = avatar or "👤"
        self.embedding = embedding if embedding is not None else np.zeros(EMBED_DIM)
        self.preferences = preferences or {}
        self.created_at = time.time()
        self.last_seen = 0.0
        self.match_count = 0

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "avatar": self.avatar,
            "preferences": self.preferences,
            "created_at": round(self.created_at, 1),
            "last_seen": round(self.last_seen, 1),
            "match_count": self.match_count,
            "has_voiceprint": bool(np.any(self.embedding != 0)),
        }

    def to_storage(self) -> dict:
        d = self.to_dict()
        d["embedding"] = self.embedding.tolist()
        return d

    @classmethod
    def from_storage(cls, data: dict) -> "SpeakerProfile":
        emb = np.array(data.get("embedding", [0.0] * EMBED_DIM), dtype=np.float32)
        p = cls(
            user_id=data["user_id"],
            name=data["name"],
            avatar=data.get("avatar", "👤"),
            embedding=emb,
            preferences=data.get("preferences", {}),
        )
        p.created_at = data.get("created_at", time.time())
        p.last_seen = data.get("last_seen", 0.0)
        p.match_count = data.get("match_count", 0)
        return p


class SpeakerManager:
    """声纹用户管理器"""

    MAX_USERS = 20

    def __init__(self):
        self._profiles: Dict[str, SpeakerProfile] = {}
        self._current_user: Optional[str] = None
        self._lock = threading.Lock()
        self._load()

    def _storage_path(self) -> Path:
        p = Path(USERS_DB_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _load(self):
        """从文件加载声纹档案"""
        path = self._storage_path()
        if not path.exists():
            # 创建默认用户
            default = SpeakerProfile("default", "默认用户", "🏠")
            self._profiles["default"] = default
            self._current_user = "default"
            self._save()
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("profiles", []):
                p = SpeakerProfile.from_storage(item)
                self._profiles[p.user_id] = p
            self._current_user = data.get("current_user", "default")
            logger.info(f"[SpeakerID] 已加载 {len(self._profiles)} 个用户声纹")
        except Exception as e:
            logger.warning(f"[SpeakerID] 加载声纹失败: {e}")
            default = SpeakerProfile("default", "默认用户", "🏠")
            self._profiles["default"] = default
            self._current_user = "default"

    def _save(self):
        """保存到文件"""
        try:
            data = {
                "profiles": [p.to_storage() for p in self._profiles.values()],
                "current_user": self._current_user,
                "updated_at": time.time(),
            }
            self._storage_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"[SpeakerID] 保存声纹失败: {e}")

    def register(self, name: str, avatar: str, audio_segments: List[np.ndarray]) -> SpeakerProfile:
        """注册新用户

        Args:
            name: 用户昵称
            avatar: 头像 emoji
            audio_segments: 3 段音频（各 3 秒，float32 16kHz）

        Returns:
            新创建的用户档案
        """
        if len(self._profiles) >= self.MAX_USERS:
            raise ValueError(f"用户数已达上限 ({self.MAX_USERS})")

        # 提取每段音频的 embedding，取平均
        embeddings = []
        for seg in audio_segments:
            emb = extract_embedding(seg)
            embeddings.append(emb)

        avg_embedding = np.mean(embeddings, axis=0)
        avg_embedding = avg_embedding / np.linalg.norm(avg_embedding)  # 归一化

        user_id = f"user_{int(time.time() * 1000) % 100000}"
        profile = SpeakerProfile(
            user_id=user_id,
            name=name,
            avatar=avatar,
            embedding=avg_embedding,
        )

        with self._lock:
            self._profiles[user_id] = profile
            self._save()

        logger.info(f"[SpeakerID] 新用户注册: {name} ({user_id})")
        return profile

    def identify(self, audio: np.ndarray) -> Tuple[Optional[str], float]:
        """识别说话人

        Args:
            audio: float32 音频数组 (至少 1 秒)

        Returns:
            (user_id, similarity) 或 (None, 0.0)
        """
        try:
            query_emb = extract_embedding(audio)
        except ValueError:
            return None, 0.0

        best_id = None
        best_sim = 0.0

        with self._lock:
            for uid, profile in self._profiles.items():
                if not np.any(profile.embedding != 0):
                    continue  # 跳过没有声纹的用户
                sim = cosine_similarity(query_emb, profile.embedding)
                if sim > best_sim:
                    best_sim = sim
                    best_id = uid

        if best_sim >= MATCH_THRESHOLD and best_id:
            with self._lock:
                self._profiles[best_id].last_seen = time.time()
                self._profiles[best_id].match_count += 1
                self._current_user = best_id
                self._save()
            logger.debug(f"[SpeakerID] 识别: {best_id} (相似度={best_sim:.3f})")
            return best_id, best_sim

        return None, best_sim

    def switch_user(self, user_id: str) -> bool:
        """手动切换用户"""
        with self._lock:
            if user_id not in self._profiles:
                return False
            self._current_user = user_id
            self._profiles[user_id].last_seen = time.time()
            self._save()
        return True

    def get_current(self) -> Optional[SpeakerProfile]:
        with self._lock:
            return self._profiles.get(self._current_user)

    def get_current_id(self) -> str:
        return self._current_user or "default"

    def list_users(self) -> List[dict]:
        with self._lock:
            return [p.to_dict() for p in self._profiles.values()]

    def update_user(self, user_id: str, name: str = None, avatar: str = None,
                    preferences: dict = None) -> bool:
        with self._lock:
            p = self._profiles.get(user_id)
            if not p:
                return False
            if name is not None:
                p.name = name
            if avatar is not None:
                p.avatar = avatar
            if preferences is not None:
                p.preferences.update(preferences)
            self._save()
        return True

    def delete_user(self, user_id: str) -> bool:
        if user_id == "default":
            return False  # 不能删默认用户
        with self._lock:
            if user_id not in self._profiles:
                return False
            del self._profiles[user_id]
            if self._current_user == user_id:
                self._current_user = "default"
            self._save()
        return True


# ── 全局单例 ──────────────────────────────────────────────────

_manager: Optional[SpeakerManager] = None


def get_speaker_manager() -> SpeakerManager:
    global _manager
    if _manager is None:
        _manager = SpeakerManager()
    return _manager
