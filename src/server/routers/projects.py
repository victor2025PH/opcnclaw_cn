# -*- coding: utf-8 -*-
"""项目工作空间 API — /api/projects/* & /report/*"""
from __future__ import annotations

import io
import re
import zipfile

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse
from loguru import logger
from starlette.responses import Response

router = APIRouter(tags=["projects"])


@router.get("/api/projects")
async def list_projects_api():
    """项目列表"""
    from ..project_workspace import list_projects
    return {"projects": list_projects()}


@router.get("/api/projects/{project_id}")
async def get_project_api(project_id: str):
    """项目详情"""
    from ..project_workspace import get_project
    p = get_project(project_id)
    if not p:
        return {"error": "项目不存在"}
    return {"project": p.to_dict(), "files": p.list_files()}


@router.get("/api/projects/{project_id}/files/{filename}")
async def get_project_file(project_id: str, filename: str):
    """读取项目文件"""
    from ..project_workspace import get_project
    p = get_project(project_id)
    if not p:
        return Response(content="项目不存在", status_code=404)
    content = p.get_file(filename)
    if content is None:
        return Response(content="文件不存在", status_code=404)
    # 判断文件类型
    if filename.endswith('.md'):
        return Response(content=content, media_type="text/markdown; charset=utf-8")
    elif filename.endswith('.html'):
        return Response(content=content, media_type="text/html; charset=utf-8")
    elif filename.endswith('.csv'):
        return Response(content=content, media_type="text/csv; charset=utf-8")
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.get("/report/{project_id}")
async def share_report(project_id: str):
    """公开分享报告页面（无需登录）"""
    from ..project_workspace import get_project, list_projects
    # 先尝试精确匹配
    p = get_project(project_id)
    if not p:
        # 尝试模糊匹配（URL 可能只传了部分 ID）
        for proj in list_projects():
            if project_id in proj.get("project_id", ""):
                p = get_project(proj["project_id"])
                break
    if not p:
        return HTMLResponse("<h1>报告不存在</h1><p>该项目报告可能已被删除。</p>", status_code=404)
    # 找 HTML 报告文件
    for f in p.list_files():
        if f.get("filename", "").endswith(".html"):
            content = p.get_file(f["filename"])
            if content:
                return HTMLResponse(content)
    # 降级：用 README.md 生成简单页面
    readme = p.get_file("README.md")
    if readme:
        body = readme
        body = re.sub(r'^### (.*$)', r'<h3>\1</h3>', body, flags=re.M)
        body = re.sub(r'^## (.*$)', r'<h2>\1</h2>', body, flags=re.M)
        body = re.sub(r'^# (.*$)', r'<h1>\1</h1>', body, flags=re.M)
        body = re.sub(r'^\- (.*$)', r'<li>\1</li>', body, flags=re.M)
        body = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', body)
        body = body.replace('\n\n', '</p><p>').replace('\n', '<br>')
        html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{p.name} — 52AI 工作队</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:-apple-system,sans-serif;background:#0b0d14;color:#eee;max-width:800px;margin:0 auto;padding:20px 16px}}
h1,h2,h3{{margin:20px 0 10px;color:#fff}}p{{margin:8px 0;line-height:1.7;color:#ccc}}li{{margin:4px 0;color:#ccc}}strong{{color:#fff}}
.header{{background:linear-gradient(135deg,#6c63ff,#8b5cf6);padding:30px 20px;text-align:center;border-radius:12px;margin-bottom:20px}}
.header h1{{font-size:22px;margin-bottom:6px}}.header p{{opacity:.8;font-size:13px}}
.footer{{text-align:center;padding:24px;color:#555;font-size:11px;margin-top:30px}}</style></head><body>
<div class="header"><h1>{p.name}</h1><p>{p.task[:80]}</p></div>
<div>{body}</div>
<div class="footer">由 52AI 工作队自动生成</div></body></html>"""
        return HTMLResponse(html)
    return HTMLResponse("<h1>暂无报告内容</h1>", status_code=404)


@router.get("/api/projects/{project_id}/share-url")
async def get_share_url(project_id: str, request: Request):
    """获取项目分享链接"""
    host = request.headers.get("host", "localhost:9766")
    scheme = "https" if "443" in host else "http"
    url = f"{scheme}://{host}/report/{project_id}"
    return {"url": url, "project_id": project_id}


@router.delete("/api/projects/{project_id}")
async def delete_project_api(project_id: str):
    """删除项目（本地工作区）"""
    from ..project_workspace import delete_project

    if delete_project(project_id):
        return {"ok": True}
    return {"ok": False, "error": "项目不存在或无法删除"}


@router.patch("/api/projects/{project_id}")
async def patch_project_api(
    project_id: str,
    body: dict = Body(...),
):
    """重命名项目等元数据更新"""
    from ..project_workspace import rename_project

    name = body.get("name")
    if name is not None:
        if rename_project(project_id, str(name)):
            return {"ok": True}
        return {"ok": False, "error": "无法更新"}
    return {"ok": False, "error": "无有效字段"}


@router.get("/api/projects/{project_id}/download")
async def download_project(project_id: str):
    """下载项目（ZIP 打包）"""
    from ..project_workspace import get_project
    p = get_project(project_id)
    if not p:
        return Response(content="项目不存在", status_code=404)
    # 创建 ZIP
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in p.dir.iterdir():
            if f.is_file():
                zf.write(f, f.name)
    buffer.seek(0)
    return Response(
        content=buffer.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project_id}.zip"'},
    )
