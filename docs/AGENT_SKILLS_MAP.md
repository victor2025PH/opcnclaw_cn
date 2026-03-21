# 十三香小龙虾 — 52 个 Agent 角色专属技能清单

> 每个角色 = AI 人设 + 通用工具 + 专属技能
>
> 通用工具 21 个（已实现）+ 专属技能 80+ 个（待实现）= 100+ 工具生态

---

## 技能架构

```
┌─────────────────────────────────────────────────┐
│               Agent 技能体系                      │
├──────────────┬──────────────┬───────────────────┤
│   通用工具    │   部门技能    │    专属技能        │
│  (所有角色)   │  (部门共享)   │   (角色独有)       │
├──────────────┼──────────────┼───────────────────┤
│ 截屏/OCR     │ 研发：代码    │ 前端：生成HTML     │
│ 点击/输入    │ 营销：微信    │ SEO：关键词分析     │
│ 快捷键       │ 客服：消息    │ 库管：库存报表      │
│ 打开应用     │ 财务：计算    │ 质检：检验报告      │
│ 计算/时间    │ 供应链：表格  │ ...               │
└──────────────┴──────────────┴───────────────────┘
```

---

## 部门 1：管理层（5 个角色）

| 角色 | 通用工具 | 专属技能 | 技能说明 |
|------|---------|---------|---------|
| **CEO** 👔 | 全部 | `task_decompose` | 将复杂任务拆解为子任务 DAG |
| | | `team_report` | 汇总所有 Agent 结果生成报告 |
| | | `decision_matrix` | 生成决策矩阵（方案对比表） |
| **COO** 🏛️ | 截屏/计算 | `process_flowchart` | 生成业务流程图（Mermaid） |
| | | `kpi_dashboard` | 生成 KPI 仪表盘数据 |
| | | `bottleneck_analysis` | 识别流程瓶颈并建议优化 |
| **CTO** 🔧 | 截屏/输入 | `tech_review` | 技术方案评审（风险/可行性打分） |
| | | `architecture_diagram` | 生成系统架构图（Mermaid） |
| | | `tech_stack_compare` | 技术选型对比分析 |
| **CFO** 💎 | 计算 | `financial_model` | 生成财务模型（收入/成本/利润预测） |
| | | `investment_analysis` | 投资回报分析（ROI/IRR/NPV） |
| | | `budget_plan` | 生成预算分配方案 |
| **CMO** 📡 | 微信/朋友圈 | `market_sizing` | 市场规模估算（TAM/SAM/SOM） |
| | | `competitor_map` | 竞品矩阵图 |
| | | `campaign_plan` | 营销活动方案（预算/渠道/排期） |

---

## 部门 2：研发技术（8 个角色）

| 角色 | 通用工具 | 专属技能 | 技能说明 |
|------|---------|---------|---------|
| **产品经理** 📱 | 截屏 | `write_prd` | 生成 PRD 文档（需求/用户故事/验收标准） |
| | | `user_persona` | 生成用户画像 |
| | | `feature_prioritize` | 功能优先级排序（RICE/MoSCoW） |
| | | `wireframe_desc` | 生成线框图描述（可转图） |
| **前端** 🖥️ | 输入/快捷键/截屏 | `gen_html` | 生成 HTML/CSS/JS 代码 |
| | | `gen_component` | 生成 UI 组件代码 |
| | | `responsive_check` | 响应式兼容性检查清单 |
| **后端** ⚙️ | 输入/快捷键/截屏 | `gen_api` | 生成 RESTful API 代码（FastAPI/Flask） |
| | | `gen_sql` | 生成 SQL 建表/查询语句 |
| | | `gen_test` | 生成 pytest 测试代码 |
| | | `code_review` | 代码审查（安全/性能/规范） |
| **测试** 🧪 | 截屏/点击 | `gen_testcase` | 生成测试用例（等价类/边界值） |
| | | `gen_bug_report` | 生成 Bug 报告（步骤/预期/实际） |
| | | `test_coverage` | 测试覆盖率分析 |
| **运维** 🔩 | 输入/快捷键/打开应用 | `gen_dockerfile` | 生成 Dockerfile/docker-compose |
| | | `gen_nginx_conf` | 生成 Nginx 配置 |
| | | `server_health` | 服务器健康检查报告 |
| | | `incident_report` | 故障报告生成 |
| **DBA** 🗄️ | 计算 | `gen_schema` | 数据库建模（ER 图描述） |
| | | `sql_optimize` | SQL 优化建议 |
| | | `backup_plan` | 备份恢复方案 |
| **安全** 🛡️ | 截屏 | `security_audit` | 安全审计报告（OWASP Top 10） |
| | | `vulnerability_scan` | 漏洞扫描结果分析 |
| | | `security_policy` | 安全策略文档 |
| **架构师** 🏗️ | 截屏 | `system_design` | 系统设计文档（高可用/扩展性） |
| | | `capacity_plan` | 容量规划（QPS/存储/带宽） |
| | | `migration_plan` | 迁移方案（数据库/服务/架构升级） |

