# Claude Code 开发任务清单 v2

> **负责范围：** 后端 Python、数据库、微信引擎、AI 路由、API 端点、测试、性能
> **不碰范围：** 前端 HTML/CSS/JS 页面样式、QR 控制台页面、admin.html UI（Cursor 负责）
> **基准版本：** v3.7.0 (2026-03-21)
> **上次更新：** 2026-03-21

---

## 已完成 (v3.6.0 → v3.7.0)

- [x] 数据库合并（13 SQLite → 2: main.db + wechat.db）
- [x] 双 FTS5 索引（unicode61 + jieba 中文分词）
- [x] 微信对话历史持久化（wechat_conversations 表）
- [x] Swagger UI (/docs) + ReDoc (/redoc) 自动 API 文档
- [x] 凌晨 3 点自动清理过期数据
- [x] 朋友圈 Vision AI 缓存 + 自动点赞评论
- [x] Web Notification API 桌面通知
- [x] 微信回复日志卡片式重设计
- [x] 启动时间 13s→8s 优化
- [x] 166 passed 全量回归测试

---

## 阶段 A：系统 API 扩展（供 Cursor 前端消费）

### A1. 系统管理 API（1 天）
- [ ] `POST /api/system/restart` — 优雅重启（先保存状态，再 reload）
- [ ] `POST /api/system/clear-cache` — 清除所有缓存（OCR、FTS、TTS）
- [ ] `GET /api/system/logs?lines=N&level=INFO` — 返回最近 N 行日志（从 loguru 内存 sink 读取）
- [ ] `GET /api/system/config` — 读取完整 config.ini（脱敏 API Key）
- [ ] `POST /api/system/config` — 修改 config.ini（热重载支持的项即时生效）
- [ ] 文件：`src/server/main.py` 或新建 `src/server/routers/system.py`

### A2. 分析统计 API（1 天）
- [ ] `GET /api/analytics/hourly` — 最近 24h 每小时消息量（聊天+微信）
- [ ] `GET /api/analytics/daily?days=30` — 每日消息量趋势
- [ ] `GET /api/analytics/top-contacts?limit=10` — 活跃好友排行
- [ ] `GET /api/analytics/sentiment-distribution` — 情感分布统计
- [ ] 数据来源：main.db 的 conversations + wechat.db
- [ ] 文件：`src/server/routers/admin.py` 或新建 `src/server/routers/analytics.py`

### A3. 配置热重载（1 天）
- [ ] 监听 config.ini 修改事件（watchdog 或 定时 stat）
- [ ] 支持热重载的配置项：AI provider、TTS voice、auto_open_qr、速率限制
- [ ] 不支持热重载的配置项（需重启）：http_port、https_port
- [ ] 通过 EventBus 发布 `config_changed` 事件
- [ ] 文件：`src/server/main.py`

---

## 阶段 B：人机协同后端（DEV_ROADMAP.md 阶段 1-2）

### B1. HumanDetector 人类活动检测器（3 天）
- [ ] 新建 `src/server/human_detector.py`
- [ ] 从 desktop.py 提取窗口/鼠标活动检测逻辑
- [ ] 集成 gaze-tracker 数据（通过 WebSocket 接收前端数据）
- [ ] API: `GET /api/cowork/human-status` → {active_window, mouse_idle_ms, typing, gaze_zone}
- [ ] 测试: `tests/test_human_detector.py`

### B2. Action Journal 操作日志与回滚（5 天）
- [ ] 新建 `src/server/action_journal.py`
- [ ] 数据模型: ActionEntry {id, action_type, params, before_screenshot, after_screenshot, timestamp, reversible}
- [ ] 记录所有 desktop.py 操作（click/type/hotkey/scroll）
- [ ] 截图对比：操作前后各截一张缩略图
- [ ] 撤销接口: `undo_last()` → 执行反向操作
- [ ] API: `GET /api/cowork/journal` 返回最近操作列表
- [ ] API: `POST /api/cowork/undo` 撤销最后一步
- [ ] main.db 新增 `action_journal` 表
- [ ] 自动清理：保留最近 200 条
- [ ] 测试: `tests/test_action_journal.py`

### B3. CoworkBus 协作调度（7 天）
- [ ] 新建 `src/server/cowork_bus.py`
- [ ] WorkZone：定义窗口归属（human / ai / idle）
- [ ] 冲突检测：AI 目标窗口 == 用户活跃窗口 → 暂停
- [ ] 任务队列：BackgroundTask {id, description, target_window, status, priority}
- [ ] 调度策略：用户活跃→AI暂停桌面，用户空闲30s→AI可操作
- [ ] API: `POST /api/cowork/task` 创建任务
- [ ] API: `GET /api/cowork/status` 返回 {human_zone, ai_zone, queue}
- [ ] API: `POST /api/cowork/pause` / `POST /api/cowork/resume`
- [ ] 集成 HumanDetector
- [ ] 测试: `tests/test_cowork_bus.py`

