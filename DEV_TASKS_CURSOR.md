# Cursor 开发任务清单

> 负责：前端 UI/UX + 组件开发 + 可视化 + 用户交互
> 不做：后端 Python 逻辑、数据库、微信引擎（Claude Code 负责）

## 阶段 1（本周）

### 1.1 校准向导 UI（2天）
- [ ] 新建 `src/client/js/calibration.js`
- [ ] 眼球追踪 5 点校准界面
  - 全屏深色背景 + 5 个闪烁圆点（四角+中心）
  - 用户注视每个点 2 秒，前端记录 gaze-tracker.js 的原始数据
  - 完成后调用 gaze-tracker.js 的 `calibrate(points)` 方法
  - 显示校准精度分数
- [ ] 入口: 设置面板 → 无障碍 → "校准眼球追踪"按钮
- [ ] 已有代码参考: `src/client/js/gaze-tracker.js` 的 `calibrate()` 方法

### 1.2 手势绑定配置 UI（3天）
- [ ] 新建 `src/client/js/gesture-bindings.js`
- [ ] 在设置面板新增"手势绑定"区域
- [ ] 展示当前所有手势→动作映射（从 expression-system.js 读取）
- [ ] 可编辑：下拉选择目标动作
- [ ] 保存到 `POST /api/access/config`（后端已有）
- [ ] 预览：点击手势名称，摄像头区域高亮对应面部区域
- [ ] 已有代码参考: `src/client/js/expression-system.js` 的 ACTION_MAP

### 1.3 CoworkBus 状态面板（2天）
- [ ] 在 app.html 头部添加"协作状态指示器"
  - 小图标: 🟢 AI 空闲 / 🔵 AI 工作中 / 🟡 用户活跃(AI 暂停) / 🔴 冲突
  - 点击展开面板: 当前任务列表、操作日志
- [ ] 调用 API: `GET /api/cowork/status`（Claude Code 开发）
- [ ] 调用 API: `GET /api/cowork/journal`（Claude Code 开发）
- [ ] 撤销按钮: 调用 `POST /api/cowork/undo`
- [ ] 暂停/恢复按钮: 调用 `POST /api/cowork/pause` / `resume`

## 阶段 2（下周）

### 2.1 操作日志时间线（3天）
- [ ] 新建 `src/client/js/action-timeline.js`
- [ ] 可视化 AI 操作历史
  - 竖向时间线：每个操作一个节点
  - 节点内容: 操作类型图标 + 描述 + 时间 + 前后截图对比
  - 点击节点展开详情
  - "撤销到这里"按钮
- [ ] 数据来源: `GET /api/cowork/journal`

### 2.2 MCP 工具市场 UI（3天）
- [ ] 在设置面板新增"插件市场"区域
- [ ] 展示已安装 MCP Server 列表（从 `/api/mcp/desktop-tools`）
- [ ] 每个工具卡片: 名称 + 描述 + 启用/禁用开关
- [ ] "添加 MCP Server"按钮: 输入 URL 或选择预置
- [ ] 工具测试: 选择工具 → 输入参数 → 执行 → 显示结果

### 2.3 数据分析图表（2天）
- [ ] 微信管理面板 → 数据分析区域
- [ ] 纯 CSS 图表（不引入 Chart.js）：
  - 每日回复数柱状图（最近 7 天）
  - 时段分布热力图（24 小时 × 颜色深浅）
  - 活跃好友 Top5 横向条
- [ ] 数据来源: `GET /api/analytics/*`（后端已有）

## 阶段 3（后续）

### 3.1 在线体验页
- [ ] 新建 `src/client/demo.html`
- [ ] 无需安装的功能展示页
  - 录屏 GIF/视频展示核心功能
  - 交互式 Demo（模拟聊天界面）
  - 功能对比表
  - 下载按钮
- [ ] 响应式设计（移动端可查看）

### 3.2 移动端适配优化
- [ ] chat.html 移动端 UI 优化
- [ ] 触摸手势支持（滑动切换面板）
- [ ] PWA 离线体验增强

---

## 开发规范

- 所有新 JS 文件放在 `src/client/js/` 目录
- 使用 ES Module (import/export)
- 从 `state.js` 导入共享状态
- 不引入新的 npm 依赖（纯原生 JS + CSS）
- 调用后端 API 时用 `fetch()`，不用 axios
- CSS 用 CSS Variables (已定义在 app.html 的 :root 中)
- 新面板参考 settings-wechat.js 的面板模式
