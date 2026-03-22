# -*- coding: utf-8 -*-
"""
项目知识库 — 让 Agent 引用历史项目成果

扫描 data/projects/ 中的历史项目，建立索引，
当 Agent 执行新任务时，注入相关历史项目的摘要。

护城河：项目积累越多，AI 产出越精准。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECTS_DIR = _PROJECT_ROOT / "data" / "projects"

# 内存缓存：项目索引
_index: List[Dict] = []
_index_time: float = 0
_INDEX_TTL = 300  # 5 分钟缓存


def _build_index() -> List[Dict]:
    """扫描项目目录，建立索引"""
    global _index, _index_time

    if time.time() - _index_time < _INDEX_TTL and _index:
        return _index

    index = []
    if not PROJECTS_DIR.exists():
        return index

    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_file = d / "project.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            # 读取 README.md（CEO 总结）作为摘要
            summary = ""
            readme = d / "README.md"
            if readme.exists():
                summary = readme.read_text(encoding="utf-8")[:500]

            # 收集关键词（从任务描述 + 文件名 + 摘要）
            keywords = set()
            task = meta.get("task", "")
            name = meta.get("name", "")
            for text in [task, name, summary]:
                # 使用滑动窗口提取 2-4 字关键词
                import re
                chars = re.findall(r'[\u4e00-\u9fff]', text)
                char_str = ''.join(chars)
                for wlen in (2, 3, 4):
                    for i in range(len(char_str) - wlen + 1):
                        keywords.add(char_str[i:i+wlen])

            index.append({
                "project_id": meta.get("project_id", d.name),
                "name": name,
                "task": task,
                "team_name": meta.get("team_name", ""),
                "agent_count": meta.get("agent_count", 0),
                "created_at": meta.get("created_at", 0),
                "artifacts": [a.get("filename", "") for a in meta.get("artifacts", [])],
                "summary": summary[:300],
                "keywords": list(keywords)[:30],
            })
        except Exception as e:
            logger.debug(f"[ProjectKB] 索引失败: {d.name}: {e}")

    # 按时间倒序
    index.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    _index = index[:50]  # 保留最近 50 个项目
    _index_time = time.time()
    logger.debug(f"[ProjectKB] 索引更新: {len(_index)} 个项目")
    return _index


def find_related_projects(task_description: str, limit: int = 3) -> List[Dict]:
    """根据任务描述找到相关历史项目"""
    index = _build_index()
    if not index:
        return []

    import re
    # 提取任务关键词（滑动窗口，限制输入长度避免生成过多关键词）
    chars = re.findall(r'[\u4e00-\u9fff]', task_description[:100])
    char_str = ''.join(chars)
    task_words = set()
    for wlen in (2, 3):  # 只用 2-3 字窗口（4字匹配概率太低）
        for i in range(len(char_str) - wlen + 1):
            task_words.add(char_str[i:i+wlen])
    if not task_words:
        return []

    # 计算相关性分数
    scored = []
    for proj in index:
        proj_words = set(proj.get("keywords", []))
        overlap = task_words & proj_words
        if overlap:
            score = len(overlap)
            # 同类任务加分
            if any(w in proj.get("task", "") for w in ["营销", "方案", "文案"] if w in task_description):
                score += 2
            scored.append((score, proj))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:limit]]


def get_knowledge_context(task_description: str) -> str:
    """生成项目知识库上下文（注入到 Agent prompt）"""
    related = find_related_projects(task_description)
    if not related:
        return ""

    parts = ["\n\n## 历史项目参考（你可以借鉴的经验）"]
    for p in related:
        line = f"- 项目「{p['name']}」：{p['task'][:80]}"
        if p.get("summary"):
            line += f"\n  摘要：{p['summary'][:150]}..."
        if p.get("artifacts"):
            files = ", ".join(p["artifacts"][:3])
            line += f"\n  产出物：{files}"
        parts.append(line)

    parts.append("\n> 可以参考历史项目的方案和经验，但要根据本次需求创新。")
    return "\n".join(parts)
