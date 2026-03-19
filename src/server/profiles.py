# -*- coding: utf-8 -*-
"""
Multi-member profile system — family/work environment with isolated agents.

Each profile has:
  - Independent memory (via session="profile:{uuid}")
  - Custom system prompt / persona
  - Preferred TTS voice (Edge TTS or cloned)
  - Age-based content filtering
  - Environment tagging (family / work)
"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from . import db as _db

FAMILY_PRESETS = [
    {
        "name": "爸爸",
        "avatar": "👨",
        "environment": "family",
        "age_group": "adult",
        "system_prompt": (
            "你是一个智能家庭助手，正在和家里的男主人对话。"
            "他喜欢科技新闻、体育和汽车。回答风格：简洁、直接、有条理。"
            "可以讨论新闻、天气、日程安排、家庭事务等。"
        ),
        "voice_id": "zh-CN-YunjianNeural",
        "preferences": {"interests": ["科技", "体育", "汽车"], "style": "concise"},
    },
    {
        "name": "妈妈",
        "avatar": "👩",
        "environment": "family",
        "age_group": "adult",
        "system_prompt": (
            "你是一个智能家庭助手，正在和家里的女主人对话。"
            "她喜欢美食、养生、教育话题。回答风格：温柔、详细、关心家人健康。"
            "可以推荐菜谱、健康建议、育儿知识等。"
        ),
        "voice_id": "zh-CN-XiaohanNeural",
        "preferences": {"interests": ["美食", "养生", "教育"], "style": "warm"},
    },
    {
        "name": "孩子",
        "avatar": "👦",
        "environment": "family",
        "age_group": "child",
        "system_prompt": (
            "你是一个儿童智能伙伴，正在和一个小朋友对话。"
            "用简单易懂的语言，多用生动有趣的比喻。"
            "可以讲故事、回答问题、辅导学习、玩知识问答游戏。"
            "绝对不允许讨论暴力、恐怖、成人话题。"
            "晚上9点后要提醒小朋友该睡觉了。"
        ),
        "voice_id": "zh-CN-XiaoyiNeural",
        "preferences": {"interests": ["故事", "学习", "游戏"], "style": "playful", "safe_mode": True},
    },
    {
        "name": "老人",
        "avatar": "👴",
        "environment": "family",
        "age_group": "elder",
        "system_prompt": (
            "你是一个智能家庭助手，正在和家里的老人对话。"
            "用简洁、清晰、大白话的方式回答，避免专业术语。"
            "语速要慢，内容要简短。多关心健康，提醒吃药、散步。"
            "可以聊天气、新闻、养生、戏曲等话题。"
        ),
        "voice_id": "zh-CN-YunyangNeural",
        "preferences": {"interests": ["养生", "新闻", "戏曲"], "style": "simple_slow"},
    },
]

WORK_PRESETS = [
    {
        "name": "通用助理",
        "avatar": "💼",
        "environment": "work",
        "age_group": "adult",
        "system_prompt": (
            "你是一个高效的工作助理。"
            "擅长文档写作、翻译润色、邮件撰写、日程管理。"
            "回答专业、条理清晰、可以使用Markdown格式。"
        ),
        "voice_id": "zh-CN-YunxiNeural",
        "preferences": {"interests": ["办公", "写作", "翻译"], "style": "professional"},
    },
    {
        "name": "编程助手",
        "avatar": "💻",
        "environment": "work",
        "age_group": "adult",
        "system_prompt": (
            "你是一个资深编程助手。"
            "擅长代码编写、bug排查、技术架构设计、API文档撰写。"
            "回答要包含代码示例，使用Markdown格式。"
        ),
        "voice_id": "zh-CN-YunxiNeural",
        "preferences": {"interests": ["编程", "技术", "架构"], "style": "technical"},
    },
    {
        "name": "会议助手",
        "avatar": "📋",
        "environment": "work",
        "age_group": "adult",
        "system_prompt": (
            "你是一个会议助手。"
            "擅长整理会议纪要、提取行动项、总结讨论要点。"
            "输出格式清晰，用列表和标题组织内容。"
        ),
        "voice_id": "zh-CN-YunyangNeural",
        "preferences": {"interests": ["会议", "管理", "总结"], "style": "structured"},
    },
]

ALL_PRESETS = {
    "family": FAMILY_PRESETS,
    "work": WORK_PRESETS,
}


def _get_conn():
    return _db.get_conn("main")


def _row_to_dict(row) -> dict:
    d = dict(row)
    if "preferences" in d and isinstance(d["preferences"], str):
        try:
            d["preferences"] = json.loads(d["preferences"])
        except (json.JSONDecodeError, TypeError):
            d["preferences"] = {}
    return d


# ─────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────

def list_profiles(environment: Optional[str] = None) -> List[dict]:
    conn = _get_conn()
    if environment:
        rows = conn.execute(
            "SELECT * FROM profiles WHERE environment = ? ORDER BY sort_order ASC, is_active DESC, created_at",
            (environment,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM profiles ORDER BY sort_order ASC, is_active DESC, created_at"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_profile(profile_id: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_active_profile() -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE is_active = 1").fetchone()
    return _row_to_dict(row) if row else None


def create_profile(
    name: str,
    avatar: str = "👤",
    environment: str = "family",
    system_prompt: str = "",
    voice_id: str = "zh-CN-XiaoxiaoNeural",
    clone_voice_path: str = "",
    wake_word: str = "",
    age_group: str = "adult",
    preferences: Optional[dict] = None,
) -> dict:
    profile_id = str(uuid.uuid4())[:8]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefs = json.dumps(preferences or {}, ensure_ascii=False)

    conn = _get_conn()
    conn.execute(
        """INSERT INTO profiles
           (id, name, avatar, environment, system_prompt, voice_id,
            clone_voice_path, wake_word, age_group, preferences, created_at, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (profile_id, name, avatar, environment, system_prompt, voice_id,
         clone_voice_path, wake_word, age_group, prefs, now),
    )
    conn.commit()
    logger.info(f"Profile created: {name} ({profile_id}) env={environment}")
    return get_profile(profile_id)


