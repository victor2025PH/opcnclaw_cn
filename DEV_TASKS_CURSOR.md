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

### P0. 意图融合面板 UI（2 天）— ✅ 已完成
- [x] 新建 `src/client/js/intent-panel.js`（ES Module）
- [x] app.html 头部 `🧠` 按钮 + 下拉面板（样式对齐 CoworkBus）
- [x] 五通道展示（注视 gaze / 表情 expression / 语音 voice / 触控 touch / 桌面 desktop）+ 各通道最近信号
- [x] 当前融合结果：`current_intent` + 置信度进度条 + 跨模态增强提示
- [x] 500ms 窗口 SVG 时间线（各通道圆点）
- [x] 紧急停止：`POST /api/intent/emergency`
- [x] `GET /api/intent/state` 每 2 秒轮询；开发区折叠：`POST /api/intent/signal` 测试（点头/语音/触控）
- [x] `settings.js` 中 `initIntentPanel()`；溢出菜单入口

### P1. 更新通知 UI（0.5 天）— ✅ 已完成
- [x] QR 启动：`GET /api/update/check`，失败回退 `GET /api/system/update-check`（后端已加别名路由）
- [x] 有更新时顶部绿色横幅：版本号 + changelog 摘要 + GitHub Releases
- [x] 「忽略此版本」→ `localStorage` `oc-update-dismiss`
- [x] 仅在线时检查；与离线横幅分层（z-index）

### P2. 移动端 PWA 增强（1 天）— ✅ 已完成
- [x] QR 页面注册 Service Worker（`qr-sw.js`，缓存版本 `oc-qr-v2`）
- [x] `qr-manifest.json`（图标 + 主题色 + standalone + shortcuts）
- [x] 离线：`/api/events` 等 API 网络优先+缓存回退；活动列表 `localStorage` 持久化 + 离线横幅
- [x] `beforeinstallprompt` 添加到主屏幕提示条（已有）
- [x] SW 预缓存 `/i18n/*.json` 供离线文案

### P3. 国际化 (i18n) 架构（2 天）— ✅ 已完成
- [x] `src/client/js/i18n.js`：`initI18nBundles`、`applyDataI18n`、`formatDate`/`formatNumber`（Intl）
- [x] `src/client/i18n/zh.json`、`en.json`（QR 主文案 + Admin nav 键 + wx 统计标签等）
- [x] App：`initI18nBundles()` 在 `initState` 之前执行，合并进 `state.js` 的 `I18N`
- [x] QR：`data-i18n` + 底部 EN/中文 切换（`oc-lang` / `oc_lang` 双写）
- [x] Admin：`loadI18n` 先拉本地 JSON，再合并后端 `/api/i18n/translations`（可选）
- [x] `state.js`：`mergeI18nBundles`、`currentLang` 读取 `oc-lang`

### P4. 在线体验 Demo 页（3 天）— ✅ 已完成（MVP）
- [x] `src/client/demo.html`：Hero + 功能卡片 + 纯前端模拟聊天 + 对比表 + CTA
- [x] `GET /demo`、`GET /demo/` → `FileResponse`（`main.py`）
- [x] QR 导航增加「在线体验」→ `/demo`；GitHub Star 外链
- [ ] 后续可选：嵌入 GIF/视频、多语言、与 `version.txt` 联动下载链接

### P5. UI 细节打磨（1 天）— ✅ 已完成
- [x] `chat.js`：长消息（≥720 字）折叠 +「展开全文/收起」
- [x] 微信面板：`#wxp-reply-spark` SVG 折线（今日回复增量趋势，轮询采样）
- [x] Admin：`refreshDashboard` 请求期 `stat-cards.skeleton-loading` 骨架闪烁动画
- [x] 空状态：`.empty` 增强（更大 emoji、副标题 `sub`）；工作流/执行记录等补充说明文案

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
| `POST /api/intent/signal` | 发送多模态信号 | P0 意图面板 | ✅ |
| `GET /api/intent/state` | 融合状态查询 | P0 意图面板 | ✅ |
| `POST /api/intent/emergency` | 紧急停止 | P0 意图面板 | ✅ |
| `GET /api/update/check` | 检查更新（主） | P1 QR 横幅 | ✅ |
| `GET /api/system/update-check` | 检查更新（别名） | P1 回退 | ✅ |

## 已有可直接用的 API（无需等待）

| API | 用途 |
|-----|------|
| 所有 v4.0.0 API | P2/P3/P4/P5 不依赖新 API |
