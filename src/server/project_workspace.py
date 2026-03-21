# -*- coding: utf-8 -*-
"""
项目工作空间 — Agent 产出物的文件系统

每个任务 = 一个项目文件夹：
  data/projects/营销方案_20260322_abc12/
    ├── project.json         (元数据)
    ├── README.md            (CEO 汇总)
    ├── 01_CMO_策略.md       (各 Agent 产出)
    ├── 02_文案_推广文案.md
    ├── 03_设计_配色方案.md
    └── ...

Agent 不再只返回文字，而是创建真实文件。
"""

from __future__ import annotations

import json
import os
import shutil
import time
import re
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

PROJECTS_DIR = Path("data/projects")
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


class Project:
    """一个项目（对应一次团队执行）"""

    def __init__(self, project_id: str, name: str, team_name: str = "",
                 task: str = "", agent_count: int = 0):
        self.project_id = project_id
        self.name = name
        self.team_name = team_name
        self.task = task
        self.agent_count = agent_count
        self.created_at = time.time()
        self.status = "in_progress"  # in_progress / completed / archived
        self.artifacts: List[Dict] = []

        # 创建项目目录
        self.dir = PROJECTS_DIR / project_id
        self.dir.mkdir(parents=True, exist_ok=True)

        # 保存元数据
        self._save_meta()

    def _save_meta(self):
        meta = {
            "project_id": self.project_id,
            "name": self.name,
            "team_name": self.team_name,
            "task": self.task,
            "agent_count": self.agent_count,
            "created_at": self.created_at,
            "status": self.status,
            "artifacts": self.artifacts,
        }
        (self.dir / "project.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def save_artifact(self, agent_name: str, agent_avatar: str,
                      filename: str, content: str, file_type: str = "md") -> str:
        """Agent 保存一个产出物

        Args:
            agent_name: Agent 名称（如"文案"）
            agent_avatar: Agent 头像 emoji
            filename: 文件名（如"推广文案"）
            content: 文件内容
            file_type: 文件类型（md/html/csv/json/txt/py/js）

        Returns:
            保存的文件路径
        """
        # 清理文件名
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', filename)
        order = len(self.artifacts) + 1
        full_name = f"{order:02d}_{agent_name}_{safe_name}.{file_type}"
        file_path = self.dir / full_name

        file_path.write_text(content, encoding="utf-8")

        artifact = {
            "order": order,
            "agent_name": agent_name,
            "agent_avatar": agent_avatar,
            "filename": full_name,
            "file_type": file_type,
            "size": len(content),
            "created_at": time.time(),
        }
        self.artifacts.append(artifact)
        self._save_meta()

        logger.info(f"[Project:{self.name}] {agent_avatar} {agent_name} → {full_name} ({len(content)} chars)")
        return str(file_path)

    def save_summary(self, content: str):
        """CEO 保存汇总报告"""
        (self.dir / "README.md").write_text(
            f"# {self.name}\n\n{content}", encoding="utf-8"
        )
        self.status = "completed"
        self._save_meta()

    def get_file(self, filename: str) -> Optional[str]:
        """读取项目中的文件"""
        path = self.dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def list_files(self) -> List[Dict]:
        """列出所有文件"""
        files = []
        for f in sorted(self.dir.iterdir()):
            if f.is_file() and f.name != "project.json":
                files.append({
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                })
        return files

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "team_name": self.team_name,
            "task": self.task[:100],
            "agent_count": self.agent_count,
            "status": self.status,
            "file_count": len(self.artifacts),
            "created_at": round(self.created_at, 1),
            "dir": str(self.dir),
        }


# ── 项目管理 ──────────────────────────────────────────────────

_projects: Dict[str, Project] = {}


def create_project(name: str, team_name: str = "", task: str = "",
                   agent_count: int = 0) -> Project:
    """创建新项目"""
    import datetime
    date = datetime.datetime.now().strftime("%Y%m%d")
    pid = f"{name[:10]}_{date}_{int(time.time()*1000)%100000}"
    # 清理 ID
    pid = re.sub(r'[\\/:*?"<>| ]', '_', pid)

    project = Project(pid, name, team_name, task, agent_count)
    _projects[pid] = project

    logger.info(f"[Workspace] 新项目: {name} → {project.dir}")
    return project


def get_project(project_id: str) -> Optional[Project]:
    return _projects.get(project_id)


def list_projects() -> List[dict]:
    # 也从磁盘加载已有项目
    for d in PROJECTS_DIR.iterdir():
        if d.is_dir() and d.name not in _projects:
            meta_file = d / "project.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    p = Project.__new__(Project)
                    p.project_id = meta["project_id"]
                    p.name = meta["name"]
                    p.team_name = meta.get("team_name", "")
                    p.task = meta.get("task", "")
                    p.agent_count = meta.get("agent_count", 0)
                    p.created_at = meta.get("created_at", 0)
                    p.status = meta.get("status", "completed")
                    p.artifacts = meta.get("artifacts", [])
                    p.dir = d
                    _projects[p.project_id] = p
                except Exception:
                    pass

    return sorted(
        [p.to_dict() for p in _projects.values()],
        key=lambda x: x["created_at"],
        reverse=True,
    )[:20]
