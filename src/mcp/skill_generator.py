"""
Prompt-based skill generator.

Lets users create new skills from natural language descriptions in ~5 seconds,
generating _meta.json + system_injection without any code.
"""

import json
import time
from pathlib import Path
from typing import Optional

from loguru import logger

SKILLS_ROOT = Path(__file__).parent.parent.parent / "skills"
USER_SKILLS_DIR = SKILLS_ROOT / "99_user_created"


def ensure_user_skills_dir():
    USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    init = USER_SKILLS_DIR / "__init__.py"
    if not init.exists():
        init.write_text("")
    meta = USER_SKILLS_DIR / "_meta.json"
    if not meta.exists():
        meta.write_text(json.dumps({
            "category": "user_created",
            "name_zh": "用户自建技能",
            "name_en": "User Created Skills",
            "skills": [],
        }, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_skill(
    description: str,
    name: Optional[str] = None,
    trigger_words: Optional[list] = None,
) -> dict:
    """
    Generate a prompt-type skill from a natural language description.

    Returns the skill dict that was added to _meta.json.
    """
    ensure_user_skills_dir()

    skill_id = f"user_{int(time.time())}"
    skill_name = name or description[:20].strip()

    if not trigger_words:
        trigger_words = _extract_triggers(description)

    system_injection = (
        f"你现在是一个专门的助手，专注于以下任务：\n\n"
        f"{description}\n\n"
        f"请根据用户的具体请求，提供专业、准确、有帮助的回答。"
    )

    skill_data = {
        "id": skill_id,
        "name_zh": skill_name,
        "name_en": skill_id,
        "category": "user_created",
        "description": description,
        "trigger_words": trigger_words,
        "examples": [description],
        "type": "prompt",
        "system_injection": system_injection,
        "preinstalled": False,
        "safe": True,
        "needs_network": False,
        "params": [],
    }

    meta_path = USER_SKILLS_DIR / "_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {"category": "user_created", "skills": []}

    meta.setdefault("skills", []).append(skill_data)
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    _update_index(skill_data)

    logger.info(f"Skill generated: {skill_id} — {skill_name}")
    return skill_data


def delete_skill(skill_id: str) -> bool:
    meta_path = USER_SKILLS_DIR / "_meta.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        before = len(meta.get("skills", []))
        meta["skills"] = [
            s for s in meta.get("skills", []) if s["id"] != skill_id]
        if len(meta["skills"]) < before:
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8")
            logger.info(f"Skill deleted: {skill_id}")
            return True
    except Exception as e:
        logger.error(f"Delete skill failed: {e}")
    return False


def list_user_skills() -> list:
    meta_path = USER_SKILLS_DIR / "_meta.json"
    if not meta_path.exists():
        return []
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta.get("skills", [])
    except Exception:
        return []


def _extract_triggers(desc: str) -> list:
    try:
        import jieba
        words = list(jieba.cut(desc))
        triggers = [w for w in words if len(w) >= 2][:5]
        return triggers if triggers else [desc[:10]]
    except ImportError:
        return [desc[:10], desc[:6]]


def _update_index(skill: dict):
    index_path = SKILLS_ROOT / "index.json"
    if not index_path.exists():
        return
    try:
        idx = json.loads(index_path.read_text(encoding="utf-8"))
        cat = idx.setdefault("categories", {}).setdefault(
            "99_user_created", {"count": 0, "skills": []})
        cat["skills"].append({
            "id": skill["id"],
            "name": skill["name_zh"],
            "desc": skill["description"],
            "triggers": skill["trigger_words"][:3],
        })
        cat["count"] = len(cat["skills"])
        idx["total"] = sum(
            c.get("count", 0) for c in idx["categories"].values())
        index_path.write_text(
            json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug(f"Index update failed: {e}")