---

## 部门 3：营销获客（7 个角色）

| 角色 | 通用工具 | 专属技能 | 技能说明 |
|------|---------|---------|---------|
| **市场运营** 📢 | 微信/朋友圈 | `campaign_execute` | 活动执行方案（时间线+物料清单） |
| | | `channel_analysis` | 渠道效果分析（各渠道 ROI） |
| | | `event_plan` | 线上/线下活动策划 |
| **SEO** 🔍 | 截屏 | `keyword_research` | 关键词挖掘（搜索量/竞争度/推荐） |
| | | `seo_audit` | 网站 SEO 审计报告 |
| | | `content_brief` | SEO 内容大纲（关键词布局） |
| | | `meta_generate` | 生成 Title/Description/H1 |
| **广告** 📊 | 计算/截屏 | `ad_copy_generate` | 生成广告创意文案（多版本 A/B） |
| | | `budget_allocate` | 广告预算分配方案 |
| | | `roi_report` | 广告 ROI 分析报告 |
| **品牌** 🎪 | | `brand_guide` | 品牌手册（定位/调性/视觉规范） |
| | | `slogan_generate` | 生成品牌 Slogan（10 个候选） |
| | | `brand_story` | 品牌故事撰写 |
| **公关** 📰 | 微信 | `press_release` | 新闻稿撰写 |
| | | `crisis_response` | 危机公关应对方案 |
| | | `media_list` | 媒体资源清单 |
| **社群** 💬 | 微信/朋友圈/消息 | `community_plan` | 社群运营方案（拉新/促活/转化） |
| | | `group_welcome` | 入群欢迎语生成 |
| | | `content_calendar` | 内容日历规划（30天） |
| **增长** 🚀 | 计算/截屏 | `funnel_analysis` | 漏斗分析（注册→付费各环节） |
| | | `ab_test_plan` | A/B 测试方案设计 |
| | | `retention_strategy` | 留存策略（7日/30日/90日） |

---

## 部门 4：销售客服（7 个角色）

| 角色 | 通用工具 | 专属技能 | 技能说明 |
|------|---------|---------|---------|
| **销售** 🤝 | 微信/消息 | `sales_pitch` | 生成销售话术（按客户类型） |
| | | `quote_generate` | 生成报价单 |
| | | `follow_up_plan` | 客户跟进计划 |
| | | `objection_handle` | 异议处理方案（价格/功能/竞品） |
| **售前** 💡 | 截屏/微信 | `solution_design` | 技术方案书 |
| | | `demo_script` | 产品演示脚本 |
| | | `competitor_compare` | 竞品对比表 |
| **在线客服** 🎧 | 微信/消息 | `auto_reply` | 智能回复（FAQ 匹配+AI 兜底） |
| | | `ticket_create` | 工单创建和分类 |
| | | `sentiment_detect` | 用户情绪检测+升级策略 |
| **售后** 🔄 | 微信/消息 | `return_process` | 退换货流程指引 |
| | | `complaint_handle` | 投诉处理方案 |
| | | `satisfaction_survey` | 满意度调查问卷 |
| **VIP 客服** 👑 | 微信/消息 | `vip_greeting` | 大客户专属问候（含客户画像） |
| | | `renewal_remind` | 续费提醒+优惠方案 |
| | | `exclusive_offer` | 专属优惠方案生成 |
| **BD** 🌐 | 微信 | `partnership_proposal` | 合作方案书 |
| | | `resource_map` | 资源整合地图 |
| | | `mou_draft` | 合作备忘录草案 |
| **CRM** 📇 | 微信/消息/计算 | `customer_segment` | 客户分层（RFM 模型） |
| | | `lifecycle_analysis` | 客户生命周期分析 |
| | | `churn_predict` | 流失预警+挽回方案 |

---

## 部门 5：供应链物流（6 个角色）

