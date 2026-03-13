# OpenClaw Voice — 协作开发规范

## 分支策略

| 分支 | 用途 | 负责方 |
|------|------|--------|
| `main` | 稳定基线，只通过合并进入 | 双方共同维护 |
| `feat/wechat` | 微信/AI/Admin 功能开发 | Cursor A（本机） |
| `feat/installer` | Windows 安装/功能增强 | Cursor B（另一台） |

## 文件所有权

### Cursor A 独占（微信/AI/Admin）

```
src/server/routers/wechat.py        # 微信、朋友圈、联系人、群发、素材、分析
src/server/routers/workflow.py       # 工作流引擎、模板、可视化编辑、日历
src/server/routers/admin.py          # 事件、健康检查、i18n、审计、导出、监控
src/server/wechat/                   # 整个微信子包
src/server/wechat_autoreply.py
src/server/wechat_monitor.py
src/client/admin.html
src/server/adaptive_style.py
src/server/anomaly_detector.py
src/server/audit_log.py
src/server/context_compressor.py
src/server/daily_report.py
src/server/data_export.py
src/server/event_bus.py
src/server/health_check.py
src/server/i18n.py
src/server/intent_predictor.py
src/server/knowledge_base.py
src/server/long_memory.py
src/server/memory_search.py
src/server/message_export.py
src/server/notification_aggregator.py
src/server/plugin_system.py
src/server/rate_limiter.py
src/server/sentiment_analyzer.py
src/server/topic_tracker.py
src/server/workflow/
```

### Cursor B 独占（Windows 安装/桌面增强）

```
src/server/routers/voice.py          # 语音/STT/TTS/WebSocket
src/server/routers/desktop.py        # 桌面控制、文件上传、远程桌面
src/server/desktop.py
src/server/desktop_skills.py
src/client/app.html                   # 主客户端
src/client/chat.html
dist/
installer.iss
openclaw.spec
start.bat
install.bat
install_full.bat
build.bat
build_portable.py
scripts/
deploy/
```

### 共享区域（双方修改需谨慎）

```
src/server/main.py          # 拆分后仅约 500 行，冲突概率低
requirements.txt             # 各自新增依赖后合并时手动确认
.env                         # 不提交到 git
src/server/routers/__init__.py  # 空文件，不需修改
```

## 日常工作流程

```bash
# 1. 开工前拉取最新基线
git checkout main
git pull origin main

# 2. 切到自己的功能分支
git checkout feat/wechat   # Cursor A
git checkout feat/installer  # Cursor B
git rebase main              # 同步最新基线

# 3. 正常开发、提交
git add -A
git commit -m "feat: xxx"

# 4. 推送到远程
git push origin feat/wechat

# 5. 合并到 main（一方先合并，另一方再 rebase 后合并）
git checkout main
git merge feat/wechat
git push origin main
```

## 合并规则

1. **先到先得**：谁先完成功能，谁先合并到 `main`
2. **后合并方需 rebase**：`git rebase main` 解决可能的冲突
3. **共享区冲突**：只可能发生在 `main.py`（约 500 行）和 `requirements.txt`，手动解决
4. **不要 force push `main`**

## 新增模块规则

- Cursor A 新建的模块放 `src/server/` 目录下（Python 后端）
- Cursor B 新建的模块放 `src/server/` 目录下或 `scripts/`（安装/部署相关）
- 新建 router 文件放 `src/server/routers/`，并在 `main.py` 中 `include_router`
- 新增依赖：在 `requirements.txt` 末尾追加，注释标注来源

## 项目结构概览（拆分后）

```
openclaw-voice/
├── src/server/
│   ├── main.py                  # ~500 行：app 初始化 + 中间件 + startup + 共享路由
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── voice.py             # STT/TTS/WebSocket (547 行)
│   │   ├── desktop.py           # 桌面控制/文件上传 (338 行)
│   │   ├── wechat.py            # 微信全部 API (1075 行)
│   │   ├── workflow.py          # 工作流/模板/日历 (285 行)
│   │   └── admin.py             # 事件/健康/审计/导出/监控 (505 行)
│   ├── wechat/                  # 微信子包（20+ 模块）
│   ├── workflow/                # 工作流子包
│   └── *.py                     # 各功能模块
├── src/client/
│   ├── app.html                 # 主客户端（Cursor B 独占）
│   ├── admin.html               # Admin 面板（Cursor A 独占）
│   └── *.html
├── dist/                        # 构建产物（Cursor B 独占）
└── CONTRIBUTING.md              # 本文件
```
