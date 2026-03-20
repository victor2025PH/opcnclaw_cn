# Cursor 开发任务清单 v2

> **负责范围：** 前端 UI/UX、可视化、页面交互、CSS/HTML/JS、安装包编译
> **不碰范围：** 后端 Python 逻辑、数据库 Schema、微信引擎、AI 路由（Claude Code 负责）
> **基准版本：** v3.7.0 (2026-03-21)
> **上次更新：** 2026-03-21 (第三轮对接后)

---

## 已完成 (v3.6.0 → v3.7.0)

- [x] QR 控制台页面完整重设计（品牌、功能卡片、导航、系统状态面板）
- [x] QR 页面 SSE 实时推送（EventSource → /api/events/stream）
- [x] Toast 通知系统（右上角滑入/滑出，支持 success/warning/error/info）
- [x] 数值动画过渡（CPU/内存等指标变化时淡入淡出）
- [x] 移动端三级响应式（800px / 400px 断点）
- [x] AI 配置状态卡片（智能检测 + 快捷操作入口）
- [x] 最近活动折叠面板（基于 EventBus，10 种事件类型）
- [x] SSE 连接状态指示器（绿色/红色小圆点 + 指数退避重连）
- [x] Admin 侧栏加「控制台/QR」导航链接
- [x] QR ↔ Admin 色系统一（CSS Variables 对齐）
- [x] 断开连接 bug 修复（disconnectPermanently + _disconnectedByUser 标志）
- [x] auto_open_qr 配置开关（前端 toggle + 后端 API）
- [x] 安装包编译 × 3 次

---

## 阶段 A：控制台 & 管理面板增强

### A1. QR 控制台主题切换 — ✅ 已完成
- [x] 右上角圆形主题切换按钮（☀️/🌙 图标）
- [x] CSS Variables 定义 `[data-theme="light"]` 完整覆盖
- [x] localStorage 持久化 `oc-qr-theme`
- [x] `prefers-color-scheme` 自动检测 + 监听变化
- [x] 亮色主题专属覆盖（nav-btn、collapse-hd、status-bar、toast）
- [x] glow 背景透明度随主题调整
- [x] 文件：`src/client/qr.html`

### A2. Admin 仪表盘实时图表 — ✅ 已完成
- [x] ECharts 图表（已有 CDN 引用）
- [x] CPU 使用率实时折线图（5分钟滑动窗口，8秒采样，38点）
- [x] 内存使用率实时折线图（同上）
- [x] 今日消息量柱状图（`/api/analytics/hourly`）
- [x] 渐变色面积填充 + smooth 曲线
- [x] 导航离开时自动停止轮询，返回时恢复
- [x] 窗口 resize 自适应
- [x] 移动端单列布局（768px 断点）
- [x] 文件：`src/client/admin.html`

### A3. 快捷操作面板 — ✅ 已完成
- [x] QR 页面新增折叠面板「⚡ 快捷操作」
- [x] 一键重启服务：`POST /api/system/restart`（含确认对话框 + 5s后自动刷新）
- [x] 清除缓存：`POST /api/system/clear-cache`（含结果Toast提示）
- [x] 切换 AI 平台：跳转 /setup
- [x] 查看后端日志：`GET /api/system/logs?lines=30`（可展开的日志面板）
- [x] 2×2 网格按钮布局，hover动效，loading状态
- [x] API不可用时优雅降级提示
- [x] 文件：`src/client/qr.html`

### A4. Admin 数据分析图表 — ✅ 已完成
- [x] 每日回复数柱状图（7天，`/api/analytics/daily?days=7`）
- [x] 情感分布饼图（`/api/wechat/smart-stats` → sentiment_distribution）
- [x] 自适应数据格式（兼容多种 API 返回结构）
- [x] 无数据时显示占位提示
- [x] 文件：`src/client/admin.html` analytics 页面
- 注：24h热力图 + Top10 之前已存在

---

## 阶段 B：多模态交互 UI（依赖 DEV_ROADMAP.md 阶段 1）

### B1. 校准向导 UI — ✅ 已存在
> camera.js 中已有 `startGazeCalibration()` (5点注视校准) 和 `CalibWizard` (7步完整向导)
> settings.js 已绑定按钮事件，设置面板已有入口

### B2. 手势绑定配置 UI — ✅ 已完成
- [x] 新建 `src/client/js/gesture-bindings.js`（ES Module）
- [x] 面部表情绑定编辑器：每个表情显示名称 + 分类 + 动作下拉选 + 启用/禁用开关
- [x] 头部动作绑定编辑器：同上结构
- [x] 14种可选动作（确认/取消/点击/右键/语音/滚动/撤销/重做/回车/截图/Escape/Tab/无动作）
- [x] 保存到 `PUT /api/access/config`
- [x] 恢复默认：`POST /api/access/config/reset`
- [x] 保存反馈动效（按钮文字变 ✅ 已保存）
- [x] 完整 CSS 样式（toggle 开关、action select、响应式）
- [x] 通过 settings.js init() 初始化，挂载到 tab-expression 面板

