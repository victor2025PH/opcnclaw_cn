# -*- coding: utf-8 -*-
"""
Agent 专属技能库 — 160 个 Prompt 技能

架构：每个技能 = 结构化 Prompt + 参数模板
执行：AI 填充 Prompt → 生成结构化输出
零代码：新增技能只需加一条 JSON 定义
"""

from __future__ import annotations
from typing import Dict, List, Optional


# ── 技能定义 ──────────────────────────────────────────────────

AGENT_SKILLS: Dict[str, dict] = {

    # ═══ 管理层 ═══════════════════════════════════════════════

    "task_decompose": {
        "name": "任务拆解", "dept": "管理", "roles": ["ceo", "coo"],
        "prompt": "将以下任务拆解为可执行的子任务列表，每个标注负责角色、优先级和预计时间：\n\n{task}",
        "output_format": "JSON数组: [{role, task, priority, est_hours}]",
    },
    "team_report": {
        "name": "团队报告", "dept": "管理", "roles": ["ceo"],
        "prompt": "基于以下团队成员的工作成果，生成一份完整的汇总报告（含执行摘要、各成员贡献、结论和建议）：\n\n{results}",
        "output_format": "Markdown 报告",
    },
    "decision_matrix": {
        "name": "决策矩阵", "dept": "管理", "roles": ["ceo", "coo"],
        "prompt": "对以下方案进行多维度对比分析，生成决策矩阵：\n方案列表：{options}\n评估维度：成本、时间、风险、收益、可行性\n每项1-10分并给出推荐",
        "output_format": "Markdown 表格",
    },
    "process_flowchart": {
        "name": "流程图", "dept": "管理", "roles": ["coo"],
        "prompt": "为以下业务流程生成 Mermaid 流程图代码：\n\n{process}",
        "output_format": "Mermaid 代码块",
    },
    "kpi_dashboard": {
        "name": "KPI仪表盘", "dept": "管理", "roles": ["coo"],
        "prompt": "为{department}部门设计KPI体系，包含5-8个关键指标，每个标注目标值、计算公式、数据来源",
        "output_format": "Markdown 表格",
    },
    "tech_review": {
        "name": "技术评审", "dept": "管理", "roles": ["cto"],
        "prompt": "对以下技术方案进行评审：\n{proposal}\n\n从可行性、性能、安全、可维护性、成本5个维度各打1-10分，给出修改建议",
        "output_format": "评审报告",
    },
    "architecture_diagram": {
        "name": "架构图", "dept": "管理", "roles": ["cto", "architect"],
        "prompt": "为以下系统生成架构图（Mermaid格式）：\n{system}\n包含：组件、数据流、外部依赖",
        "output_format": "Mermaid 代码块",
    },
    "tech_stack_compare": {
        "name": "技术选型", "dept": "管理", "roles": ["cto"],
        "prompt": "对比以下技术方案：{options}\n从性能、生态、学习成本、社区活跃度、长期维护5个维度对比，给出推荐",
        "output_format": "对比表格 + 推荐",
    },
    "financial_model": {
        "name": "财务模型", "dept": "管理", "roles": ["cfo"],
        "prompt": "为以下业务建立财务模型：\n{business}\n预算：{budget}\n\n输出12个月的收入/成本/利润预测表",
        "output_format": "Markdown 表格（月度）",
    },
    "investment_analysis": {
        "name": "投资分析", "dept": "管理", "roles": ["cfo"],
        "prompt": "分析以下投资项目：\n{project}\n投资额：{amount}\n\n计算ROI、IRR、回收期，给出投资建议",
        "output_format": "分析报告 + 数据表",
    },
    "budget_plan": {
        "name": "预算方案", "dept": "管理", "roles": ["cfo"],
        "prompt": "为{department}部门制定{period}预算方案，总额{budget}，按类别分配并说明理由",
        "output_format": "预算分配表",
    },
    "market_sizing": {
        "name": "市场规模", "dept": "管理", "roles": ["cmo"],
        "prompt": "估算{product}的市场规模：\nTAM（总可用市场）\nSAM（可服务市场）\nSOM（可获得市场）\n给出数据来源和计算逻辑",
        "output_format": "TAM/SAM/SOM 分析",
    },
    "competitor_map": {
        "name": "竞品矩阵", "dept": "管理", "roles": ["cmo"],
        "prompt": "绘制{product}的竞品矩阵图，横轴：价格（低→高），纵轴：功能（少→多），标注主要竞品位置和我们的定位",
        "output_format": "矩阵描述 + 定位建议",
    },
    "campaign_plan": {
        "name": "营销方案", "dept": "管理", "roles": ["cmo"],
        "prompt": "为{product}制定营销方案：\n预算：{budget}\n目标：{goal}\n\n包含渠道分配、时间排期、预期效果",
        "output_format": "营销方案文档",
    },

    # ═══ 研发技术 ═════════════════════════════════════════════

    "write_prd": {
        "name": "PRD文档", "dept": "研发", "roles": ["pm"],
        "prompt": "为以下产品需求撰写PRD：\n{requirement}\n\n包含：背景、目标用户、功能列表、用户故事、验收标准、优先级",
        "output_format": "PRD Markdown",
    },
    "user_persona": {
        "name": "用户画像", "dept": "研发", "roles": ["pm"],
        "prompt": "为{product}创建3个典型用户画像，每个包含：姓名、年龄、职业、痛点、使用场景、期望",
        "output_format": "3个用户画像卡片",
    },
    "feature_prioritize": {
        "name": "功能排序", "dept": "研发", "roles": ["pm"],
        "prompt": "用RICE框架对以下功能列表排序：\n{features}\n\nRICE = Reach × Impact × Confidence / Effort",
        "output_format": "排序表格（含RICE分数）",
    },
    "gen_html": {
        "name": "生成HTML", "dept": "研发", "roles": ["frontend"],
        "prompt": "根据以下需求生成HTML/CSS/JS代码：\n{requirement}\n\n要求响应式设计，使用CSS Variables，简洁美观",
        "output_format": "HTML代码",
    },
    "gen_component": {
        "name": "生成组件", "dept": "研发", "roles": ["frontend"],
        "prompt": "生成一个{framework}组件：\n功能：{description}\n\n包含完整代码、Props定义、使用示例",
        "output_format": "组件代码",
    },
    "gen_api": {
        "name": "生成API", "dept": "研发", "roles": ["backend"],
        "prompt": "用{framework}生成以下API：\n{api_spec}\n\n包含路由、请求模型、响应模型、业务逻辑、错误处理",
        "output_format": "Python代码",
    },
    "gen_sql": {
        "name": "生成SQL", "dept": "研发", "roles": ["backend", "dba"],
        "prompt": "根据以下需求生成SQL：\n{requirement}\n\n包含建表语句、索引、示例查询",
        "output_format": "SQL代码",
    },
    "gen_test": {
        "name": "生成测试", "dept": "研发", "roles": ["backend", "tester"],
        "prompt": "为以下功能生成pytest测试代码：\n{function_desc}\n\n覆盖正常流程、边界情况、异常情况",
        "output_format": "pytest代码",
    },
    "code_review": {
        "name": "代码审查", "dept": "研发", "roles": ["backend", "frontend"],
        "prompt": "审查以下代码：\n```\n{code}\n```\n\n从安全性、性能、可读性、最佳实践4个维度评审，给出具体修改建议",
        "output_format": "审查报告",
    },
    "gen_testcase": {
        "name": "测试用例", "dept": "研发", "roles": ["tester"],
        "prompt": "为以下功能设计测试用例：\n{feature}\n\n用等价类划分法和边界值法，输出测试用例表",
        "output_format": "测试用例表格",
    },
    "gen_bug_report": {
        "name": "Bug报告", "dept": "研发", "roles": ["tester"],
        "prompt": "根据以下现象生成Bug报告：\n{symptom}\n\n格式：标题、严重程度、复现步骤、预期结果、实际结果、环境信息",
        "output_format": "Bug报告",
    },
    "gen_dockerfile": {
        "name": "Dockerfile", "dept": "研发", "roles": ["devops"],
        "prompt": "为以下项目生成Dockerfile：\n语言：{language}\n框架：{framework}\n依赖：{deps}\n\n多阶段构建，最小镜像",
        "output_format": "Dockerfile",
    },
    "server_health": {
        "name": "服务器健康", "dept": "研发", "roles": ["devops"],
        "prompt": "生成服务器健康检查报告模板，包含：CPU/内存/磁盘/网络/服务状态/日志异常/安全告警",
        "output_format": "检查报告模板",
    },
    "system_design": {
        "name": "系统设计", "dept": "研发", "roles": ["architect"],
        "prompt": "为以下系统撰写设计文档：\n{system}\n\n包含：架构图、组件说明、数据流、API接口、部署方案、扩展策略",
        "output_format": "系统设计文档",
    },
    "security_audit": {
        "name": "安全审计", "dept": "研发", "roles": ["security"],
        "prompt": "对以下系统进行安全审计：\n{system}\n\n按OWASP Top 10逐项检查，给出风险等级和修复建议",
        "output_format": "安全审计报告",
    },
    "sql_optimize": {
        "name": "SQL优化", "dept": "研发", "roles": ["dba"],
        "prompt": "优化以下SQL查询：\n```sql\n{sql}\n```\n\n分析执行计划、添加索引建议、改写优化",
        "output_format": "优化建议 + 改写后SQL",
    },
    "capacity_plan": {
        "name": "容量规划", "dept": "研发", "roles": ["architect"],
        "prompt": "为以下系统做容量规划：\n用户量：{users}\n日活：{dau}\n峰值QPS：{qps}\n\n计算服务器、存储、带宽需求",
        "output_format": "容量规划表",
    },

    # ═══ 营销获客 ═════════════════════════════════════════════

    "campaign_execute": {
        "name": "活动执行", "dept": "营销", "roles": ["marketer"],
        "prompt": "制定{campaign}活动的执行方案：\n时间线、物料清单、人员分工、预算分配、应急预案",
        "output_format": "执行方案",
    },
    "keyword_research": {
        "name": "关键词挖掘", "dept": "营销", "roles": ["seo"],
        "prompt": "为{product}挖掘SEO关键词：\n核心词5个、长尾词20个，标注搜索意图（信息型/交易型/导航型）和竞争度（高/中/低）",
        "output_format": "关键词表格",
    },
    "seo_audit": {
        "name": "SEO审计", "dept": "营销", "roles": ["seo"],
        "prompt": "审计以下网站的SEO表现：\n{url}\n\n检查：Title/Meta/H1/内链/外链/速度/移动端/结构化数据",
        "output_format": "SEO审计报告",
    },
    "content_brief": {
        "name": "内容大纲", "dept": "营销", "roles": ["seo"],
        "prompt": "为关键词'{keyword}'撰写SEO内容大纲：\n目标字数、H2/H3结构、关键词布局位置、内链建议",
        "output_format": "内容大纲",
    },
    "ad_copy_generate": {
        "name": "广告文案", "dept": "营销", "roles": ["ads"],
        "prompt": "为{product}生成{platform}广告文案：\n目标受众：{audience}\n\n生成5个版本（不同角度/风格），每个含标题+描述+CTA",
        "output_format": "5组广告文案",
    },
    "budget_allocate": {
        "name": "预算分配", "dept": "营销", "roles": ["ads"],
        "prompt": "将{budget}广告预算分配到各渠道：\n渠道选项：{channels}\n\n基于ROI历史数据和目标给出分配方案",
        "output_format": "预算分配表",
    },
    "brand_guide": {
        "name": "品牌手册", "dept": "营销", "roles": ["brand"],
        "prompt": "为{brand}制定品牌手册：\n品牌定位、调性词、视觉规范（色彩/字体/间距）、语言规范（用词/禁忌）",
        "output_format": "品牌手册",
    },
    "slogan_generate": {
        "name": "Slogan生成", "dept": "营销", "roles": ["brand"],
        "prompt": "为{brand}生成10个Slogan候选：\n品牌定位：{positioning}\n\n每个标注风格（理性/感性/幽默/激励），并推荐前3名",
        "output_format": "Slogan列表+推荐",
    },
    "press_release": {
        "name": "新闻稿", "dept": "营销", "roles": ["pr"],
        "prompt": "撰写新闻稿：\n事件：{event}\n\n格式：倒金字塔结构，含标题、导语、主体、引述、背景",
        "output_format": "新闻稿",
    },
    "crisis_response": {
        "name": "危机公关", "dept": "营销", "roles": ["pr"],
        "prompt": "针对以下危机事件制定应对方案：\n{crisis}\n\n包含：态度定调、声明稿、Q&A口径、后续行动",
        "output_format": "危机应对方案",
    },
    "community_plan": {
        "name": "社群方案", "dept": "营销", "roles": ["community"],
        "prompt": "制定{product}的社群运营方案：\n拉新策略、促活方法、转化路径、每日内容计划、社群规则",
        "output_format": "社群运营方案",
    },
    "content_calendar": {
        "name": "内容日历", "dept": "营销", "roles": ["community"],
        "prompt": "为{product}制定30天内容发布日历：\n渠道：{channels}\n每天标注：平台、主题、形式（图文/视频/直播）、发布时间",
        "output_format": "30天日历表",
    },
    "funnel_analysis": {
        "name": "漏斗分析", "dept": "营销", "roles": ["growth"],
        "prompt": "分析以下转化漏斗：\n{funnel_data}\n\n找出最大流失环节，给出3个优化建议（含预期提升）",
        "output_format": "漏斗分析报告",
    },
    "ab_test_plan": {
        "name": "A/B测试", "dept": "营销", "roles": ["growth"],
        "prompt": "设计A/B测试方案：\n目标：{goal}\n变量：{variable}\n\n样本量计算、持续时间、成功标准、实施步骤",
        "output_format": "A/B测试方案",
    },
    "retention_strategy": {
        "name": "留存策略", "dept": "营销", "roles": ["growth"],
        "prompt": "为{product}设计用户留存策略：\nDAU：{dau}\n7日留存：{retention}\n\n分阶段策略（首日/7日/30日/90日）",
        "output_format": "留存策略方案",
    },

    # ═══ 销售客服 ═════════════════════════════════════════════

    "sales_pitch": {
        "name": "销售话术", "dept": "销售", "roles": ["sales"],
        "prompt": "为{product}生成销售话术：\n客户类型：{customer_type}\n痛点：{pain_point}\n\n含开场白、需求挖掘、产品介绍、异议处理、促成",
        "output_format": "话术脚本",
    },
    "quote_generate": {
        "name": "报价单", "dept": "销售", "roles": ["sales"],
        "prompt": "生成报价单：\n客户：{customer}\n产品：{items}\n\n含产品明细、单价、数量、折扣、总价、有效期、付款方式",
        "output_format": "报价单表格",
    },
    "follow_up_plan": {
        "name": "跟进计划", "dept": "销售", "roles": ["sales"],
        "prompt": "制定客户跟进计划：\n客户：{customer}\n当前阶段：{stage}\n\n7天跟进计划（每天的动作、话术、目标）",
        "output_format": "7天跟进日历",
    },
    "objection_handle": {
        "name": "异议处理", "dept": "销售", "roles": ["sales"],
        "prompt": "准备{product}的常见客户异议应对方案：\n\n列出10个最常见异议，每个配套：共情→澄清→解决→确认 的话术",
        "output_format": "异议处理手册",
    },
    "solution_design": {
        "name": "方案设计", "dept": "销售", "roles": ["presale"],
        "prompt": "为{customer}设计技术方案：\n需求：{requirement}\n\n含方案概述、架构图、实施计划、报价、交付里程碑",
        "output_format": "技术方案书",
    },
    "demo_script": {
        "name": "演示脚本", "dept": "销售", "roles": ["presale"],
        "prompt": "编写{product}的演示脚本：\n受众：{audience}\n时长：{duration}\n\n含开场、功能展示顺序、互动环节、收尾",
        "output_format": "演示脚本",
    },
    "auto_reply": {
        "name": "智能回复", "dept": "客服", "roles": ["cs_online"],
        "prompt": "根据客户消息生成回复：\n消息：{message}\n\n语气友善专业，先理解问题，再给出解决方案，必要时引导到人工",
        "output_format": "回复文本",
    },
    "ticket_create": {
        "name": "工单创建", "dept": "客服", "roles": ["cs_online"],
        "prompt": "根据客户描述创建工单：\n描述：{description}\n\n自动分类（咨询/投诉/建议/故障）、优先级、标签、分配建议",
        "output_format": "工单JSON",
    },
    "return_process": {
        "name": "退换货指引", "dept": "客服", "roles": ["cs_after"],
        "prompt": "客户申请退换货：\n原因：{reason}\n订单：{order}\n\n判断是否符合条件，生成操作步骤指引",
        "output_format": "退换货指引",
    },
    "complaint_handle": {
        "name": "投诉处理", "dept": "客服", "roles": ["cs_after"],
        "prompt": "处理客户投诉：\n投诉内容：{complaint}\n\n先共情安抚，分析原因，给出解决方案（至少2个选项），跟进计划",
        "output_format": "投诉处理方案",
    },
    "vip_greeting": {
        "name": "VIP问候", "dept": "客服", "roles": ["cs_vip"],
        "prompt": "为VIP客户生成专属问候：\n客户：{name}\n消费记录：{history}\n\n个性化问候+专属优惠推荐",
        "output_format": "问候消息",
    },
    "renewal_remind": {
        "name": "续费提醒", "dept": "客服", "roles": ["cs_vip"],
        "prompt": "生成续费提醒消息：\n客户：{name}\n到期：{expire}\n\n含续费价值说明、限时优惠、操作入口",
        "output_format": "续费提醒",
    },
    "partnership_proposal": {
        "name": "合作方案", "dept": "销售", "roles": ["bd"],
        "prompt": "撰写合作方案书：\n合作方：{partner}\n合作模式：{model}\n\n含背景分析、合作价值、分工方案、利润分配、时间表",
        "output_format": "合作方案书",
    },
    "customer_segment": {
        "name": "客户分层", "dept": "销售", "roles": ["crm"],
        "prompt": "用RFM模型对客户进行分层：\n数据描述：{data}\n\nR(最近购买)/F(购买频率)/M(消费金额)各分5档，输出8个客群标签",
        "output_format": "RFM分层表",
    },
    "churn_predict": {
        "name": "流失预警", "dept": "销售", "roles": ["crm"],
        "prompt": "分析以下客户的流失风险：\n行为：{behavior}\n\n评估流失概率（高/中/低），制定挽回方案（短信/电话/优惠/拜访）",
        "output_format": "流失预警报告",
    },

    # ═══ 供应链 ═══════════════════════════════════════════════

    "supplier_evaluate": {
        "name": "供应商评估", "dept": "供应链", "roles": ["buyer"],
        "prompt": "评估供应商：{supplier}\n\n从价格、质量、交期、服务、规模5个维度各10分，并与{competitor}对比",
        "output_format": "评估表格+推荐",
    },
    "purchase_order": {
        "name": "采购单", "dept": "供应链", "roles": ["buyer"],
        "prompt": "生成采购单：\n供应商：{supplier}\n物品：{items}\n交货日：{date}\n\n含品名、规格、数量、单价、总价",
        "output_format": "采购单表格",
    },
    "price_compare": {
        "name": "比价表", "dept": "供应链", "roles": ["buyer"],
        "prompt": "生成多供应商比价表：\n产品：{product}\n供应商：{suppliers}\n\n对比：单价、起订量、交期、付款方式、售后",
        "output_format": "比价对比表",
    },
    "inventory_report": {
        "name": "库存报表", "dept": "供应链", "roles": ["warehouse"],
        "prompt": "生成库存报表模板：\n仓库：{warehouse}\n\n含SKU、名称、数量、库龄、安全库存、补货建议",
        "output_format": "库存报表",
    },
    "stock_alert": {
        "name": "库存预警", "dept": "供应链", "roles": ["warehouse"],
        "prompt": "设置库存预警规则：\n产品：{products}\n\n为每个产品设定：安全库存、最大库存、补货点、补货量、紧急阈值",
        "output_format": "预警规则表",
    },
    "shipping_plan": {
        "name": "配送方案", "dept": "供应链", "roles": ["logistics"],
        "prompt": "制定配送方案：\n发货地：{from}\n目的地：{to}\n货物：{cargo}\n\n比较快递/整车/零担，推荐最优方案",
        "output_format": "配送方案",
    },
    "route_optimize": {
        "name": "路线优化", "dept": "供应链", "roles": ["logistics"],
        "prompt": "优化配送路线：\n出发点：{start}\n目的地列表：{destinations}\n\n按距离和时间最优排序",
        "output_format": "路线规划",
    },
    "order_dispatch": {
        "name": "订单分配", "dept": "供应链", "roles": ["dispatch"],
        "prompt": "分配订单到仓库/产线：\n订单：{orders}\n资源：{resources}\n\n按就近、产能、库存3个因素综合分配",
        "output_format": "分配方案",
    },
    "inspection_standard": {
        "name": "检验标准", "dept": "供应链", "roles": ["quality"],
        "prompt": "为{product}制定质检标准：\n包含：外观/尺寸/功能/安全4类检查项，每项标注AQL和抽样水平",
        "output_format": "质检标准表",
    },
    "quality_report": {
        "name": "质检报告", "dept": "供应链", "roles": ["quality"],
        "prompt": "生成质检报告：\n批次：{batch}\n检查结果：{results}\n\n含合格率、不良分布、原因分析、改进建议",
        "output_format": "质检报告",
    },
    "demand_forecast": {
        "name": "需求预测", "dept": "供应链", "roles": ["scm"],
        "prompt": "预测{product}未来{months}个月的需求：\n历史数据：{history}\n\n考虑季节性、趋势、促销影响",
        "output_format": "需求预测表",
    },
    "sc_risk_assess": {
        "name": "供应链风险", "dept": "供应链", "roles": ["scm"],
        "prompt": "评估供应链风险：\n供应商：{suppliers}\n\n从单一来源、地域集中、交期波动、价格波动、质量稳定5个维度评估",
        "output_format": "风险评估报告",
    },

    # ═══ 财务行政 ═════════════════════════════════════════════

    "bookkeeping": {
        "name": "记账凭证", "dept": "财务", "roles": ["accountant"],
        "prompt": "根据以下交易生成记账凭证：\n交易：{transaction}\n\n借贷分录、科目、金额、摘要",
        "output_format": "记账凭证",
    },
    "cost_calculate": {
        "name": "成本核算", "dept": "财务", "roles": ["accountant"],
        "prompt": "核算{product}的成本：\n原材料：{materials}\n人工：{labor}\n制造费：{overhead}\n\n计算单位成本和利润率",
        "output_format": "成本核算表",
    },
    "financial_statement": {
        "name": "财务报表", "dept": "财务", "roles": ["finance"],
        "prompt": "分析以下财务数据：\n{data}\n\n生成资产负债表分析、利润表分析、关键指标（毛利率/净利率/资产负债率）",
        "output_format": "财务分析报告",
    },
    "cashflow_forecast": {
        "name": "现金流预测", "dept": "财务", "roles": ["finance"],
        "prompt": "预测未来{months}个月现金流：\n收入：{revenue}\n支出：{expense}\n\n标注现金流为负的月份和应对建议",
        "output_format": "现金流预测表",
    },
    "tax_plan": {
        "name": "税务筹划", "dept": "财务", "roles": ["tax"],
        "prompt": "为{company_type}公司制定税务筹划方案：\n年收入：{revenue}\n\n合规节税建议（研发加计、小微优惠、区域政策）",
        "output_format": "税务筹划方案",
    },
    "tax_calendar": {
        "name": "税务日历", "dept": "财务", "roles": ["tax"],
        "prompt": "生成{year}年税务日历：\n公司类型：{type}\n\n标注每月申报项目、截止日期、注意事项",
        "output_format": "12个月税务日历",
    },
    "contract_review": {
        "name": "合同审查", "dept": "财务", "roles": ["legal"],
        "prompt": "审查以下合同条款：\n{contract}\n\n标注风险条款（红色）、建议修改条款（黄色），给出修改建议",
        "output_format": "合同审查报告",
    },
    "compliance_check": {
        "name": "合规检查", "dept": "财务", "roles": ["legal"],
        "prompt": "检查{business}的合规情况：\n行业：{industry}\n\n逐项检查适用法规，标注合规/不合规/需改进",
        "output_format": "合规检查清单",
    },
    "legal_opinion": {
        "name": "法律意见", "dept": "财务", "roles": ["legal"],
        "prompt": "就以下事项出具法律意见：\n{matter}\n\n分析法律风险、引用相关法条、给出建议",
        "output_format": "法律意见书",
    },
    "jd_generate": {
        "name": "招聘JD", "dept": "行政", "roles": ["hr"],
        "prompt": "生成{position}的招聘JD：\n部门：{dept}\n级别：{level}\n\n含岗位职责、任职要求、薪资范围、亮点福利",
        "output_format": "招聘JD",
    },
    "interview_question": {
        "name": "面试题库", "dept": "行政", "roles": ["hr"],
        "prompt": "为{position}准备面试题库：\n含行为面试题5个、技术题5个、情景题3个，每题附评分标准",
        "output_format": "面试题库",
    },
    "performance_review": {
        "name": "绩效评估", "dept": "行政", "roles": ["hr"],
        "prompt": "生成{position}的绩效评估模板：\n含KPI指标、权重、评分标准（1-5分）、自评+上级评",
        "output_format": "绩效评估表",
    },
    "meeting_minutes": {
        "name": "会议纪要", "dept": "行政", "roles": ["admin", "assistant"],
        "prompt": "根据以下会议内容生成纪要：\n{content}\n\n格式：会议信息、议题讨论、决议事项、行动项（负责人+截止时间）",
        "output_format": "会议纪要",
    },
    "travel_plan": {
        "name": "差旅方案", "dept": "行政", "roles": ["admin", "assistant"],
        "prompt": "规划差旅行程：\n出发：{from}\n目的地：{to}\n日期：{dates}\n预算：{budget}\n\n含交通+住宿+日程安排",
        "output_format": "差旅行程表",
    },

    # ═══ 内容创意 ═════════════════════════════════════════════

    "ad_copy": {
        "name": "广告文案", "dept": "内容", "roles": ["writer"],
        "prompt": "为{product}写{platform}广告文案：\n受众：{audience}\n卖点：{usp}\n\n生成5个版本，风格各异",
        "output_format": "5组广告文案",
    },
    "product_desc": {
        "name": "产品描述", "dept": "内容", "roles": ["writer"],
        "prompt": "撰写{product}的电商详情页文案：\n核心卖点：{features}\n\n含标题、副标题、卖点描述、使用场景、用户评价风格",
        "output_format": "详情页文案",
    },
    "email_template": {
        "name": "邮件模板", "dept": "内容", "roles": ["writer"],
        "prompt": "生成{type}类型的邮件模板：\n场景：{scenario}\n\n含主题行(3个选项)、正文、CTA按钮文案",
        "output_format": "邮件模板",
    },
    "social_post": {
        "name": "社交发文", "dept": "内容", "roles": ["writer"],
        "prompt": "为{platform}写发文：\n主题：{topic}\n\n含文案+话题标签+发布时间建议+互动引导",
        "output_format": "社交媒体帖子",
    },
    "proofread": {
        "name": "校对", "dept": "内容", "roles": ["editor"],
        "prompt": "校对以下文本：\n{text}\n\n标注：错别字、语法错误、逻辑问题、风格不一致，给出修改后版本",
        "output_format": "校对报告+修改版",
    },
    "rewrite": {
        "name": "改写润色", "dept": "内容", "roles": ["editor"],
        "prompt": "将以下文本改写为{style}风格：\n{text}\n\n保持核心信息不变，调整语气和表达",
        "output_format": "改写后文本",
    },
    "title_optimize": {
        "name": "标题优化", "dept": "内容", "roles": ["editor"],
        "prompt": "为以下文章优化标题：\n内容摘要：{summary}\n\n生成10个候选标题，每个标注吸引力评分（1-10），推荐前3",
        "output_format": "10个标题+推荐",
    },
    "color_palette": {
        "name": "配色方案", "dept": "内容", "roles": ["designer"],
        "prompt": "为{brand}设计配色方案：\n行业：{industry}\n调性：{tone}\n\n主色+辅色+中性色+强调色，各给HEX值",
        "output_format": "配色方案（含HEX）",
    },
    "image_prompt": {
        "name": "AI绘图提示词", "dept": "内容", "roles": ["designer"],
        "prompt": "生成{scene}的AI绘图提示词（Midjourney格式）：\n风格：{style}\n\n正面提示词+负面提示词+参数建议",
        "output_format": "Midjourney 提示词",
    },
    "ui_spec": {
        "name": "UI规范", "dept": "内容", "roles": ["designer"],
        "prompt": "为{product}制定UI设计规范：\n含字体（标题/正文/注释）、间距（4px基数）、圆角、阴影、动效",
        "output_format": "UI规范文档",
    },
    "video_script": {
        "name": "视频脚本", "dept": "内容", "roles": ["video"],
        "prompt": "为{topic}写{duration}视频脚本：\n平台：{platform}\n\n含分镜、旁白、字幕、BGM建议、转场",
        "output_format": "视频脚本（分镜表）",
    },
    "storyboard": {
        "name": "分镜脚本", "dept": "内容", "roles": ["video"],
        "prompt": "为以下视频写分镜头脚本：\n{concept}\n\n每个镜头含：画面描述、镜头类型、时长、旁白/对白、音效",
        "output_format": "分镜表",
    },
    "shot_list": {
        "name": "拍摄清单", "dept": "内容", "roles": ["photographer"],
        "prompt": "为{product}产品拍摄准备清单：\n风格：{style}\n\n含角度列表、灯光方案、道具清单、后期风格参考",
        "output_format": "拍摄清单",
    },
    "creative_brief": {
        "name": "创意简报", "dept": "内容", "roles": ["copywriter"],
        "prompt": "撰写创意简报：\n项目：{project}\n目标：{goal}\n受众：{audience}\n\n含洞察、创意概念、执行方向、参考案例",
        "output_format": "创意简报",
    },
    "translate": {
        "name": "翻译", "dept": "内容", "roles": ["translator"],
        "prompt": "将以下文本翻译为{target_lang}：\n{text}\n\n注意文化适配和本地化表达",
        "output_format": "翻译文本",
    },
    "localize": {
        "name": "本地化", "dept": "内容", "roles": ["translator"],
        "prompt": "将以下内容本地化为{market}市场版本：\n{content}\n\n调整文化差异、计量单位、日期格式、敏感内容",
        "output_format": "本地化文本",
    },

    # ═══ 专业顾问 ═════════════════════════════════════════════

    "data_clean": {
        "name": "数据清洗", "dept": "顾问", "roles": ["data_analyst"],
        "prompt": "设计数据清洗方案：\n数据描述：{data}\n问题：{issues}\n\n给出清洗步骤、异常值处理、缺失值策略",
        "output_format": "数据清洗方案",
    },
    "trend_analysis": {
        "name": "趋势分析", "dept": "顾问", "roles": ["data_analyst"],
        "prompt": "分析以下数据的趋势：\n{data}\n\n识别：增长/下降趋势、季节性、异常点、预测未来3个月",
        "output_format": "趋势分析报告",
    },
    "cohort_analysis": {
        "name": "同期群分析", "dept": "顾问", "roles": ["data_analyst"],
        "prompt": "对以下用户数据做同期群分析：\n{data}\n\n按注册月份分组，展示1-12月留存率热力图",
        "output_format": "同期群表格",
    },
    "prompt_optimize": {
        "name": "Prompt优化", "dept": "顾问", "roles": ["ai_trainer"],
        "prompt": "优化以下Prompt：\n{prompt}\n\n从清晰度、具体性、格式控制、few-shot示例4个维度改进",
        "output_format": "优化后Prompt+改进说明",
    },
    "kb_build": {
        "name": "知识库构建", "dept": "顾问", "roles": ["ai_trainer"],
        "prompt": "为{domain}设计知识库构建方案：\n数据来源、分类体系、向量化策略、检索方案、更新机制",
        "output_format": "知识库方案",
    },
    "learning_path": {
        "name": "学习路径", "dept": "顾问", "roles": ["mentor"],
        "prompt": "为学习{skill}设计学习路径：\n当前水平：{level}\n目标：{goal}\n\n分阶段（入门/进阶/精通），每阶段标注资源和时间",
        "output_format": "学习路径图",
    },
    "quiz_generate": {
        "name": "测验生成", "dept": "顾问", "roles": ["mentor"],
        "prompt": "为{topic}生成测验题：\n难度：{difficulty}\n\n10道选择题+5道简答题，含答案和解析",
        "output_format": "测验题+答案",
    },
    "swot_analysis": {
        "name": "SWOT分析", "dept": "顾问", "roles": ["consultant"],
        "prompt": "对{subject}进行SWOT分析：\n\n优势(S)、劣势(W)、机会(O)、威胁(T)各列3-5条，并给出SO/ST/WO/WT策略",
        "output_format": "SWOT矩阵+策略",
    },
    "okr_design": {
        "name": "OKR设计", "dept": "顾问", "roles": ["consultant"],
        "prompt": "为{team}设计季度OKR：\n战略目标：{strategy}\n\n3个O（目标），每个3个KR（关键结果），每个KR有量化指标",
        "output_format": "OKR表格",
    },
    "org_design": {
        "name": "组织设计", "dept": "顾问", "roles": ["consultant"],
        "prompt": "为{company}设计组织架构：\n规模：{size}\n业务：{business}\n\n含组织图、岗位编制、汇报关系、协作机制",
        "output_format": "组织架构方案",
    },
    "market_report": {
        "name": "市调报告", "dept": "顾问", "roles": ["researcher"],
        "prompt": "撰写{industry}行业调研报告：\n含市场规模、增长率、主要玩家、技术趋势、政策环境、投资建议",
        "output_format": "行业调研报告",
    },
    "competitor_analysis": {
        "name": "竞品分析", "dept": "顾问", "roles": ["researcher"],
        "prompt": "深度分析竞品{competitor}：\n维度：产品功能、定价、市场份额、优劣势、策略推测",
        "output_format": "竞品分析报告",
    },
    "schedule_manage": {
        "name": "日程管理", "dept": "顾问", "roles": ["assistant"],
        "prompt": "管理以下日程：\n已有安排：{schedule}\n新增请求：{request}\n\n检测冲突、建议调整、输出优化后日程",
        "output_format": "优化后日程表",
    },
    "meeting_arrange": {
        "name": "会议安排", "dept": "顾问", "roles": ["assistant"],
        "prompt": "安排会议：\n主题：{topic}\n参会人：{attendees}\n时长：{duration}\n\n生成会议邀请（时间/地点/议程）",
        "output_format": "会议邀请",
    },
}


