# -*- coding: utf-8 -*-
"""
朋友圈图片素材库

功能：
  1. 本地素材管理 — 分类存储、导入、删除
  2. AI 智能标签 — Vision API 自动识别图片内容生成标签
  3. 语义匹配 — 根据文案关键词匹配最佳配图
  4. 使用追踪 — 避免重复使用、记录发布历史

优化思考：
  放弃传统的"目录分类"方案，改用 **AI 标签 + 向量化语义匹配**。
  但考虑到本地部署场景不方便跑 embedding 模型，
  采用"关键词标签 + TF-IDF 相似度"的轻量方案，
  效果接近语义匹配，但零额外依赖。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from .. import db as _db

MEDIA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "media"
SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _get_conn() -> sqlite3.Connection:
    return _db.get_conn("wechat")


def _file_hash(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


# ── 导入与管理 ─────────────────────────────────────────────────────────────────

def import_file(file_path: str, category: str = "", tags: List[str] = None) -> Optional[Dict]:
    """导入单张图片到素材库"""
    src = Path(file_path)
    if not src.exists():
        return None
    if src.suffix.lower() not in SUPPORTED_EXT:
        return None

    fid = _file_hash(str(src))
    conn = _get_conn()
    existing = conn.execute("SELECT id FROM media WHERE id = ?", (fid,)).fetchone()
    if existing:
        return {"id": fid, "status": "exists"}

    dest_dir = MEDIA_DIR / (category or "uncategorized")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{fid}{src.suffix.lower()}"
    shutil.copy2(str(src), str(dest))

    size = src.stat().st_size
    w, h = _get_image_size(str(src))

    conn.execute(
        "INSERT INTO media (id, filename, path, tags, category, file_size, width, height, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fid, src.name, str(dest), json.dumps(tags or [], ensure_ascii=False),
         category, size, w, h, time.time()),
    )
    conn.commit()
    return {"id": fid, "filename": src.name, "path": str(dest), "status": "imported"}


def import_directory(dir_path: str, category: str = "") -> List[Dict]:
    """批量导入目录下所有图片"""
    results = []
    d = Path(dir_path)
    if not d.is_dir():
        return results
    for f in d.iterdir():
        if f.suffix.lower() in SUPPORTED_EXT:
            r = import_file(str(f), category)
            if r:
                results.append(r)
    return results


def delete_media(media_id: str) -> bool:
    """删除素材"""
    conn = _get_conn()
    row = conn.execute("SELECT path FROM media WHERE id = ?", (media_id,)).fetchone()
    if not row:
        return False
    try:
        Path(row["path"]).unlink(missing_ok=True)
    except Exception:
        pass
    conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
    conn.commit()
    return True


def list_media(
    category: str = "",
    tag: str = "",
    limit: int = 50,
    offset: int = 0,
    unused_first: bool = True,
) -> List[Dict]:
    """列出素材"""
    conn = _get_conn()
    query = "SELECT * FROM media WHERE 1=1"
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category)
    if tag:
        query += " AND tags LIKE ?"
        params.append(f"%{tag}%")

    order = "use_count ASC, added_at DESC" if unused_first else "added_at DESC"
    query += f" ORDER BY {order} LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_categories() -> List[Dict]:
    """获取所有分类及数量"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM media GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    return [{"category": r["category"] or "uncategorized", "count": r["cnt"]} for r in rows]


def get_stats() -> Dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    analyzed = conn.execute("SELECT COUNT(*) FROM media WHERE ai_analyzed = 1").fetchone()[0]
    used = conn.execute("SELECT COUNT(*) FROM media WHERE use_count > 0").fetchone()[0]
    return {"total": total, "analyzed": analyzed, "used": used, "unused": total - used}


# ── AI 标签 ────────────────────────────────────────────────────────────────────

async def analyze_media(media_id: str, vision_call: Callable) -> Optional[Dict]:
    """
    用 Vision AI 分析图片，生成标签和描述。

    vision_call 签名: async (image_path: str) -> str
    """
    conn = _get_conn()
    row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    if not row:
        return None

    path = row["path"]
    if not Path(path).exists():
        return None

    try:
        import base64
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        prompt = (
            "分析这张图片，返回 JSON：\n"
            '{"tags": ["标签1","标签2",...], "category": "分类", "description": "一句话描述", "mood": "情绪", "colors": ["主色调"]}\n'
            "tags 至少 5 个中文关键词，category 从这些选：旅行/美食/风景/科技/生活/人物/动物/文字/艺术/运动/其他"
        )

        result = await vision_call(b64, prompt)
        parsed = _parse_ai_tags(result)

        conn.execute(
            "UPDATE media SET tags = ?, category = ?, description = ?, ai_analyzed = 1 WHERE id = ?",
            (json.dumps(parsed.get("tags", []), ensure_ascii=False),
             parsed.get("category", row["category"]),
             parsed.get("description", ""),
             media_id),
        )
        conn.commit()
        return parsed
    except Exception as e:
        logger.warning(f"Media analysis failed for {media_id}: {e}")
        return None


