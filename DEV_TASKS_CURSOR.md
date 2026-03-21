# Cursor 开发任务清单 v4

> **负责范围：** 前端 UI/UX、可视化、页面交互、CSS/HTML/JS
> **不碰范围：** 后端 Python 逻辑、数据库 Schema、微信引擎、AI 路由（Claude Code 负责）
> **当前版本：** v4.1.0 (2026-03-21)
> **目标版本：** v4.2.0
> **上次更新：** 2026-03-21

---

## 已完成 (v3.5.2 → v4.1.0)

### v3.5.2 → v4.0.0
- [x] QR 控制台完整重设计（品牌、功能卡片、导航、SSE、Toast）
- [x] 主题切换（亮/暗 + 自动检测 + localStorage 持久化）
- [x] Admin 仪表盘实时图表（ECharts: CPU/内存/消息量）
- [x] 快捷操作面板（重启/清缓存/日志/切换AI）
- [x] Admin 数据分析图表（回复数/情感饼图）
- [x] 校准向导（7步完整向导）
- [x] 手势绑定配置 UI（14种动作）
- [x] CoworkBus 协作状态面板（实时指标+截图对比）
- [x] 操作日志时间线（垂直时间线+撤销）
- [x] MCP 工具市场 UI（服务器列表+工具测试+收藏+历史）

### v4.0.0 → v4.1.0
- [x] P0: 意图融合面板 (intent-panel.js, 245行, 5通道可视化+时间线+紧急停止)
- [x] P2: PWA 增强 (qr-sw.js + qr-manifest.json + 离线缓存 + 添加到主屏幕)
- [x] P3: i18n 架构 (i18n.js + zh.json + en.json + QR/Admin 双页面文案 + 语言切换)
- [x] P4: Demo 页面 (demo.html, 深色主题, 6功能卡片, 响应式)
- [x] P5: UI 打磨 (长消息折叠/sparkline/骨架屏/空状态)

---

## v4.2.0 任务

### P0. 多用户 UI（3天）— 依赖 Claude 后端 API
> **状态：⏳ 等待 Claude 完成声纹识别后端**
> Claude 完成后会通知你，届时以下 API 可用：
> - `GET /api/users` — 用户列表
> - `POST /api/users/register` — 注册新用户（上传声纹音频）
> - `GET /api/users/current` — 当前识别到的用户
> - `POST /api/users/switch` — 手动切换用户

- [ ] 新建 `src/client/js/user-panel.js`（ES Module）
- [ ] app.html 顶部 header-right 添加用户头像按钮（当前用户名 + 切换入口）
- [ ] 用户切换下拉面板：头像列表 + "添加新用户"入口
- [ ] 用户注册向导 UI：
  - 步骤 1：输入昵称 + 选择头像（emoji 选择器）
  - 步骤 2：录入 3 句话采集声纹（带进度条 + 波形动画）
  - 步骤 3：完成确认
  - 录音使用 `navigator.mediaDevices.getUserMedia({audio:true})`
  - 每句话录 3 秒，上传到 `POST /api/users/register`
- [ ] 用户偏好设置面板：昵称编辑、头像更换、AI 人设风格选择
- [ ] 声纹自动识别：当 `GET /api/users/current` 返回值变化时，header 头像实时更新
- [ ] QR 页面也显示当前用户标识
- [ ] i18n 键前缀：`user.*`（添加到 zh.json 和 en.json）
- [ ] CSS：用户面板沿用 cowork-panel 风格，注册向导用 calibration wizard 风格

### P1. 离线状态 UI（1天）— 依赖 Claude 后端 API
> **状态：⏳ 等待 Claude 完成离线模式后端**
> API：`GET /api/system/network-status` → `{online, mode, local_model}`

- [ ] QR 页面顶部网络状态指示器（🟢 在线 / 🟡 本地模式 / 🔴 离线）
- [ ] 离线时显示横幅："当前使用本地 AI 模型，部分功能受限"
- [ ] app.html 聊天区域模型标识：云端模型名 vs "本地 Qwen2.5"
- [ ] 离线可用功能标记：技能列表中灰显需要网络的技能
- [ ] 网络恢复时自动切换 + Toast 提示 "已恢复云端连接"
- [ ] i18n 键前缀：`offline.*`

### P2. 工作流可视化编辑器（5天）— 依赖 Claude 后端 API
> **状态：⏳ 等待 Claude 完成定时工作流后端**
> API：
> - `GET /api/workflows` — 工作流列表
> - `POST /api/workflows` — 创建工作流
> - `PUT /api/workflows/{id}` — 更新工作流
> - `POST /api/workflows/{id}/run` — 手动执行
> - `DELETE /api/workflows/{id}` — 删除
> - `GET /api/workflows/{id}/history` — 执行历史

- [ ] 新建 `src/client/js/workflow-editor.js`（ES Module）
- [ ] 画布区域：纯 CSS+JS 拖拽（不引入 npm 依赖）
  - 节点可在画布内自由拖动（mousedown/mousemove/mouseup）
  - 缩放支持（wheel 事件）
  - 画布平移（右键拖拽或空格+拖拽）
- [ ] 节点类型（左侧工具栏拖出）：
  - 触发器：定时（cron 表达式）、事件（微信新消息/系统启动）
  - 条件：if/else 分支（关键词匹配/时间段/联系人白名单）
  - 动作：发微信消息、截屏、打开应用、发朋友圈、TTS 播报
  - AI：生成文案、分析内容、智能回复