def create_from_preset(preset_name: str, environment: str = "family") -> Optional[dict]:
    presets = ALL_PRESETS.get(environment, [])
    preset = next((p for p in presets if p["name"] == preset_name), None)
    if not preset:
        return None
    return create_profile(
        name=preset["name"],
        avatar=preset["avatar"],
        environment=preset["environment"],
        system_prompt=preset["system_prompt"],
        voice_id=preset["voice_id"],
        age_group=preset["age_group"],
        preferences=preset.get("preferences"),
    )


def update_profile(profile_id: str, **kwargs) -> Optional[dict]:
    allowed = {
        "name", "avatar", "environment", "system_prompt", "voice_id",
        "clone_voice_path", "wake_word", "age_group", "preferences", "sort_order",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return get_profile(profile_id)

    if "preferences" in updates and isinstance(updates["preferences"], dict):
        updates["preferences"] = json.dumps(updates["preferences"], ensure_ascii=False)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [profile_id]

    conn = _get_conn()
    conn.execute(f"UPDATE profiles SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return get_profile(profile_id)


def delete_profile(profile_id: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    conn.commit()
    if cur.rowcount > 0:
        logger.info(f"Profile deleted: {profile_id}")
        return True
    return False


def activate_profile(profile_id: str) -> Optional[dict]:
    conn = _get_conn()
    conn.execute("UPDATE profiles SET is_active = 0")
    conn.execute("UPDATE profiles SET is_active = 1 WHERE id = ?", (profile_id,))
    conn.commit()
    profile = get_profile(profile_id)
    if profile:
        logger.info(f"Profile activated: {profile['name']} ({profile_id})")
    return profile


def get_session_id(profile_id: str) -> str:
    """Return the memory session string for a profile."""
    return f"profile:{profile_id}"


def get_presets(environment: Optional[str] = None) -> dict:
    if environment:
        return {environment: ALL_PRESETS.get(environment, [])}
    return ALL_PRESETS


# ─────────────────────────────────────────────────
# Interest learning
# ─────────────────────────────────────────────────

TOPIC_KEYWORDS = {
    "编程": ["代码", "python", "java", "编程", "bug", "api", "函数", "变量", "git", "数据库"],
    "科技": ["人工智能", "ai", "芯片", "5g", "机器人", "算法", "大模型", "区块链"],
    "美食": ["菜谱", "做菜", "烹饪", "食材", "餐厅", "好吃", "美食", "烘焙", "火锅"],
    "养生": ["健康", "养生", "中医", "穴位", "锻炼", "血压", "减肥", "睡眠", "维生素"],
    "教育": ["学习", "考试", "作业", "数学", "英语", "物理", "化学", "历史", "地理"],
    "游戏": ["游戏", "王者", "原神", "steam", "手游", "电竞", "通关", "装备"],
    "音乐": ["音乐", "歌曲", "吉他", "钢琴", "演唱会", "歌手", "歌词"],
    "体育": ["足球", "篮球", "跑步", "健身", "奥运", "比赛", "球队", "运动"],
    "旅行": ["旅行", "旅游", "景点", "机票", "酒店", "攻略", "自驾", "出行"],
    "影视": ["电影", "电视剧", "综艺", "动漫", "剧情", "演员", "导演"],
    "工作": ["工作", "项目", "会议", "报告", "管理", "ppt", "excel", "文档", "邮件"],
    "写作": ["写作", "文章", "小说", "文案", "润色", "翻译", "论文"],
    "理财": ["理财", "股票", "基金", "投资", "收入", "存款", "保险", "房贷"],
    "育儿": ["孩子", "宝宝", "育儿", "幼儿园", "辅食", "疫苗", "亲子"],
    "宠物": ["猫", "狗", "宠物", "猫粮", "狗粮", "铲屎官", "喵", "汪"],
}


def learn_interests(profile_id: str, text: str) -> Optional[dict]:
    """Extract topic keywords from text and merge into profile preferences."""
    if not text or len(text) < 5:
        return None

    lower = text.lower()
    found = set()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            found.add(topic)

    if not found:
        return None

    p = get_profile(profile_id)
    if not p:
        return None

    prefs = p.get("preferences", {})
    if isinstance(prefs, str):
        try:
            prefs = json.loads(prefs)
        except (json.JSONDecodeError, TypeError):
            prefs = {}

    existing = set(prefs.get("interests", []))
    merged = list(existing | found)[:20]
    prefs["interests"] = merged

    update_profile(profile_id, preferences=prefs)
    return prefs


def init_default_profiles():
    """Create default profiles if none exist (first run)."""
    existing = list_profiles()
    if existing:
        return
    env = (Path("data") / ".env_mode").read_text().strip() if (Path("data") / ".env_mode").exists() else "family"
    presets = ALL_PRESETS.get(env, FAMILY_PRESETS)
    for i, preset in enumerate(presets):
        p = create_profile(
            name=preset["name"],
            avatar=preset["avatar"],
            environment=preset["environment"],
            system_prompt=preset["system_prompt"],
            voice_id=preset["voice_id"],
            age_group=preset["age_group"],
            preferences=preset.get("preferences"),
        )
        if i == 0 and p:
            activate_profile(p["id"])
    logger.info(f"Default profiles created for env={env}")