async def batch_analyze(vision_call: Callable, limit: int = 10) -> int:
    """批量分析未标注的素材"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id FROM media WHERE ai_analyzed = 0 LIMIT ?", (limit,)
    ).fetchall()
    count = 0
    for row in rows:
        result = await analyze_media(row["id"], vision_call)
        if result:
            count += 1
    return count


# ── 智能配图匹配 ──────────────────────────────────────────────────────────────

def match_images(
    text: str,
    count: int = 3,
    category_hint: str = "",
    exclude_ids: List[str] = None,
) -> List[Dict]:
    """
    根据文案内容智能匹配配图。

    算法：关键词提取 → 标签 TF-IDF 相似度 → 排序返回。
    优先返回未使用/少使用的图片，避免重复。
    """
    import re
    exclude_ids = exclude_ids or []

    keywords = _extract_keywords(text)
    if not keywords:
        return list_media(category=category_hint, limit=count)

    conn = _get_conn()
    query = "SELECT * FROM media WHERE ai_analyzed = 1"
    params: list = []
    if category_hint:
        query += " AND category = ?"
        params.append(category_hint)
    if exclude_ids:
        placeholders = ",".join("?" * len(exclude_ids))
        query += f" AND id NOT IN ({placeholders})"
        params.extend(exclude_ids)

    rows = conn.execute(query, params).fetchall()
    if not rows:
        return list_media(category=category_hint, limit=count)

    scored = []
    for row in rows:
        try:
            tags = json.loads(row["tags"])
        except Exception:
            tags = []
        desc = row["description"] or ""
        score = _compute_relevance(keywords, tags, desc)
        freshness = 1.0 / (1 + row["use_count"])
        scored.append((row, score * 0.7 + freshness * 0.3))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [_row_to_dict(r) for r, _ in scored[:count]]


def record_use(media_id: str):
    """记录素材被使用"""
    conn = _get_conn()
    conn.execute(
        "UPDATE media SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
        (time.time(), media_id),
    )
    conn.commit()


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _extract_keywords(text: str) -> List[str]:
    """从文案中提取关键词"""
    try:
        import jieba
        words = jieba.lcut(text)
        stop = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
                "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
                "看", "好", "自己", "这", "他", "她", "它", "们", "那", "被", "从", "把",
                "让", "还", "个", "啊", "吧", "呢", "吗", "嗯", "哦", "哈"}
        return [w for w in words if len(w) >= 2 and w not in stop]
    except ImportError:
        import re
        return [w for w in re.findall(r"[\u4e00-\u9fff]+", text) if len(w) >= 2]


def _compute_relevance(keywords: List[str], tags: List[str], desc: str) -> float:
    """计算关键词与标签的相关性分数"""
    if not keywords or not tags:
        return 0.0

    tag_set = set(t.lower() for t in tags)
    desc_lower = desc.lower()
    score = 0.0
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in tag_set:
            score += 1.0
        elif any(kw_lower in t for t in tag_set):
            score += 0.5
        elif kw_lower in desc_lower:
            score += 0.3

    return score / len(keywords) if keywords else 0


def _parse_ai_tags(raw: str) -> Dict:
    """解析 Vision AI 返回的 JSON"""
    import re
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}


def _get_image_size(path: str) -> Tuple[int, int]:
    """获取图片尺寸"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def _row_to_dict(row) -> Dict:
    try:
        tags = json.loads(row["tags"])
    except Exception:
        tags = []
    return {
        "id": row["id"],
        "filename": row["filename"],
        "path": row["path"],
        "tags": tags,
        "category": row["category"],
        "description": row["description"],
        "size": row["file_size"],
        "width": row["width"],
        "height": row["height"],
        "use_count": row["use_count"],
        "ai_analyzed": bool(row["ai_analyzed"]),
        "added_at": row["added_at"],
    }
