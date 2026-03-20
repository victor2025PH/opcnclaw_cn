# Changelog

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