# ── 技能检索 ──────────────────────────────────────────────────

def get_skills_for_role(role_id: str) -> List[dict]:
    """获取角色的专属技能列表"""
    return [
        {"id": sid, "name": s["name"], "dept": s["dept"]}
        for sid, s in AGENT_SKILLS.items()
        if role_id in s.get("roles", [])
    ]


def get_skill(skill_id: str) -> Optional[dict]:
    return AGENT_SKILLS.get(skill_id)


def execute_skill(skill_id: str, params: dict) -> str:
    """构建技能 Prompt（供 Agent 调用 AI 时使用）"""
    skill = AGENT_SKILLS.get(skill_id)
    if not skill:
        return ""
    prompt = skill["prompt"]
    for k, v in params.items():
        prompt = prompt.replace(f"{{{k}}}", str(v))
    if skill.get("output_format"):
        prompt += f"\n\n输出格式：{skill['output_format']}"
    return prompt


def list_all_skills() -> List[dict]:
    return [
        {"id": sid, "name": s["name"], "dept": s["dept"], "roles": s["roles"]}
        for sid, s in AGENT_SKILLS.items()
    ]


def get_stats() -> dict:
    depts = {}
    for s in AGENT_SKILLS.values():
        d = s["dept"]
        depts[d] = depts.get(d, 0) + 1
    return {
        "total_skills": len(AGENT_SKILLS),
        "by_department": depts,
    }