| 角色 | 通用工具 | 专属技能 | 技能说明 |
|------|---------|---------|---------|
| **采购** 🛒 | 计算/截屏 | `supplier_evaluate` | 供应商评估表（价格/质量/交期） |
| | | `purchase_order` | 生成采购单 |
| | | `price_compare` | 多供应商比价表 |
| | | `contract_template` | 采购合同模板 |
| **库管** 📦 | 计算 | `inventory_report` | 库存报表（SKU/数量/金额/周转） |
| | | `stock_alert` | 安全库存预警 |
| | | `inout_record` | 出入库记录单 |
| **物流** 🚛 | 计算 | `shipping_plan` | 配送方案（快递/整车/零担比选） |
| | | `route_optimize` | 配送路线优化 |
| | | `tracking_report` | 物流时效追踪报告 |
| **调度** 📋 | 计算 | `order_dispatch` | 订单分配方案（按产能/库存/地域） |
| | | `capacity_schedule` | 产能排程表 |
| | | `urgent_plan` | 紧急插单应对方案 |
| **质检** ✅ | 截屏 | `inspection_standard` | 检验标准制定（AQL/抽样方案） |
| | | `quality_report` | 质量检验报告 |
| | | `defect_analysis` | 不良品分析（鱼骨图/帕累托） |
| **供应链经理** 🔗 | 计算/截屏 | `demand_forecast` | 需求预测（历史数据+趋势） |
| | | `sc_kpi_report` | 供应链 KPI 报告（库存周转/交付率） |
| | | `sc_risk_assess` | 供应链风险评估 |

---

## 部门 6：财务行政（6 个角色）

| 角色 | 通用工具 | 专属技能 | 技能说明 |
|------|---------|---------|---------|
| **会计** 📒 | 计算 | `bookkeeping` | 记账凭证生成 |
| | | `invoice_check` | 发票审核清单 |
| | | `cost_calculate` | 成本核算表 |
| | | `reconciliation` | 对账报告 |
| **财务分析** 💰 | 计算/截屏 | `financial_statement` | 三大报表分析（资产/利润/现金流） |
| | | `variance_analysis` | 预算差异分析 |
| | | `cashflow_forecast` | 现金流预测（3/6/12个月） |
| **税务** 🧾 | 计算 | `tax_plan` | 税务筹划方案 |
| | | `tax_calendar` | 纳税日历（月度申报提醒） |
| | | `tax_saving` | 合规节税建议 |
| **法务** ⚖️ | | `contract_review` | 合同审查（风险标注+修改建议） |
| | | `compliance_check` | 合规检查清单 |
| | | `ip_strategy` | 知识产权策略 |
| | | `legal_opinion` | 法律意见书 |
| **HR** 👥 | 微信 | `jd_generate` | 生成招聘 JD |
| | | `interview_question` | 面试题库（按岗位/级别） |
| | | `performance_review` | 绩效评估模板 |
| | | `salary_benchmark` | 薪酬对标分析 |
| **行政** 🏢 | 微信/打开应用 | `meeting_minutes` | 会议纪要生成 |
| | | `travel_plan` | 差旅方案（机票/酒店/行程） |
| | | `asset_register` | 资产登记表 |

---

## 部门 7：内容创意（7 个角色）

| 角色 | 通用工具 | 专属技能 | 技能说明 |
|------|---------|---------|---------|
| **文案** ✍️ | | `ad_copy` | 广告文案（多版本+多风格） |
| | | `product_desc` | 产品描述（电商详情页级别） |
| | | `email_template` | 邮件模板（欢迎/促销/召回） |
| | | `social_post` | 社交媒体发文（微博/小红书/抖音） |
| **编辑** 📝 | | `proofread` | 校对（错别字/语法/逻辑） |
| | | `rewrite` | 改写润色（不同风格转换） |
| | | `title_optimize` | 标题优化（10 个候选+打分） |
| | | `abstract_generate` | 摘要提取 |
| **设计师** 🎨 | 截屏 | `color_palette` | 配色方案（主色+辅色+中性色） |
| | | `layout_suggest` | 排版建议（网格/层次/留白） |
| | | `image_prompt` | AI 绘图提示词（Midjourney/SD） |
| | | `ui_spec` | UI 规范文档（字体/间距/圆角） |
| **视频** 🎬 | | `video_script` | 视频脚本（分镜+旁白+字幕） |
| | | `storyboard` | 分镜头脚本 |
| | | `video_brief` | 视频制作需求单 |
| **摄影** 📸 | 截屏 | `shot_list` | 拍摄清单（角度/灯光/道具） |
| | | `photo_brief` | 产品拍摄需求单 |
| | | `edit_guide` | 后期修图指南 |
| **创意总监** 💡 | | `creative_brief` | 创意简报（目标/受众/概念/执行） |
| | | `campaign_concept` | Campaign 概念方案 |
| | | `mood_board` | 情绪板描述（视觉方向） |
| **翻译** 🌐 | | `translate` | 多语言翻译（8种语言） |
| | | `localize` | 本地化适配（文化差异调整） |
| | | `glossary` | 术语表维护 |

---

## 部门 8：专业顾问（6 个角色）