### B3. CoworkBus 协作状态面板 — ✅ 已完成（已增强）
- [x] 新建 `src/client/js/cowork-panel.js`（ES Module）
- [x] app.html 头部 header-right 添加协作状态指示器按钮
- [x] 状态图标：🟢 AI空闲 / 🔵 AI工作中 / 🟡 已暂停 / 🔴 冲突
- [x] 下拉面板：状态区 + 任务队列 + 操作日志
- [x] 撤销按钮：`POST /api/cowork/undo`（含单条撤销和撤销上一步）
- [x] 暂停/恢复：`POST /api/cowork/pause|resume`（按钮文字动态切换）
- [x] 数据来源：`GET /api/cowork/status` + `GET /api/cowork/journal`
- [x] Mock 数据降级：API 不可用时自动使用 mock，显示 Mock 标签
- [x] 5秒轮询 + bus 事件监听双通道
- [x] header-overflow-menu 适配
- [x] CoworkBus CSS 完整样式 + 亮色主题适配 + 移动端适配
- [x] 通过 settings.js init() 初始化
- [x] **增强**：展示 `can_operate_desktop`（桌面操作权限标签 ✅/🚫）
- [x] **增强**：展示 `tasks_running` / `tasks_pending`（🏃运行·排队指标）
- [x] **增强**：展示 `human_window`（用户当前窗口信息）
- [x] **增强**：队列项状态颜色区分（running/pending/completed）
- [x] **增强**：截图查看按钮（📷 + overlay modal 对比视图）

### B4. 操作日志时间线 — ✅ 已完成
- [x] 新建 `src/client/js/action-timeline.js`（ES Module）
- [x] 垂直时间线布局：dot图标 + 连接线 + 内容区
- [x] 每条记录：操作类型图标 + 描述 + 精确时间 + 相对时间
- [x] 截图对比：点击📷按钮加载 `GET /api/cowork/journal/{id}/thumbnails`，展示操作前后截图
- [x] 撤销到某步：「↩️ 撤销到这里」按钮 + 确认对话框
- [x] 最新条目高亮（accent 边框）
- [x] 缓存截图数据避免重复请求
- [x] 兼容多种 journal 返回格式（数组/对象包裹）
- [x] 刷新按钮 + bus 事件 `cowork:journal_update` 自动更新
- [x] 通过 settings.js init() 初始化，挂载到 tab-expression 面板
- [x] 数据来源：`GET /api/cowork/journal` + `GET /api/cowork/journal/{id}/thumbnails`

---

## 阶段 C：生态 & 体验

### C1. MCP 工具市场 UI — ✅ 已完成
- [x] MCP 面板已有完整 UI（`settings-models.js`）
- [x] 已安装 MCP Server 列表，卡片式：名称 + 状态徽章 + 连接/断开 toggle 开关 + 移除按钮
- [x] **增强**：每张服务器卡片增加启用/禁用 toggle 开关（`mcpToggle`）
- [x] **增强**：服务器卡片增加移除按钮（`mcpRemove` → `DELETE /api/mcp/servers/{id}`）
- [x] **增强**：预置服务器快速选择（桌面控制、微信工具、文件系统、Web搜索）
- [x] 添加 MCP Server：名称 + 传输方式(STDIO/HTTP) + 命令/URL → `POST /api/mcp/servers/add`
- [x] 工具测试：选工具 → 参数表单(自动生成) → JSON编辑 → 执行 → 显示结果
- [x] 工具收藏、拖拽排序、调用历史
- [x] 文件：`src/client/js/settings-models.js` + `src/client/app.html`

### C2. 移动端 PWA 增强（1 天）
- [ ] QR 页面注册 Service Worker
- [ ] 离线可查看历史状态和活动
- [ ] manifest.json 图标和主题色
- [ ] 添加到主屏幕支持

### C3. 在线体验 Demo 页（3 天）
- [ ] 新建 `src/client/demo.html`
- [ ] 录屏 GIF/视频展示核心功能
- [ ] 交互式模拟聊天界面
- [ ] 功能对比表 + 下载按钮
- [ ] 响应式（移动端可看）

### C4. 国际化 (i18n) 架构（2 天）
- [ ] 创建 `src/client/js/i18n.js`
- [ ] 中/英文 JSON 语言包
- [ ] QR + Admin 双页面文案替换
- [ ] 语言切换 UI（admin 已有按钮框架）
- [ ] localStorage 持久化

---

## 开发规范

- 所有新 JS 放 `src/client/js/`，ES Module 格式
- 从 `state.js` 导入共享状态
- 不引入新 npm 依赖（纯原生 JS + CSS）
- API 用 `fetch()`，不用 axios
- CSS 用 CSS Variables
- 新面板参考 `settings-wechat.js` 的面板模式
- 每阶段完成后同步到安装目录 + 编译安装包

---

## 需要 Claude Code 提供的 API

| API | 用途 | 我方消费位置 |
|-----|------|-------------|
| `GET /api/analytics/hourly` | 每小时消息量 | A2 图表 |
| `GET /api/analytics/daily?days=7` | 每日回复数 | A4 图表 |
| `POST /api/system/restart` | 重启服务 | A3 快捷操作 |
| `POST /api/system/clear-cache` | 清除缓存 | A3 快捷操作 |
| `GET /api/system/logs?lines=N` | 尾部日志 | A3 快捷操作 |
| `GET /api/cowork/status` | 协作状态(含 can_operate_desktop, tasks_running, tasks_pending, human_window) | B3 状态面板 |
| `GET /api/cowork/journal` | 操作日志 | B3/B4 时间线 |
| `GET /api/cowork/journal/{id}/thumbnails` | 操作前后截图 | B4 时间线 |
| `POST /api/cowork/undo` | 撤销操作 | B3/B4 |
| `POST /api/cowork/pause\|resume` | 暂停/恢复 | B3 |
| `POST /api/cowork/task` | 添加后台任务 | B3（可选） |
| `PUT /api/access/config` | 保存手势绑定 | B2 |
| `POST /api/access/config/reset` | 恢复默认绑定 | B2 |
| `DELETE /api/mcp/servers/{id}` | 移除 MCP 服务器 | C1 |
| `POST /api/mcp/disconnect/{id}` | 断开 MCP 服务器 | C1 |
