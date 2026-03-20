# Claude Code 开发任务清单 v3

> **负责范围：** 后端 Python、数据库、微信引擎、AI 路由、API 端点、测试、性能
> **不碰范围：** 前端 HTML/CSS/JS 页面样式、QR 控制台页面、admin.html UI（Cursor 负责）
> **当前版本：** v4.0.0 (2026-03-21)
> **目标版本：** v4.1.0
> **上次更新：** 2026-03-21

---

## 已完成 (v3.5.2 → v4.0.0)

### 基础设施
- [x] 数据库合并（13 SQLite → 2: main.db + wechat.db）
- [x] 双 FTS5 索引（unicode61 + jieba 中文分词）
- [x] 微信对话历史持久化（wechat_conversations 表）
- [x] Swagger UI (/docs) + ReDoc (/redoc) 自动 API 文档
- [x] 凌晨 3 点自动清理过期数据
- [x] 启动时间 13s→8s 优化
- [x] FastAPI lifespan 迁移（on_event → asynccontextmanager）

### 微信 4.x
- [x] 无障碍钩子（SetWinEventHook）激活 UI 树
- [x] mmui:: 控件完整读写（会话/消息/输入/发送）
- [x] 自动回复（私聊+群聊@me）
- [x] 朋友圈 Vision AI 缓存 + 自动点赞评论
- [x] 多会话自动扫描 + 未读消息处理

### 人机协作
- [x] HumanDetector：鼠标/键盘空闲检测、前台窗口跟踪
- [x] ActionJournal：AI 操作日志（前后截图、智能撤销）
- [x] CoworkBus：协作调度（冲突检测、任务队列、后台执行器）

### API（供 Cursor 前端消费）
- [x] POST /api/system/restart
- [x] POST /api/system/clear-cache
- [x] GET /api/system/logs?lines=N
- [x] GET /api/analytics/hourly
- [x] GET /api/analytics/daily?days=N
- [x] GET /api/analytics/top-contacts
- [x] GET /api/analytics/sentiment-distribution
- [x] GET /api/cowork/status
- [x] GET /api/cowork/journal
- [x] POST /api/cowork/undo / pause / resume / task
- [x] GET /api/metrics（性能监控）

### MCP & 安全
- [x] MCP Server（5 工具, HTTP+stdio 双传输）
- [x] PIN 码安全保护（敏感 API 需 token）
- [x] 速率限制 + CORS 配置
- [x] 配置热重载（watchdog + EventBus）

### 测试
- [x] test_db.py（24 tests）
- [x] test_memory_search.py（22 tests）
- [x] test_cowork.py（19 tests）
- [x] 全量: 185 passed, 0 failed

---

## v4.1.0 任务

### P0. 意图融合引擎（5 天）
- [ ] 新建 `src/server/intent_fusion.py`
- [ ] 四通道信号融合（手势+表情+语音+触控）
- [ ] 融合规则矩阵：紧急停止 > 语音指令 > 手势动作 > 情感上下文
- [ ] 500ms 时间窗口内信号合并
- [ ] WebSocket 信号协议（type: "signal"）
- [ ] API: `POST /api/intent/signal` 接收信号
- [ ] API: `GET /api/intent/state` 当前融合状态
- [ ] 测试: `tests/test_intent_fusion.py`

### P1. A2A 协议支持（3 天）
- [ ] 新建 `src/server/a2a.py`
- [ ] Agent-to-Agent 通信：任务委派、状态同步、结果汇报
- [ ] Agent Card 发现协议（/.well-known/agent.json）
- [ ] 与代码 Agent（Claude Desktop / Cursor）协作场景
- [ ] API: `POST /api/a2a/task` 接收外部 Agent 任务
- [ ] API: `GET /api/a2a/card` Agent 能力描述
- [ ] 测试: `tests/test_a2a.py`

### P2. 自动更新检测（1 天）
- [ ] 启动时检查 GitHub Release
- [ ] API: `GET /api/system/update-check` → {has_update, latest_version, download_url}
- [ ] 通过 EventBus 发布 `update_available` 事件
- [ ] Cursor 可在 QR 页面显示更新通知

### P3. 微信引擎增强（3 天）
- [ ] 朋友圈滚动+多页读取（当前只读首屏）
- [ ] 评论链自动跟进（评论→等回复→再回复）
- [ ] 群消息 @ 任意人检测（不仅限 @me）
- [ ] 消息类型扩展：图片/语音/文件/链接识别

### P4. 测试补全（2 天）
- [ ] tests/test_wechat_adapter.py — Mock UIA 测试
- [ ] tests/test_intent_fusion.py — 多模态融合
- [ ] tests/test_moments.py — Vision AI 结果解析
- [ ] tests/test_a2a.py — Agent 通信
- [ ] 全量回归保持 0 failed

### P5. 性能优化（1 天）
- [ ] Prometheus 格式 metrics 端点（/metrics）
- [ ] FTS5 查询性能监控（慢查询日志）
- [ ] WebSocket 连接池优化
- [ ] AI 路由首包超时自适应调整

---

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

## Cursor 依赖我提供的新 API

| API | 优先级 | Cursor 用途 |
|-----|--------|------------|
| `POST /api/intent/signal` | **高** | 多模态信号发送 |
| `GET /api/intent/state` | **高** | 融合状态显示 |
| `GET /api/system/update-check` | 中 | QR 页面更新通知 |
| `GET /api/a2a/card` | 低 | Agent 发现页面 |
