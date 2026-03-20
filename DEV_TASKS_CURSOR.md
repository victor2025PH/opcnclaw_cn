# Cursor 开发任务清单 v3

> **负责范围：** 前端 UI/UX、可视化、页面交互、CSS/HTML/JS、安装包编译
> **不碰范围：** 后端 Python 逻辑、数据库 Schema、微信引擎、AI 路由（Claude Code 负责）
> **当前版本：** v4.0.0 (2026-03-21)
> **目标版本：** v4.1.0
> **上次更新：** 2026-03-21

---

## 已完成 (v3.5.2 → v4.0.0)

### 阶段 A：控制台 & 管理面板
- [x] QR 控制台完整重设计（品牌、功能卡片、导航、SSE、Toast）
- [x] 主题切换（亮/暗 + 自动检测 + localStorage 持久化）
- [x] Admin 仪表盘实时图表（ECharts: CPU/内存/消息量）
- [x] 快捷操作面板（重启/清缓存/日志/切换AI）
- [x] Admin 数据分析图表（回复数/情感饼图）
- [x] 移动端响应式（800px / 400px 断点）

### 阶段 B：多模态交互 UI
- [x] 校准向导（7步完整向导）
- [x] 手势绑定配置 UI（14种动作）
- [x] CoworkBus 协作状态面板（实时指标+截图对比）
- [x] 操作日志时间线（垂直时间线+撤销）

### 阶段 C：生态
- [x] MCP 工具市场 UI（服务器列表+工具测试+收藏+历史）

---

## v4.1.0 任务

### P0. 意图融合面板 UI（2 天）— 依赖 Claude API
> 等 Claude 完成 `POST /api/intent/signal` 和 `GET /api/intent/state` 后开始

- [ ] 新建 `src/client/js/intent-panel.js`（ES Module）
- [ ] app.html 添加意图融合可视化面板
- [ ] 四通道信号实时显示（手势🖐️ / 表情😊 / 语音🎤 / 触控👆）
- [ ] 当前融合结果高亮（最终识别的意图 + 置信度进度条）
- [ ] 信号时间线（500ms 窗口内各通道信号时序图）
- [ ] 紧急停止大按钮（🛑 优先级最高）
- [ ] 数据来源: `GET /api/intent/state`（2秒轮询）
- [ ] 发送测试信号: `POST /api/intent/signal`
- [ ] CSS: 沿用 CoworkBus 面板风格

### P1. 更新通知 UI（0.5 天）— 依赖 Claude API
> 等 Claude 完成 `GET /api/system/update-check` 后开始

- [ ] QR 页面启动时检查更新: `GET /api/system/update-check`
- [ ] 有更新时显示顶部横幅（版本号 + 下载链接 + 关闭按钮）
- [ ] 更新横幅 CSS（渐变背景、圆角、响应式）
- [ ] 忽略此版本功能（localStorage 记录 dismissed 版本）

### P2. 移动端 PWA 增强（1 天）
- [ ] QR 页面注册 Service Worker
- [ ] manifest.json（图标 + 主题色 + 名称）
- [ ] 离线可查看历史状态和活动
- [ ] 添加到主屏幕支持
- [ ] iOS/Android 兼容测试

### P3. 国际化 (i18n) 架构（2 天）
- [ ] 新建 `src/client/js/i18n.js`（ES Module）
- [ ] 中文/英文 JSON 语言包（`src/client/i18n/zh.json`, `en.json`）
- [ ] QR + Admin + App 三页面文案替换
- [ ] 语言切换 UI（admin 已有按钮框架）
- [ ] localStorage 持久化 `oc-lang`
- [ ] 日期/数字格式本地化

### P4. 在线体验 Demo 页（3 天）
- [ ] 新建 `src/client/demo.html`
- [ ] 录屏 GIF/视频展示核心功能（语音交互/微信/桌面控制/人机协作）
- [ ] 交互式模拟聊天界面（纯前端演示）
- [ ] 功能对比表（vs 其他同类产品）
- [ ] 下载按钮 + GitHub Star 按钮
- [ ] 响应式（移动端可看）

### P5. UI 细节打磨（1 天）
- [ ] app.html 聊天界面长消息折叠/展开
- [ ] 微信面板回复速度图表（sparkline）
- [ ] Admin 页面加载骨架屏（skeleton loading）
- [ ] 所有面板空状态插图

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

## 需要 Claude Code 提供的新 API

| API | 用途 | 我方消费位置 | 状态 |
|-----|------|-------------|------|
| `POST /api/intent/signal` | 发送多模态信号 | P0 意图面板 | ⏳ Claude 开发中 |
| `GET /api/intent/state` | 融合状态查询 | P0 意图面板 | ⏳ Claude 开发中 |
| `GET /api/system/update-check` | 检查更新 | P1 更新通知 | ⏳ Claude 开发中 |

## 已有可直接用的 API（无需等待）

| API | 用途 |
|-----|------|
| 所有 v4.0.0 API | P2/P3/P4/P5 不依赖新 API |