- [ ] 节点之间可拖线连接（SVG path + Bezier 曲线）
  - 输出端口（节点右侧圆点）拖线到输入端口（节点左侧圆点）
  - 连线可删除（点击连线 + Delete 键）
- [ ] 右侧属性面板：选中节点后编辑参数
  - 定时触发器：cron 表达式编辑器（预设 + 自定义）
  - 发消息动作：联系人选择 + 消息模板（支持变量 {date}/{weather}）
  - AI 节点：prompt 编辑 + 模型选择
- [ ] 预置模板（一键加载）：
  - "每日早报"：8:00 触发 → AI 生成新闻摘要 → TTS 播报
  - "微信自动回复"：新消息触发 → 关键词匹配 → AI 回复
  - "朋友圈定时发布"：12:00 触发 → AI 生成文案 → 发布
- [ ] 工具栏按钮：运行/暂停/保存/删除
- [ ] 执行历史时间线（复用 action-timeline.js 风格）
- [ ] 挂载到 admin.html 的工作流 tab
- [ ] i18n 键前缀：`workflow.*`

### P3. IoT 控制面板（2天）— 依赖 Claude 后端 API
> **状态：⏳ 等待 Claude 完成 IoT 后端**
> API：
> - `GET /api/iot/devices` — 设备列表
> - `POST /api/iot/control` — 控制设备
> - `POST /api/iot/config` — 保存 HomeAssistant 配置

- [ ] 新建 `src/client/js/iot-panel.js`（ES Module）
- [ ] 设备列表卡片：图标 + 名称 + 状态（开/关/亮度/温度）
- [ ] 点击设备弹出控制面板：
  - 开关类：toggle 按钮
  - 灯光类：亮度滑块 + 色温滑块
  - 空调类：温度 +/- 按钮 + 模式选择
- [ ] 房间分组视图（客厅/卧室/厨房，可折叠）
- [ ] 语音命令快捷入口："关灯"、"调高温度"（链接到语音输入）
- [ ] 设置区：HomeAssistant URL + Long-Lived Token 输入
- [ ] 挂载到 settings 的新 tab "智能家居"
- [ ] i18n 键前缀：`iot.*`

### P4. Web Push 订阅 UI（1天）— 依赖 Claude 后端 API
> **状态：⏳ 等待 Claude 完成推送后端**
> API：
> - `POST /api/push/subscribe` — 提交推送订阅
> - `GET /api/push/status` — 查询推送状态
> - `POST /api/push/test` — 发送测试通知

- [ ] QR 页面添加"开启通知"按钮（铃铛图标）
- [ ] 点击后调用 `Notification.requestPermission()` + `PushManager.subscribe()`
- [ ] 将 subscription JSON 发送到 `POST /api/push/subscribe`
- [ ] 通知设置面板（在 settings 中）：
  - 总开关
  - 类型选择：微信新消息 / 系统事件 / 工作流完成 / 更新可用
  - 静默时段：23:00-07:00 不推送
- [ ] 权限被拒绝时显示引导提示
- [ ] 测试按钮：发送一条测试推送
- [ ] i18n 键前缀：`push.*`

---

## 开发规范

- 所有新 JS 放 `src/client/js/`，ES Module 格式
- 从 `state.js` 导入共享状态
- **不引入新 npm 依赖**（纯原生 JS + CSS）
- API 用 `fetch()`，不用 axios
- CSS 用 CSS Variables
- 新面板参考 `settings-wechat.js` 的面板模式
- 每阶段完成后同步到安装目录 + 编译安装包
- 新面板的所有文案必须在 `src/client/i18n/zh.json` 和 `en.json` 中添加对应键

---

## 需要 Claude Code 提供的 API（按开发顺序）

| 批次 | API | 用途 | 状态 |
|------|-----|------|------|
| 第1批 | `GET /api/users` | 用户列表 | ⏳ Claude 开发中 |
| 第1批 | `POST /api/users/register` | 声纹注册 | ⏳ Claude 开发中 |
| 第1批 | `GET /api/users/current` | 当前用户 | ⏳ Claude 开发中 |
| 第1批 | `POST /api/users/switch` | 切换用户 | ⏳ Claude 开发中 |
| 第2批 | `GET /api/system/network-status` | 网络状态 | ⏳ 待开发 |
| 第3批 | `GET /api/workflows` | 工作流列表 | ⏳ 待开发 |
| 第3批 | `POST /api/workflows` | 创建工作流 | ⏳ 待开发 |
| 第3批 | `POST /api/workflows/{id}/run` | 执行工作流 | ⏳ 待开发 |
| 第4批 | `GET /api/iot/devices` | IoT 设备列表 | ⏳ 待开发 |
| 第4批 | `POST /api/iot/control` | 控制设备 | ⏳ 待开发 |
| 第5批 | `POST /api/push/subscribe` | 推送订阅 | ⏳ 待开发 |

## 已有可直接用的 API（无需等待）

无。所有 v4.2 前端任务都依赖 Claude 新 API。Claude 会按 P0→P1→P2→P3→P4 顺序开发后端，每完成一批 API 会更新本文档状态并通知你开始。
