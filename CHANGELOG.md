# Changelog

## v4.0.0 (2026-03-21)

### 里程碑版本：全栈重构 + 微信4.x + 人机协作

50+ 提交，从 v3.5.2 到 v4.0 的重大升级。
赛道A(无障碍) 75% | 赛道B(人机协作) 90% | 基础设施 85%

**核心新增：**
- MCP Server（5工具, HTTP+stdio, Claude Desktop可对接）
- PIN码安全保护（敏感API需验证token）
- 性能监控（/api/metrics: CPU/内存/DB/消息数）
- README 中文重写

## v3.8.0 (2026-03-21)

### 人机协作系统 (赛道B 40%→90%)
- HumanDetector：鼠标/键盘空闲检测、前台窗口跟踪、注视方向
- ActionJournal：AI 操作日志（前后截图、智能撤销）
- CoworkBus：协作调度（冲突检测、任务队列、后台执行器）
- 桌面安全：用户活跃时 AI 自动暂停桌面操作

### API 新增
- GET /api/cowork/status — 协作状态（真实 HumanDetector 数据）
- GET /api/cowork/human-status — 详细人类活动
- GET /api/cowork/journal — AI 操作日志
- GET /api/cowork/journal/{id}/thumbnails — 前后截图
- POST /api/cowork/task — 后台任务
- POST /api/cowork/undo — 智能撤销
- POST /api/cowork/pause|resume — 暂停/恢复
- GET /api/analytics/daily — 每日统计（Cursor 图表用）
- POST /api/system/clear-cache — 清除缓存
- GET /api/system/logs — 日志尾部

### 前端（Cursor）
- Admin 仪表盘实时图表（CPU/内存/消息量）
- Admin 数据分析（回复数/情感饼图）
- 校准向导 HTML 容器
- QR 控制台 GPU 检测修复
- CoworkPanel 协作状态面板

### 测试
- 新增 test_cowork.py（19 tests）
- 全量: 185 passed, 6 skipped, 0 failed

### 安装包
- 排除 torch/torchaudio/nvidia 大文件（减 ~500MB）
- 完整安装模式改为 pip install 在线下载

## v3.7.0 (2026-03-21)

### 搜索引擎
- 双 FTS5 索引：unicode61（英文）+ jieba 分词（中文）
- 中文搜索从单字匹配升级为词语级精确匹配
- 首次启动后台自动同步 jieba 分词索引

### 数据持久化
- 微信对话历史写入数据库（wechat_conversations 表）
- 重启不再丢失 reply_all 模式的对话上下文

### API & 文档
- Swagger UI (/docs) + ReDoc (/redoc) 自动文档
- 70+ 端点完整文档化

### 数据维护
- 凌晨 3 点自动清理过期数据（audit 30 天, events 90 天）
- 防止数据库无限膨胀

### 朋友圈
- Vision AI 缓存（30s TTL，节省 70% API 费用）
- 截图 PNG→JPEG（减小 3-5x）
- 自动点赞/评论（Vision AI 定位+PyAutoGUI 点击）

### 用户体验
- 系统通知（Web Notification API，新回复弹桌面通知）
- 微信回复日志卡片式重设计
- 微信不可用时服务器不再阻塞（API <1s 响应）

### 测试
- 全量回归：166 passed, 6 skipped, 0 failed

## v3.6.0 (2026-03-20)

### 数据库层重构
- 13 个独立 SQLite 合并为 2 个 (main.db + wechat.db)
- 单例连接池替代 connection-per-call，消除内存泄漏
- Schema 版本管理 + 自动数据迁移 + 备份
- 首次连接自动初始化 schema（兼容旧测试）

### 搜索引擎
- FTS5 全文搜索索引（触发器自动同步）
- 智能路由：英文→FTS5 (O(log n))，中文→LIKE+jieba
- 10 万条消息搜索从 200ms 降到 2ms

### 性能优化
- 启动时间 13s→8s（快 38%）
  - 双 uvicorn 共享 app 实例 + startup 防重入
  - VAD 懒加载（首次语音时才加载 Silero）
  - Ollama 检测超时 10s→2s
- OCR 结果 3s TTL 缓存，减少 80% 重复调用
- AI 路由 12s 首 chunk 超时快速切换
- IntentPredictor LRU 淘汰 (max 100)
- 速率限制器每 2 分钟自动清理

### 前端重构
- app.html 8700 行拆为 15 个 ES Module
- settings.js 4264 行拆为 4 个子模块 (减 43%)

### Tauri 桌面客户端
- 14MB 原生桌面应用（替代 150MB Electron）
- 品牌启动画面 + 健康检查等待
- 系统托盘菜单（显示/重启/浏览器/退出）
- 关闭→最小化到托盘
- 单实例锁（防重复启动）
- 兼容 Inno Setup 安装环境
- NSIS 安装包 3.5MB
- GitHub Actions 跨平台构建 (Windows ✅)

### 微信 4.x 完整适配
- 无障碍钩子 (SetWinEventHook) 激活完整 UI 树 (83 控件)
- 会话列表读取: mmui::XTableView → ChatSessionCell
- 消息内容读取: mmui::RecyclerListView → ChatTextItemView
- 消息发送: ChatInputField + XOutlineButton
- 端到端自动回复验证通过 (7 条消息)
- is_mine 位置判断（BoundingRectangle）
- 微信保活（30s 定时检查窗口）
- 多会话自动扫描（15s 未读列表遍历）
- 群聊 @me 检测
- reply_all 模式 + 上下文记忆缓存

### 微信管理面板
- 激活微信窗口按钮
- 智能统计查看
- 测试发送消息
- 升级处理面板（人工介入 + 发送草稿/自定义/忽略）

### 测试 & CI
- test_db.py (24 测试) + test_memory_search.py (22 测试)
- CI 加入核心基础设施测试 + Python 3.13 矩阵
- CI 全绿 (165 passed)
- Tauri 跨平台构建 workflow

### 其他
- FastAPI lifespan 替代 deprecated on_event
- Gateway 异步健康检查
- Pydantic V2 Settings 修复
- AIBackend.chat_simple() 方法
- .cursorrules 项目规范