### B4. 意图融合引擎（5 天）
- [ ] 新建 `src/server/intent_fusion.py`
- [ ] 四通道信号融合（手势+表情+语音+触控）
- [ ] 融合规则矩阵（见 DEV_ROADMAP.md 任务 1.1）
- [ ] 紧急停止 > 语音指令 > 手势动作 > 情感上下文
- [ ] 500ms 时间窗口内信号合并
- [ ] WebSocket 信号协议（type: "signal"）
- [ ] 测试: `tests/test_intent_fusion.py`

---

## 阶段 C：MCP 生态 & 高级功能

### C1. MCP Server 标准化（3 天）
- [ ] 将桌面控制包装为标准 MCP Server
- [ ] 支持 stdio/HTTP 双传输
- [ ] 微信操作打包为 MCP 工具（wechat_read, wechat_send, wechat_moments）
- [ ] 注册到 MCP Server Registry
- [ ] 文件：`src/mcp/desktop_server.py`

### C2. 微信引擎优化（3 天）
- [ ] DB Reader 密钥提取适配微信 4.x
- [ ] wxauto 4.x 兼容层完善
- [ ] 朋友圈滚动+多页读取
- [ ] 评论链自动跟进

### C3. A2A 协议支持（3 天）
- [ ] 新建 `src/server/a2a.py`
- [ ] Agent-to-Agent 通信协议
- [ ] 与代码 Agent 协作场景

### C4. 性能监控 API（2 天）
- [ ] `GET /api/metrics` — 各组件延迟/吞吐量
- [ ] FTS5 搜索延迟、Vision AI 调用次数、微信消息处理延迟
- [ ] Prometheus 格式 metrics 端点（可选）

### C5. 安全加固（2 天）
- [ ] Admin 面板 PIN 码保护（`POST /api/auth/pin`）
- [ ] API Token 管理（生成/吊销/查看）
- [ ] CORS 配置细化
- [ ] 速率限制优化

### C6. 自动更新检测（1 天）
- [ ] 启动时检查 GitHub Release
- [ ] API: `GET /api/system/update-check` → {has_update, latest_version, download_url}
- [ ] 通过 EventBus 发布 `update_available` 事件

---

## 阶段 D：测试补全

- [ ] `tests/test_wechat_adapter.py` — Mock UIA 测试
- [ ] `tests/test_cowork_bus.py` — 冲突检测/调度
- [ ] `tests/test_action_journal.py` — 记录/撤销
- [ ] `tests/test_intent_fusion.py` — 多模态融合
- [ ] `tests/test_moments.py` — Vision AI 结果解析
- [ ] 每阶段完成后跑全量回归，保持 0 failed

---

## Cursor 依赖的 API（优先开发）

| API | 方法 | 返回 | 依赖方 |
|-----|------|------|--------|
| `/api/system/clear-cache` | POST | `{ok, cleared: ["fts","ocr","vision"]}` | Cursor A3 |
| `/api/system/logs?lines=N` | GET | `{lines: ["..."]}`  | Cursor A3 |
| `/api/cowork/status` | GET | `{human_zone, ai_zone, queue: [task]}` | Cursor B3 |
| `/api/cowork/journal` | GET | `{entries: [{id,action,desc,ts}]}` | Cursor B4 |
| `/api/cowork/undo` | POST | `{ok, undone: "action_desc"}` | Cursor B3/B4 |
| `/api/cowork/pause` | POST | `{ok, status: "paused"}` | Cursor B3 |
| `/api/cowork/resume` | POST | `{ok, status: "running"}` | Cursor B3 |

已有可直接用：
- `/api/restart` (POST) — Cursor 用 `/api/system/restart`，加别名
- `/api/analytics/hourly` (GET) — 已有

## 开发规范

- 所有新模块通过 `db.py` 访问数据库
- 异步优先（async/await）
- 中文注释
- 每个模块配套 pytest 测试
- API 端点在 `routers/` 目录，业务逻辑在 `server/` 目录
- 新端点加 Swagger docstring
- 不修改前端 HTML/CSS/JS 文件（Cursor 负责）
- 文件不重叠：只改 src/server/、tests/、src/mcp/

---

## Cursor 依赖我提供的 API（优先实现）

| API | 优先级 | Cursor 用途 |
|-----|--------|------------|
| `GET /api/analytics/hourly` | **高** | Admin 实时图表 |
| `POST /api/system/restart` | **高** | QR 快捷操作 |
| `POST /api/system/clear-cache` | **高** | QR 快捷操作 |
| `GET /api/system/logs?lines=N` | **高** | QR 快捷操作 |
| `GET /api/cowork/status` | 中 | 协作状态面板 |
| `GET /api/cowork/journal` | 中 | 操作时间线 |
| `POST /api/cowork/undo` | 中 | 撤销按钮 |
| `POST /api/cowork/pause\|resume` | 中 | 暂停/恢复 |
