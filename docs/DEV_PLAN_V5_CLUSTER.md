# 十三香小龙虾 v5.1 — 无限扩展 + 多机协同方案

> 2026-03-21 | 深度思考版
>
> 核心目标：用户自定义 Agent + 无限规模团队 + 多台电脑分布式协作

---

## 一、整体架构

```
                        ┌─────────────────────┐
                        │   调度中心 (Master)    │
                        │   任意一台十三香电脑    │
                        │                     │
                        │   ┌───────────────┐ │
                        │   │  TeamOrchestrator│ │
                        │   │  任务拆解+分发   │ │
                        │   │  进度汇总+结果  │ │
                        │   └───────┬───────┘ │
                        └───────────┼─────────┘
               ┌────────────────────┼────────────────────┐
               │                    │                    │
        ┌──────▼──────┐      ┌──────▼──────┐      ┌──────▼──────┐
        │  电脑A (本机)  │      │  电脑B (远程)  │      │  电脑C (远程)  │
        │  Worker Node │      │  Worker Node │      │  Worker Node │
        │              │      │              │      │              │
        │  Agent 1-5   │      │  Agent 6-10  │      │  Agent 11-15 │
        │  本地AI+工具  │      │  本地AI+工具  │      │  本地AI+工具  │
        │  桌面操作能力  │      │  桌面操作能力  │      │  桌面操作能力  │
        └──────────────┘      └──────────────┘      └──────────────┘

每台电脑是一个 Worker Node，拥有完整的十三香小龙虾能力。
Master 把子任务分发到不同 Worker，Worker 执行后汇报结果。
```

---

## 二、三层扩展设计

### 第 1 层：自定义 Agent（无限角色）

```
用户可以自己创建任意角色：

  POST /api/agents/roles/create
  {
    "name": "产品经理",
    "avatar": "📱",
    "description": "需求分析、产品规划、用户故事编写",
    "system_prompt": "你是一个资深产品经理，擅长...",
    "preferred_model": "deepseek-chat",
    "tools": ["desktop_screenshot", "send_wechat"],
    "tags": ["产品", "管理"]
  }

预置 13 个 + 用户自定义无限个 = 无限角色库
角色持久化到 data/agent_roles.json
支持导入/导出（分享给其他用户）
```

**角色模板市场**（未来）：
- 用户创建的优秀角色可以发布到市场
- 其他用户一键导入
- 按行业分类：电商/教育/医疗/金融/法律/...

### 第 2 层：无限规模团队（单机）

```
当前限制：13 Agent（= 13 个预置角色）
扩展后：无上限（取决于 AI 平台并发）

优化策略：
  - 分批执行：50 个 Agent → 每批 10 个并行 → 5 批
  - 平台分散：Agent 1-5 走智谱, 6-10 走百度, 11-15 走 DeepSeek
  - 队列管理：令牌桶限流，避免触发平台封禁
  - 优先级调度：CEO/关键 Agent 优先执行
```

**并发能力估算**：

| AI 平台 | 免费限速 | 可承载 Agent 数 |
|--------|---------|---------------|
| 智谱 GLM-4-Flash | 5次/秒 | 5 |
| 百度文心 | 5次/秒 | 5 |
| 硅基流动 | 3次/秒 | 3 |
| DeepSeek | 2次/秒 | 2 |
| 通义千问 | 3次/秒 | 3 |
| Ollama 本地 | 无限 | 取决于 GPU/CPU |
| **合计** | **18次/秒** | **18+ 并行** |

单机实际承载：**30-50 个 Agent**（分批+排队），全部免费。

### 第 3 层：多机协同（分布式集群）

```
核心思想：
  每台装了十三香的电脑 = 一个 Worker Node
  每个 Worker 有自己的 AI 平台配额 + 桌面操作能力
  Master 统一调度 → Worker 各自执行 → 汇总结果

场景举例：
  10 台电脑 × 18次/秒 = 180 次/秒 AI 调用
  10 台电脑 × 50 Agent = 500 Agent 并行
  每台电脑可以操作自己的桌面（分布式桌面自动化）
```

---

## 三、多机协同协议

### 3.1 节点发现

