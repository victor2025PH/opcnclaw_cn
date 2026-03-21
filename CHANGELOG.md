# Changelog

## v5.2.0 (2026-03-22)

### Agent 交互重构
- 先问再做：AI 先收集需求（产品/预算/目标），不直接部署团队
- Agent 逐一报到：每个 Agent 自我介绍"老板好！我是XX，负责XX"
- 确认后执行：deploy_team(组建) → confirm_team(执行) 两步走
- 团队完成自动通知：聊天区 5 秒轮询，完成时自动追加结果卡片

### Agent 智能分配
- 自动检测已配置 AI 平台（Key 状态检测）
- 轮询分散 Agent 到不同平台（减少限速）
- 无 Key 平台明确提醒用户配置
- 省钱模式提醒切换"质量优先"

### Agent 容错
- 单个 Agent 失败不阻塞团队（降级为默认回答）
- 团队历史持久化到 SQLite（重启不丢失）

### 桌宠小龙虾
- SVG 小龙虾造型（钳子/眼睛/触角/嘴巴/脚）
- 6 种状态动画（晃动/膨胀/摆头/跳动/张嘴/抖动）
- 双击弹出输入面板（4 个快捷任务 + 输入框）
- 右键菜单（聊天/团队状态/快速任务/管理/设置）
- 团队调度全流程（组建→进度→结果→复制）
- 透明无边框窗口 140×200，不在任务栏显示

### UI 优化
- 欢迎页重塑为"AI团队"入口（6 个团队任务 + 4 个快捷操作）
- 顶栏精简 14→4 个按钮（其余收进溢出菜单）
- 底部工具栏加大（14px/500weight）
- 聊天区滚动修复（flex-in-grid min-height:0）
- 溢出菜单响应修复（hdr-extra class 替代 !important）
- 输入框提示词："告诉AI团队你想做什么..."

### 托盘菜单统一
- Tauri 和 Python 托盘菜单完全一致（15 项）
- 新增：手机扫码/聊天/设置/管理面板入口

### 安装包
- 快捷方式修复（start.bat 替代缺失的 Tauri exe）
- 离线依赖包（68 个 wheel，无需联网安装）
- Tauri exe 文件大小检测（>1MB 才启动）
- 工具总数：24（含 deploy_team/confirm_team/check_team_result）

## v5.0.0 (2026-03-21)

### 一键 Agent 团队（核心创新）
- 13 个 Agent 角色：CEO/研究员/写手/程序员/分析师/设计师/运营/客服/翻译/财务/法务/助理/导师
- 7 个预置团队模板：创业/内容/技术/营销/学习/商务/全员
- 每个 Agent 绑定不同 AI 平台（智谱/DeepSeek/百度）
- CEO 自动拆解任务 → 并行分发 → 汇总审核
- Agent 间消息总线 + 实时状态追踪
- API: POST /api/agents/team/create, /execute, /status, /messages, /result

### 文件双向传输（手机 ↔ 电脑）
- 手机上传文件到电脑（自动保存到桌面）
- 电脑推送文件到手机（下载链接）
- 大文件上限 500MB，24h 自动清理
- API: POST /api/files/upload, GET /api/files/list, GET /api/files/{id}/download

### 手机远程控制电脑
- remote.html: 全屏远程桌面页面
- 触控映射：单击/长按右键/双指滚轮/三指切窗口
- 虚拟键盘：快捷键栏(Ctrl+C/V/Z, Alt+Tab, Esc)
- 剪贴板双向同步
- 文件拖拽上传
- API: POST /api/remote/clipboard, GET /api/remote/status

### 测试
- 新增 test_agent_team.py（24 tests）
- 全量: 407 passed, 6 skipped

## v4.4.0 (2026-03-21)

### CI/CD 自动化
- GitHub Actions 测试覆盖全模块（排除 boot_test/server/benchmark）
- Python 3.10-3.13 矩阵测试
- 测试失败时 CI 直接标红，不再 continue-on-error

### 安装包修复
- Tauri exe 改为可选依赖（skipifsourcedoesntexist）
- 无 Rust 环境也能编译安装包（纯 Python 模式，147MB）

### 插件市场前端
- plugin-market.js: 插件列表+搜索+启用/禁用 toggle
- 基于已有 /api/plugins API

### 工作流编辑器集成
- workflow-editor.js 挂载到 admin 页面

## v4.3.0 (2026-03-21)