| 角色 | 通用工具 | 专属技能 | 技能说明 |
|------|---------|---------|---------|
| **数据分析** 📈 | 计算/截屏 | `data_clean` | 数据清洗方案 |
| | | `chart_suggest` | 可视化图表推荐 |
| | | `trend_analysis` | 趋势分析报告 |
| | | `cohort_analysis` | 同期群分析 |
| **AI 训练师** 🤖 | | `prompt_optimize` | Prompt 工程优化 |
| | | `kb_build` | 知识库构建方案 |
| | | `finetune_plan` | 模型微调方案 |
| **导师** 🎓 | | `learning_path` | 学习路径规划 |
| | | `quiz_generate` | 测验题生成 |
| | | `study_plan` | 学习计划表 |
| **管理顾问** 🎯 | 计算 | `swot_analysis` | SWOT 分析 |
| | | `okr_design` | OKR 设计 |
| | | `org_design` | 组织架构设计 |
| **研究员** 🔬 | 截屏/消息 | `market_report` | 市场调研报告 |
| | | `competitor_analysis` | 竞品深度分析 |
| | | `industry_overview` | 行业概览 |
| **助理** 📋 | 微信/时间/打开应用 | `schedule_manage` | 日程管理（冲突检测+建议） |
| | | `meeting_arrange` | 会议安排（时间+议程+参会人） |
| | | `reminder_set` | 提醒设置 |
| | | `doc_organize` | 文档整理分类 |

---

## 统计总览

| 部门 | 角色数 | 专属技能数 | 通用工具 |
|------|--------|----------|---------|
| 管理层 | 5 | 15 | 按角色分配 |
| 研发技术 | 8 | 26 | 输入/截屏/快捷键 |
| 营销获客 | 7 | 22 | 微信/朋友圈/截屏 |
| 销售客服 | 7 | 22 | 微信/消息 |
| 供应链 | 6 | 18 | 计算/截屏 |
| 财务行政 | 6 | 19 | 计算/微信 |
| 内容创意 | 7 | 22 | 截屏 |
| 专业顾问 | 6 | 16 | 计算/截屏/微信 |
| **合计** | **52** | **160** | **21 通用** |

**总计：52 角色 × (通用 21 + 专属 160) = 181 个技能点**

---

## 技能实现策略

### 第 1 类：纯 Prompt 技能（120 个，零开发成本）

大部分专属技能本质上是**结构化 Prompt**，不需要写代码：

```python
# 示例：sales_pitch（销售话术生成）
SKILL_PROMPTS = {
    "sales_pitch": {
        "name": "销售话术",
        "prompt": """你是资深销售。请根据以下信息生成销售话术：
客户类型: {customer_type}
产品: {product}
客户痛点: {pain_point}

输出格式：
1. 开场白（30字）
2. 需求挖掘话术（3个问题）
3. 产品介绍（匹配痛点）
4. 异议处理（3个常见异议+应对）
5. 促成话术（2种方式）""",
        "params": ["customer_type", "product", "pain_point"],
    },
}
```

### 第 2 类：模板生成技能（30 个，低成本）

用 AI 填充结构化模板：

```python
# 示例：purchase_order（采购单）
def purchase_order(supplier, items, delivery_date):
    template = """
    ┌─────────────────────────────┐
    │        采 购 单              │
    ├─────────────────────────────┤
    │ 供应商: {supplier}          │
    │ 交货日: {delivery_date}     │
    ├────┬────────┬───┬──────────┤
    │ 序号│ 品名    │数量│ 单价     │
    {items_table}
    ├────┴────────┴───┴──────────┤
    │ 合计: ¥{total}              │
    └─────────────────────────────┘
    """
    return ai_fill(template, ...)
```

### 第 3 类：工具集成技能（10 个，需开发）

需要调用外部 API 或系统能力的：

```python
# 需要实际开发的技能
NEEDS_DEVELOPMENT = [
    "keyword_research",     # 需要搜索引擎 API
    "stock_alert",          # 需要库存数据库
    "tax_calendar",         # 需要税务日历数据
    "server_health",        # 需要服务器监控 API
    "demand_forecast",      # 需要历史销售数据
    "route_optimize",       # 需要地图 API
    "salary_benchmark",     # 需要薪酬数据库
    "tracking_report",      # 需要物流 API
    "vulnerability_scan",   # 需要安全扫描工具
    "data_clean",           # 需要数据处理管道
]
```

### 实施优先级

```
第 1 批（立即可做）：120 个 Prompt 技能 → 定义 JSON 即可，零代码
第 2 批（1 周内）：30 个模板技能 → 简单 Python 函数
第 3 批（后续迭代）：10 个工具集成 → 需要对接外部 API
```

---

*160 个专属技能 + 21 个通用工具 = 每个 Agent 都能真正"干活"*
