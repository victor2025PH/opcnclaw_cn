# Claude Code 开发任务清单 v4

> **负责范围：** 后端 Python、数据库、微信引擎、AI 路由、API 端点、测试、性能
> **不碰范围：** 前端 HTML/CSS/JS 页面样式（Cursor 负责）
> **当前版本：** v4.1.0 (2026-03-21)
> **目标版本：** v4.2.0
> **上次更新：** 2026-03-21

---

## 已完成 (v3.5.2 → v4.1.0)

完整记录见 CHANGELOG.md。核心：
- [x] 数据库合并 13→2、FTS5 双索引、对话持久化
- [x] 微信 4.x 全适配（无障碍钩子 + UIA + 13种消息类型 + 精确@检测）
- [x] 人机协作（HumanDetector + ActionJournal + CoworkBus）
- [x] MCP Server（5工具, HTTP+stdio）
- [x] 意图融合引擎（4通道 + 去抖 + 跨模态增强 + 自动桌面执行）
- [x] A2A 协议（Google 标准兼容 + 5技能 + Webhook + 60s超时）
- [x] 原生 Function Calling（智谱+DeepSeek，20个工具）
- [x] 6个桌面操作工具（截屏/OCR/点击/输入/快捷键/打开应用）
- [x] Prometheus metrics + OCR 预加载 + 线程安全修复
- [x] 340 passed 全量回归

---

## v4.2.0 任务

### P0. 声纹识别 + 多用户隔离（5天）
- [ ] 新建 `src/server/speaker_id.py`
  - 声纹特征提取（resemblyzer 或 speechbrain）
  - 用户注册：3句话 → 平均 embedding → 存储
  - 实时识别：每次说话前 0.5s 提取 → 余弦相似度匹配
  - 阈值：相似度 > 0.75 = 匹配成功
- [ ] 新建 `src/server/user_manager.py`
  - 多用户数据模型：User {id, name, avatar, voice_embedding, preferences}
  - 用户隔离：每人独立 conversation_history + profiles + 偏好
  - 存储：main.db 新增 `users` 表 + `user_preferences` 表
- [ ] API 端点：
  - `GET /api/users` — 用户列表
  - `POST /api/users/register` — 注册（接收 3 段音频 base64）
  - `GET /api/users/current` — 当前声纹识别到的用户
  - `POST /api/users/switch` — 手动切换
  - `PUT /api/users/{id}` — 更新用户偏好
  - `DELETE /api/users/{id}` — 删除用户
- [ ] 集成到 voice.py WebSocket：每次 stop_listening 时自动识别说话人
- [ ] 集成到 backend.py：根据当前用户加载对应的 system_prompt 和 history
- [ ] 测试：`tests/test_speaker_id.py`

### P1. 全离线模式（3天）
- [ ] 新建 `src/server/offline_manager.py`
  - 网络状态检测：定期心跳（每 30s ping 一次 AI 平台）
  - 自动切换：有网→云端，断网→本地 Ollama
  - Ollama 模型自动下载：首次联网时 `ollama pull qwen2.5:7b`
- [ ] 修改 `src/router/router.py`
  - 新增 `offline_mode` 状态
  - 所有平台不可用时自动降级到 Ollama
  - 网络恢复时自动切回云端
- [ ] 离线 TTS 降级：Edge TTS → pyttsx3（Windows 内置）
- [ ] API：`GET /api/system/network-status` → `{online, mode, local_model}`
- [ ] 测试：`tests/test_offline.py`

### P2. 定时工作流引擎（5天）
- [ ] 扩展 `src/server/workflow.py`（已有节点框架）
  - 新增 CronTrigger 节点（APScheduler 或自实现 cron 解析）
  - 新增 EventTrigger 节点（监听 EventBus 事件）
  - 新增 AI 节点（调用 chat_simple 生成内容）
  - 工作流序列化：JSON 格式存入 main.db `workflows` 表
  - 后台调度器：定时检查并执行到期的工作流
- [ ] 预置模板：
  - "每日早报"：8:00 → get_weather + AI 生成新闻 → TTS 播报
  - "微信自动回复"：新消息 → 关键词匹配 → AI 回复
  - "朋友圈定时发布"：12:00 → AI 生成文案 → publish_moment
- [ ] API：
  - `GET /api/workflows` — 列表
  - `POST /api/workflows` — 创建
  - `PUT /api/workflows/{id}` — 更新
  - `POST /api/workflows/{id}/run` — 手动执行
  - `DELETE /api/workflows/{id}` — 删除
  - `GET /api/workflows/{id}/history` — 执行历史
- [ ] 测试：`tests/test_workflow_cron.py`

### P3. 智能家居 IoT（3天）
- [ ] 新建 `src/server/iot_bridge.py`
  - HomeAssistant REST API 集成（设备发现/状态/控制）
  - MQTT 直连（可选，灵活控制任意设备）
  - 设备数据模型：Device {id, name, type, room, state}
- [ ] 在 tools.py 添加 IoT 工具：
  - `iot_list_devices()` — 列出设备
  - `iot_control(device, action, value)` — 控制设备
  - `iot_get_status(device)` — 查询状态
- [ ] 集成到意图识别：语音"关灯"→ iot_control
- [ ] API：
  - `GET /api/iot/devices` — 设备列表
  - `POST /api/iot/control` — 控制设备
  - `POST /api/iot/config` — 保存 HomeAssistant 配置
- [ ] 测试：`tests/test_iot.py`

### P4. Web Push 推送（2天）
- [ ] 新建 `src/server/web_push.py`
  - VAPID 密钥对生成和管理
  - 推送订阅存储（main.db `push_subscriptions` 表）
  - 推送发送（pywebpush 库）
- [ ] 集成到 EventBus：微信新消息/系统事件 → 触发推送
- [ ] 静默时段控制（23:00-07:00 不推送）
- [ ] API：
  - `POST /api/push/subscribe` — 提交订阅
  - `GET /api/push/status` — 查询状态
  - `POST /api/push/test` — 测试推送
- [ ] 测试：`tests/test_push.py`

---

## 开发规范

- 所有新模块通过 `db.py` 访问数据库
- 异步优先（async/await）
- 中文注释
- 每个模块配套 pytest 测试
- API 端点加 Swagger docstring
- 不修改前端 HTML/CSS/JS 文件（Cursor 负责）

---

## Cursor 依赖我提供的 API（按批次）

| 批次 | API | Cursor 用途 | 预计完成 |
|------|-----|------------|---------|
| 第1批 | users 系列 4个端点 | P0 多用户 UI | 2-3天后 |
| 第2批 | network-status | P1 离线 UI | 第1周末 |
| 第3批 | workflows 系列 6个端点 | P2 编辑器 | 第2周初 |
| 第4批 | iot 系列 3个端点 | P3 控制面板 | 第2周中 |
| 第5批 | push 系列 3个端点 | P4 推送 UI | 第2周末 |
