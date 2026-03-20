# Claude Code 开发任务清单

> 负责：后端核心 + 数据层 + 微信引擎 + 测试
> 不做：前端 UI 组件、CSS 样式、HTML 模板（Cursor 负责）

## 阶段 1（本周）

### 1.1 HumanDetector 合并（3天）
- [ ] 创建 `src/server/human_detector.py`
- [ ] 从 desktop.py 提取窗口/鼠标活动检测逻辑
- [ ] 从 event_bus.py 提取键盘输入检测
- [ ] 集成 gaze-tracker 的注视方向（通过 WebSocket 接收前端数据）
- [ ] API: `GET /api/cowork/human-status` 返回 {active_window, mouse_idle_ms, typing, gaze_zone}
- [ ] 单元测试: `tests/test_human_detector.py`

### 1.2 Action Journal 操作日志（1周）
- [ ] 创建 `src/server/action_journal.py`
- [ ] 数据模型: ActionEntry {id, action_type, params, before_screenshot, after_screenshot, timestamp, reversible}
- [ ] 记录所有 desktop.py 的操作（click/type/hotkey/scroll）
- [ ] 截图对比：操作前后各截一张缩略图
- [ ] 撤销接口: `undo_last()` → 执行反向操作（Ctrl+Z / 恢复位置）
- [ ] API: `GET /api/cowork/journal` 返回最近操作列表
- [ ] API: `POST /api/cowork/undo` 撤销最后一步
- [ ] 数据库: main.db 新增 `action_journal` 表
- [ ] 自动清理: 保留最近 100 条，超过自动删除截图

### 1.3 CoworkBus 协作调度（2周）
- [ ] 创建 `src/server/cowork_bus.py`
- [ ] WorkZone: 定义"谁在用哪个窗口"（human / ai / idle）
- [ ] 冲突检测: AI 要操作的窗口 == 用户当前活跃窗口 → 暂停
- [ ] 任务队列: BackgroundTask {id, description, target_window, status, priority}
- [ ] 调度策略:
  - 用户活跃 → AI 暂停桌面操作，只做后台计算（AI回复/分析）
  - 用户空闲 > 30s → AI 可以操作桌面
  - 用户回来 → AI 立即暂停，保存进度
- [ ] API: `POST /api/cowork/task` 创建后台任务
- [ ] API: `GET /api/cowork/status` 返回 {human_zone, ai_zone, queue}
- [ ] API: `POST /api/cowork/pause` / `POST /api/cowork/resume` 手动控制
- [ ] 集成 HumanDetector 判断用户状态

## 阶段 2（下周）

### 2.1 后台任务模式
- [ ] desktop.py 新增 `execute_background()` 方法
- [ ] 执行时最小化目标窗口，完成后恢复
- [ ] 任务进度通过 WebSocket 推送到前端
- [ ] 超时保护: 单个任务最多 5 分钟

### 2.2 MCP Server 标准化
- [ ] 将 mcp_desktop_tools.py 独立为标准 MCP Server 进程
- [ ] 支持 stdio/HTTP 两种传输
- [ ] 注册到 MCP Server Registry
- [ ] 微信操作打包为 MCP 工具 (wechat_read, wechat_send, wechat_moments)

### 2.3 微信引擎优化
- [ ] DB Reader 密钥提取适配微信 4.x 内存结构
- [ ] wxauto 4.x 兼容层完善
- [ ] 朋友圈滚动+多页读取
- [ ] 评论链自动跟进实测

## 阶段 3（后续）

### 3.1 测试补全
- [ ] tests/test_wechat_adapter.py — Mock UIA 测试轨道切换
- [ ] tests/test_cowork_bus.py — 冲突检测/调度测试
- [ ] tests/test_action_journal.py — 记录/撤销测试
- [ ] tests/test_moments.py — Vision AI 结果解析测试

### 3.2 性能监控
- [ ] API: `GET /api/metrics` 返回各组件延迟/吞吐
- [ ] FTS5 搜索延迟、Vision AI 调用次数、微信消息处理延迟

---

## 开发规范

- 所有新模块通过 `db.py` 访问数据库
- 异步优先 (async/await)
- 中文注释
- 每个模块配套 pytest 测试
- API 端点在 routers/ 目录，业务逻辑在 server/ 目录