```
方案 A（局域网）：UDP 广播发现
  - 每台十三香启动时广播 "OPENCLAW_HELLO" 到 UDP 8770
  - 其他节点收到后注册到节点列表
  - 心跳检测：每 30 秒 ping 一次

方案 B（跨网络）：中心注册
  - 用户在 Master 上手动添加 Worker 的 IP:Port
  - 或者所有节点注册到云端协调服务

推荐：先实现方案 A（局域网自动发现），后续加方案 B
```

### 3.2 通信协议

```
基于 HTTP API（复用已有的 A2A 协议）：

Master → Worker:
  POST http://worker-ip:8766/api/cluster/task
  {
    "task_id": "t123",
    "agent_role": {...},      // Agent 角色定义
    "task_description": "...", // 子任务描述
    "context": {...},          // 共享上下文
    "timeout": 300
  }

Worker → Master:
  POST http://master-ip:8766/api/cluster/result
  {
    "task_id": "t123",
    "worker_id": "worker-B",
    "status": "done",
    "result": "...",
    "duration_ms": 12345
  }
```

### 3.3 任务分配策略

```python
class ClusterScheduler:
    """多机任务调度器"""

    def distribute(self, tasks: List[SubTask], workers: List[Worker]):
        """智能分配策略"""

        # 策略 1: 负载均衡
        #   统计每个 Worker 当前执行中的任务数
        #   优先分配给空闲的 Worker

        # 策略 2: 能力匹配
        #   需要桌面操作的任务 → 有桌面的 Worker
        #   需要特定 AI 平台的 → 有该平台 Key 的 Worker
        #   需要大内存/GPU 的 → 硬件更强的 Worker

        # 策略 3: 就近原则
        #   访问本机文件的任务 → 本机 Worker
        #   网络延迟低的 Worker 优先

        # 策略 4: 故障转移
        #   Worker 超时 → 自动重试到其他 Worker
        #   Worker 断线 → 任务重新分配
```

### 3.4 数据同步

```
共享数据（Master 管理）：
  - 任务描述和上下文
  - Agent 间消息
  - 最终汇总结果

不共享数据（各 Worker 本地）：
  - 桌面截图
  - 本地文件
  - AI 对话历史

同步机制：
  - 任务结果实时上报（HTTP POST）
  - 大文件通过文件传输 API（/api/files/push）
  - EventBus 事件通过 WebSocket 跨节点广播
```

---

## 四、实现方案

### 4.1 后端新增模块

| 文件 | 内容 | 工期 |
|------|------|------|
| `src/server/agent_custom.py` | 自定义角色 CRUD + 持久化 + 导入导出 | 1天 |
| `src/server/cluster.py` | 多机集群核心：节点管理+任务分发+结果收集 | 2天 |
| `src/server/cluster_discovery.py` | 局域网 UDP 自动发现 | 1天 |
| `src/server/routers/cluster.py` | 集群 API 路由 | 1天 |
| 修改 `agent_team.py` | 支持大规模团队+分批执行+集群分发 | 1天 |

### 4.2 API 设计

```
# ── 自定义角色 ──
POST   /api/agents/roles/create     # 创建自定义角色
PUT    /api/agents/roles/{id}       # 编辑角色
DELETE /api/agents/roles/{id}       # 删除角色
POST   /api/agents/roles/import     # 导入角色（JSON）
GET    /api/agents/roles/export     # 导出所有角色

# ── 自定义团队 ──
POST   /api/agents/team/custom      # 自定义团队（指定角色列表）
PUT    /api/agents/templates/{id}   # 编辑团队模板
POST   /api/agents/templates/create # 创建自定义模板

# ── 集群管理 ──
GET    /api/cluster/nodes           # 节点列表
POST   /api/cluster/nodes/add       # 手动添加节点
DELETE /api/cluster/nodes/{id}      # 移除节点
GET    /api/cluster/status          # 集群状态（总算力/在线节点/任务队列）
POST   /api/cluster/discover        # 触发局域网发现

# ── 集群任务 ──（Worker 端）
POST   /api/cluster/task            # 接收 Master 分发的任务
POST   /api/cluster/result          # 上报任务结果
GET    /api/cluster/worker/status   # 本机 Worker 状态
```

### 4.3 前端新增

| 文件 | 内容 | 工期 |
|------|------|------|
| `src/client/js/agent-custom.js` | 角色创建/编辑器 + 拖拽组队 | 2天 |
| `src/client/js/cluster-panel.js` | 集群管理面板（节点列表+状态+一键发现） | 1天 |
| 修改 `agent-team-panel.js` | 支持大规模团队状态显示 | 1天 |