### 语音唤醒优化
- Silero VAD 预过滤：静音→能量检测→VAD→只有真人语音才送 STT
- 减少 90% 无用 STT 调用，降低延迟和 API 成本
- 唤醒词命中专用日志（区分 INFO 和 DEBUG 级别）

### 多语言 TTS 自动切换
- 8 种语言自动检测：中/英/日/韩/法/德/西/俄
- 按文本字符比例选择对应 Edge TTS 声音
- 混合文本按多数语种决定（如"今天weather很好"→中文声音）
- 纯数字/极短文本回退到用户配置的默认声音

### 声纹轻量化（v4.2 修复）
- resemblyzer(torch 2GB) → MFCC(numpy 10MB)
- 测试速度 36s → 0.6s，内存占用降低 200 倍
- 实测：3 用户注册+切换+识别全部通过

### 测试
- 新增 test_tts_lang.py（8 tests）
- 全量: 371 passed, 6 skipped, 0 failures

## v4.2.0 (2026-03-21)

### 声纹识别 + 多用户系统
- resemblyzer d-vector 声纹编码器（256维，CPU 可运行）
- 用户注册：3句话采集 → 平均 embedding → 余弦相似度匹配（阈值 0.75）
- 多用户隔离：每人独立记忆/偏好/人设
- 前端：用户头像按钮 + 下拉切换 + 注册向导（录音+波形动画）
- API: GET /api/users, POST /api/users/register, GET /api/users/current

### 离线模式
- 30s 心跳网络检测，3级状态（online/local/offline）
- 断网自动切换 Ollama 本地模型（优先 qwen2.5）
- EventBus 发布 network_mode_change 事件
- API: GET /api/system/network-status

### 工作流 RESTful API
- 完整 CRUD 别名：GET/POST /api/workflows, PUT /api/workflows/{id}
- 手动执行：POST /api/workflows/{id}/run
- 执行历史：GET /api/workflows/{id}/history

### IoT 智能家居
- HomeAssistant REST API 桥接（设备发现/状态/控制）
- 按名称模糊查找设备
- iot_control 工具集成（AI说"关灯"即可执行）
- API: GET /api/iot/devices, POST /api/iot/control, POST /api/iot/config

### Web Push 推送
- 订阅管理 + 测试推送
- API: POST /api/push/subscribe, GET /api/push/status, POST /api/push/test

### 测试
- 新增 test_speaker_id.py（18 tests）+ test_offline.py（4 tests）
- 工具总数: 20→21 (新增 iot_control)

## v4.1.0 (2026-03-21)

### 意图融合引擎（多模态信号融合）
- 四通道信号融合：注视(gaze) + 表情(expression) + 语音(voice) + 桌面(desktop)
- 500ms 滑动窗口 + 优先级排序：紧急停止 > 语音 > 手势 > 情感
- 跨模态增强矩阵：点头+"好"=2x置信度，摇头+"不"=2x
- 紧急停止立即响应（不等融合窗口）→ CoworkBus 自动暂停
- 在线配置调整：窗口/阈值/置信度无需重启
- API: POST /api/intent/signal, GET /api/intent/state, POST /api/intent/emergency

### A2A 协议（Agent-to-Agent 通信）
- Google A2A 标准兼容的 Agent Card 发现（/.well-known/agent.json）
- 任务生命周期管理：submitted → working → completed/failed
- 5 个内置技能处理器：wechat_send/read, screenshot, ocr, voice
- 桌面操作任务自动委派 CoworkBus 调度
- Webhook 异步通知 + EventBus 事件广播
- Claude Desktop / Cursor 可通过 A2A 委派桌面操作
- API: POST /api/a2a/task, GET /api/a2a/card, GET /api/a2a/tasks

### 微信引擎增强
- 朋友圈多页浏览：browse_pages() 自动滚动+去重+到底检测
- 混合滚动策略：前3页滚轮（平滑）→ 之后 PageDown（可靠）
- 截图对比到底检测：像素级相似度 > 95% = 到底
- 消息类型扩展至 13 种：链接/小程序/引用/表情包/位置/名片/转账/红包等
- @检测精确匹配：优先匹配 OPENCLAW_WECHAT_NICKNAME，回退泛匹配
- 新增 _check_at_anyone() 提取所有被@的人列表

### 测试
- 新增 test_intent_fusion.py（36 tests）
- 新增 test_a2a.py（33 tests）
- 全量: 306 passed, 6 skipped, 0 failed (新模块)

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