---

## 五、使用场景

### 场景 1：个人创业者（1 台电脑）

```
用户创建自定义角色：产品经理、测试工程师、UI 设计师
组建 8 人产品团队 → 一键执行
"帮我做一个宠物社交APP的产品方案"
→ 8 个 Agent 并行工作 → 3 分钟输出完整 PRD
```

### 场景 2：小团队（3 台电脑，同一 WiFi）

```
电脑A（Master）：CEO + 产品经理 + 分析师
电脑B：程序员 × 3（前端/后端/测试）
电脑C：设计师 + 运营 + 客服

"开发一个电商小程序"
→ Master 拆解 9 个子任务
→ 分发到 3 台电脑
→ 各自执行 + 实时同步
→ 15 分钟输出：需求文档 + 技术方案 + 设计稿 + 推广计划
```

### 场景 3：公司部署（10 台电脑）

```
每台电脑负责不同业务线：
  电脑 1-2：客服团队（自动回复微信/邮件）
  电脑 3-4：内容团队（自动生成文章/视频脚本）
  电脑 5-6：数据团队（自动分析报表/生成图表）
  电脑 7-8：研发团队（代码审查/Bug 分析）
  电脑 9-10：备用节点（故障转移）

→ 50+ Agent 7×24 小时自动工作
→ Master 统一监控 + 任务分配
→ 故障自动转移，零停机
```

### 场景 4：分布式桌面自动化

```
任务："在 10 台电脑上同时注册 10 个测试账号"
→ Master 拆解为 10 个子任务
→ 每台电脑的 Agent 操控自己的浏览器
→ 同时注册 → 10 分钟完成（单机需 100 分钟）

任务："把 1000 个文件分类整理到不同文件夹"
→ 分成 10 份 × 100 个
→ 每台电脑处理 100 个
→ 并行完成
```

---

## 六、排期

### 第 1 周：自定义角色 + 大规模团队

| 天 | 任务 |
|---|------|
| D1 | `agent_custom.py`: 角色 CRUD + JSON 持久化 + 导入导出 |
| D2 | 修改 `agent_team.py`: 分批执行 + 令牌桶限流 + 50 Agent 支持 |
| D3 | `agent-custom.js`: 角色创建/编辑器前端 |
| D4 | 自定义团队模板 API + 测试 |
| D5 | 集成测试 + 20 Agent 大规模团队实测 |

### 第 2 周：多机协同

| 天 | 任务 |
|---|------|
| D6 | `cluster.py`: 节点管理 + 任务分发 + 结果收集 |
| D7 | `cluster_discovery.py`: UDP 局域网自动发现 |
| D8 | `routers/cluster.py`: 集群 API |
| D9 | `cluster-panel.js`: 集群管理前端 |
| D10 | 双机联调测试 |

---

## 七、技术风险

| 风险 | 应对 |
|------|------|
| 50 Agent 并发触发 AI 限速 | 令牌桶 + 平台分散 + 指数退避 |
| Worker 断线导致任务丢失 | 任务持久化 + 自动重试 + 故障转移 |
| 跨机通信安全 | HTTPS + Token 认证 + 局域网白名单 |
| 大规模消息同步延迟 | EventBus 批量推送 + 增量同步 |
| 内存占用过高 | Agent 按需创建 + 执行完释放 + 历史裁剪 |

---

## 八、商业价值

| 功能 | 竞品 | 定价参考 |
|------|------|---------|
| 自定义 Agent | ChatGPT GPTs | 免费（开源） |
| 多 Agent 协作 | CrewAI/AutoGen | Pro ¥99/年 |
| 多机集群 | **无竞品** | 企业版 ¥999/年 |
| 分布式桌面自动化 | **无竞品** | 企业版独享 |
| 500 Agent 并行 | **无竞品** | 按节点数收费 |

**核心卖点：全球首个消费级多机 AI Agent 集群**。
企业客户可以用 10 台普通电脑组建 "AI 部门"，成本 < 1 个人力。

---

*方案基于 v5.0.0 架构扩展，兼容现有全部功能。*
*第 1 层（自定义角色）可独立发布，不依赖集群。*
