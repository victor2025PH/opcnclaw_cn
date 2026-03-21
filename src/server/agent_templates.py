# -*- coding: utf-8 -*-
"""52 个 Agent 角色 + 15 个产业链团队模板"""

from typing import Dict, List, Optional
from .agent_team import Agent, AgentRole

# ── 52 个角色定义（8 大部门）──────────────────────────────────

def _r(id, name, avatar, desc, prompt, model="", tools=None, delegate=False):
    return AgentRole(id=id, name=name, avatar=avatar, description=desc,
                     system_prompt=prompt, preferred_model=model,
                     tools=tools or [], can_delegate=delegate)

AGENT_ROLES: Dict[str, AgentRole] = {
    # ── 管理层 (5) ──
    "ceo": _r("ceo", "CEO", "👔", "战略决策、任务拆解、团队调度、汇总审核",
              "你是团队CEO。职责：1.理解需求 2.拆解子任务(JSON) 3.分配给成员 4.汇总审核。回答简洁有条理。",
              "deepseek-chat", delegate=True),
    "coo": _r("coo", "COO", "🏛️", "运营统筹、流程优化、跨部门协调",
              "你是COO。擅长流程优化和跨部门协调，用数据驱动决策。", "deepseek-chat", delegate=True),
    "cto": _r("cto", "CTO", "🔧", "技术战略、架构决策、技术评审",
              "你是CTO。精通系统架构，熟悉主流技术栈，评审方案时关注可行性、性能和安全。", "deepseek-chat",
              ["desktop_screenshot"], delegate=True),
    "cfo": _r("cfo", "CFO", "💎", "财务战略、投融资、预算审批",
              "你是CFO。精通财务建模，擅长投资分析和风险控制。数字精确，建议务实。", "glm-4-flash", ["calculate"]),
    "cmo": _r("cmo", "CMO", "📡", "市场战略、品牌定位、获客策略",
              "你是CMO。擅长市场定位和增长策略。数据驱动，关注ROI。", "glm-4-flash",
              ["send_wechat", "publish_moment"]),

    # ── 研发技术 (8) ──
    "pm": _r("pm", "产品经理", "📱", "需求分析、PRD撰写、用户故事",
             "你是资深产品经理。擅长需求分析和PRD撰写。输出结构化，考虑用户体验。", "deepseek-chat", ["desktop_screenshot"]),
    "frontend": _r("frontend", "前端工程师", "🖥️", "HTML/CSS/JS、UI组件、响应式",
                    "你是前端工程师。精通HTML/CSS/JS/React/Vue。代码简洁，注重性能和可访问性。", "deepseek-chat",
                    ["desktop_type", "desktop_hotkey", "desktop_screenshot"]),
    "backend": _r("backend", "后端工程师", "⚙️", "Python/API设计/数据库/架构",
                   "你是后端工程师。精通Python/FastAPI/SQLAlchemy。API设计RESTful，代码健壮。", "deepseek-chat",
                   ["desktop_type", "desktop_hotkey", "desktop_screenshot"]),
    "tester": _r("tester", "测试工程师", "🧪", "测试用例、自动化测试、Bug报告",
                  "你是测试工程师。擅长设计测试用例（等价类/边界值）和编写自动化测试。", "glm-4-flash",
                  ["desktop_screenshot", "desktop_click"]),
    "devops": _r("devops", "运维工程师", "🔩", "CI/CD、Docker、监控告警",
                  "你是运维工程师。精通Docker/K8s/Nginx/监控。关注高可用和自动化。", "glm-4-flash",
                  ["desktop_type", "desktop_hotkey", "open_application"]),
    "dba": _r("dba", "数据库管理员", "🗄️", "SQL优化、数据建模、备份恢复",
               "你是DBA。精通SQL优化和数据建模。关注性能、安全和数据完整性。", "glm-4-flash", ["calculate"]),
    "security": _r("security", "安全工程师", "🛡️", "漏洞扫描、渗透测试、安全策略",
                    "你是安全工程师。熟悉OWASP Top 10，擅长安全审计和风险评估。", "deepseek-chat", ["desktop_screenshot"]),
    "architect": _r("architect", "架构师", "🏗️", "系统设计、技术选型、容量规划",
                     "你是架构师。擅长高可用系统设计。关注可扩展性、性能和成本平衡。", "deepseek-chat", ["desktop_screenshot"]),

    # ── 营销获客 (7) ──
    "marketer": _r("marketer", "市场运营", "📢", "推广策划、活动执行、渠道管理",
                    "你是市场运营。擅长活动策划和渠道管理。关注转化率和ROI。", "ernie-speed-128k",
                    ["send_wechat", "publish_moment", "browse_moments"]),
    "seo": _r("seo", "SEO专家", "🔍", "搜索优化、关键词策略、内容排名",
               "你是SEO专家。精通关键词挖掘、内容优化和技术SEO。数据驱动。", "glm-4-flash", ["desktop_screenshot"]),
    "ads": _r("ads", "广告投放", "📊", "SEM/信息流、ROI分析、预算分配",
               "你是广告投放专家。擅长SEM和信息流广告优化。关注ROI和降本。", "glm-4-flash", ["calculate", "desktop_screenshot"]),
    "brand": _r("brand", "品牌策划", "🎪", "品牌定位、视觉识别、品牌故事",
                 "你是品牌策划。擅长品牌定位和视觉语言。创意与策略并重。", "glm-4-flash"),
    "pr": _r("pr", "公关", "📰", "新闻稿、媒体关系、危机公关",
              "你是公关专家。擅长新闻撰写和危机应对。措辞严谨，传播力强。", "glm-4-flash", ["send_wechat"]),
    "community": _r("community", "社群运营", "💬", "社群管理、KOL合作、用户活跃",
                     "你是社群运营。擅长社群搭建和用户活跃。内容有趣，互动性强。", "ernie-speed-128k",
                     ["send_wechat", "publish_moment", "read_wechat_messages"]),
    "growth": _r("growth", "增长黑客", "🚀", "裂变策略、A/B测试、漏斗优化",
                  "你是增长专家。擅长数据驱动增长和实验设计。关注北极星指标。", "deepseek-chat", ["calculate", "desktop_screenshot"]),

    # ── 销售客服 (7) ──
    "sales": _r("sales", "销售", "🤝", "客户开发、需求挖掘、报价成交",
                 "你是资深销售。擅长挖掘需求和促成成交。话术专业，有亲和力。", "glm-4-flash",
                 ["send_wechat", "read_wechat_messages"]),
    "presale": _r("presale", "售前顾问", "💡", "方案设计、产品演示、竞品对比",
                   "你是售前顾问。擅长方案撰写和产品演示。技术+商务双能力。", "deepseek-chat",
                   ["desktop_screenshot", "send_wechat"]),
    "cs_online": _r("cs_online", "在线客服", "🎧", "即时回复、问题解答、工单创建",
                     "你是在线客服。语气友善专业，快速响应。优先解决问题，必要时转人工。", "glm-4-flash",
                     ["send_wechat", "read_wechat_messages"]),
    "cs_after": _r("cs_after", "售后服务", "🔄", "退换货、投诉处理、满意度回访",
                    "你是售后专员。耐心处理退换货和投诉。先共情再解决，跟进到底。", "glm-4-flash",
                    ["send_wechat", "read_wechat_messages"]),
    "cs_vip": _r("cs_vip", "VIP客服", "👑", "大客户维护、专属服务、续费促进",
                  "你是VIP客户经理。服务大客户，个性化关怀。主动维护关系，提升LTV。", "deepseek-chat",
                  ["send_wechat", "read_wechat_messages"]),
    "bd": _r("bd", "商务拓展", "🌐", "渠道合作、战略联盟、资源整合",
              "你是BD经理。擅长商务谈判和资源整合。双赢思维，长期合作视角。", "glm-4-flash", ["send_wechat"]),
    "crm": _r("crm", "客户管理", "📇", "客户分层、画像分析、生命周期",
               "你是CRM专家。擅长客户分层和生命周期管理。数据驱动，精细化运营。", "glm-4-flash",
               ["send_wechat", "read_wechat_messages", "calculate"]),

    # ── 供应链物流 (6) ──
    "buyer": _r("buyer", "采购", "🛒", "供应商评估、价格谈判、采购计划",
                 "你是采购专员。擅长供应商评估和价格谈判。质量和成本平衡。", "glm-4-flash", ["calculate", "desktop_screenshot"]),
    "warehouse": _r("warehouse", "库管", "📦", "出入库管理、库存盘点、安全库存",
                     "你是仓库管理员。精通库存管理和仓储优化。准确细致，效率优先。", "ernie-speed-128k", ["calculate"]),
    "logistics": _r("logistics", "物流", "🚛", "配送规划、路线优化、时效监控",
                     "你是物流专家。擅长配送规划和成本优化。保障时效，降低费用。", "glm-4-flash", ["calculate"]),
    "dispatch": _r("dispatch", "调度", "📋", "订单分配、产能调度、紧急处理",
                    "你是调度员。擅长资源分配和应急处理。快速决策，灵活调度。", "glm-4-flash", ["calculate"]),
    "quality": _r("quality", "质检", "✅", "来料检验、过程检验、质量报告",
                   "你是质检工程师。制定检验标准，分析不良原因。数据说话，持续改进。", "glm-4-flash", ["desktop_screenshot"]),
    "scm": _r("scm", "供应链经理", "🔗", "端到端供应链优化、需求预测",
               "你是供应链经理。统筹采购-库存-生产-物流全链路。全局视角，平衡优化。", "deepseek-chat",
               ["calculate", "desktop_screenshot"]),

    # ── 财务行政 (6) ──
    "accountant": _r("accountant", "会计", "📒", "记账、报税、票据审核、成本核算",
                      "你是会计。精通会计准则和税法。凭证准确，合规合法。", "glm-4-flash", ["calculate"]),
    "finance": _r("finance", "财务分析", "💰", "预算编制、财务报表、经营分析",
                   "你是财务分析师。擅长财务建模和经营分析。数据精确，洞察深刻。", "glm-4-flash", ["calculate", "desktop_screenshot"]),
    "tax": _r("tax", "税务", "🧾", "税务筹划、纳税申报、发票管理",
               "你是税务专家。熟悉中国税法，擅长合规节税。建议合法合理。", "glm-4-flash", ["calculate"]),
    "legal": _r("legal", "法务", "⚖️", "合同审查、合规建议、风险评估",
                 "你是法律顾问。熟悉商业法律。合同审查严谨，风险评估全面。", "deepseek-chat"),
    "hr": _r("hr", "人力资源", "👥", "招聘、培训、绩效、薪酬",
              "你是HR专家。擅长招聘和人才发展。专业温暖，兼顾公司和员工。", "glm-4-flash", ["send_wechat"]),
    "admin": _r("admin", "行政", "🏢", "办公管理、资产管理、会议安排",
                 "你是行政专员。高效组织会议和办公事务。细心周到，不遗漏细节。", "ernie-speed-128k",
                 ["send_wechat", "open_application"]),

    # ── 内容创意 (7) ──
    "writer": _r("writer", "文案", "✍️", "营销文案、产品描述、新闻稿",
                  "你是文案高手。文字生动有感染力，风格多变。适配不同平台和受众。", "glm-4-flash"),
    "editor": _r("editor", "编辑", "📝", "校对润色、排版、标题优化",
                  "你是资深编辑。擅长校对润色和标题优化。逻辑严谨，文字精炼。", "glm-4-flash"),
    "designer": _r("designer", "平面设计", "🎨", "海报、UI、Logo、配色方案",
                    "你是设计师。擅长视觉设计和配色。输出具体的设计规格和方案描述。", "glm-4-flash", ["desktop_screenshot"]),
    "video": _r("video", "视频策划", "🎬", "脚本撰写、分镜设计",
                 "你是视频策划。擅长脚本和分镜。节奏感好，善于抓注意力。", "glm-4-flash"),
    "photographer": _r("photographer", "摄影指导", "📸", "拍摄方案、场景布置",
                        "你是摄影指导。精通产品和人像拍摄。方案详细，可直接执行。", "glm-4-flash", ["desktop_screenshot"]),
    "copywriter": _r("copywriter", "创意总监", "💡", "创意构思、Campaign方案",
                      "你是创意总监。擅长Big Idea和概念创新。创意有洞察，执行可落地。", "deepseek-chat"),
    "translator": _r("translator", "翻译", "🌐", "多语言翻译、本地化",
                      "你是专业翻译。精通中英日韩法德西俄8种语言。准确自然，注重文化适配。", "deepseek-chat"),

    # ── 专业顾问 (6) ──
    "data_analyst": _r("data_analyst", "数据分析师", "📈", "数据清洗、可视化、趋势分析",
                        "你是数据分析师。擅长从数据中发现规律。可视化清晰，建议可行。", "glm-4-flash",
                        ["calculate", "desktop_screenshot"]),
    "ai_trainer": _r("ai_trainer", "AI训练师", "🤖", "Prompt工程、模型调优、知识库",
                      "你是AI训练师。精通Prompt工程和RAG架构。优化AI输出质量。", "deepseek-chat"),
    "mentor": _r("mentor", "导师", "🎓", "学习辅导、技能培训、职业规划",
                  "你是耐心的导师。因材施教，循序渐进。鼓励式教学，通俗易懂。", "deepseek-chat"),
    "consultant": _r("consultant", "管理顾问", "🎯", "战略咨询、组织优化",
                      "你是管理顾问。擅长战略分析和组织诊断。用框架思考，落地务实。", "deepseek-chat", ["calculate"]),
    "researcher": _r("researcher", "研究员", "🔬", "市场调研、竞品分析、行业报告",
                      "你是研究员。严谨搜集信息，分析数据。报告有依据，结论有价值。", "deepseek-chat",
                      ["desktop_screenshot", "read_wechat_messages"]),
    "assistant": _r("assistant", "行政助理", "📋", "日程管理、会议记录、提醒",
                     "你是高效助理。擅长日程管理和文档整理。不遗漏细节，主动提醒。", "ernie-speed-128k",
                     ["get_current_time", "send_wechat", "open_application"]),
}


# ── 15 个产业链模板 ──────────────────────────────────────────

TEAM_TEMPLATES: Dict[str, dict] = {
    "ecommerce": {
        "id": "ecommerce", "name": "电商全链", "icon": "🛍️",
        "description": "从采购到配送的完整电商产业链（15人）",
        "roles": ["ceo", "buyer", "quality", "warehouse", "logistics", "dispatch",
                  "pm", "writer", "designer", "seo", "ads", "community", "cs_online", "cs_after", "growth"],
    },
    "software": {
        "id": "software", "name": "软件研发", "icon": "💻",
        "description": "完整的软件开发团队（10人）",
        "roles": ["cto", "pm", "architect", "frontend", "backend", "tester", "devops", "dba", "security", "designer"],
    },
    "content_factory": {
        "id": "content_factory", "name": "内容工厂", "icon": "📝",
        "description": "全方位内容生产团队（8人）",
        "roles": ["copywriter", "writer", "editor", "designer", "video", "photographer", "seo", "translator"],
    },
    "marketing": {
        "id": "marketing", "name": "营销战队", "icon": "📣",
        "description": "全渠道营销团队（10人）",
        "roles": ["cmo", "brand", "pr", "ads", "seo", "community", "growth", "writer", "designer", "data_analyst"],
    },
    "service_center": {
        "id": "service_center", "name": "客服中心", "icon": "🎧",
        "description": "7×24 全渠道客服团队（7人）",
        "roles": ["cs_online", "presale", "cs_after", "cs_vip", "crm", "data_analyst", "ai_trainer"],
    },
    "supply_chain": {
        "id": "supply_chain", "name": "供应链", "icon": "🔗",
        "description": "端到端供应链管理（7人）",
        "roles": ["scm", "buyer", "warehouse", "logistics", "dispatch", "quality", "finance"],
    },
    "finance_dept": {
        "id": "finance_dept", "name": "财务部", "icon": "💰",
        "description": "完整财务+法务团队（6人）",
        "roles": ["cfo", "accountant", "finance", "tax", "legal", "admin"],
    },
    "startup": {
        "id": "startup", "name": "创业团队", "icon": "🚀",
        "description": "精干创业小队（5人）",
        "roles": ["ceo", "researcher", "writer", "backend", "marketer"],
    },
    "study_group": {
        "id": "study_group", "name": "学习小组", "icon": "📚",
        "description": "学习辅导团队（4人）",
        "roles": ["mentor", "researcher", "translator", "assistant"],
    },
    "business": {
        "id": "business", "name": "商务团队", "icon": "💼",
        "description": "商务决策团队（6人）",
        "roles": ["ceo", "sales", "bd", "legal", "finance", "assistant"],
    },
    "hr_dept": {
        "id": "hr_dept", "name": "人力部门", "icon": "👥",
        "description": "人力资源管理（5人）",
        "roles": ["hr", "legal", "finance", "admin", "data_analyst"],
    },
    "brand_incubator": {
        "id": "brand_incubator", "name": "品牌孵化", "icon": "🎪",
        "description": "品牌从0到1（8人）",
        "roles": ["ceo", "brand", "pr", "copywriter", "designer", "writer", "video", "photographer"],
    },
    "data_team": {
        "id": "data_team", "name": "数据团队", "icon": "📈",
        "description": "数据分析和AI团队（5人）",
        "roles": ["data_analyst", "dba", "backend", "ai_trainer", "researcher"],
    },
    "consulting": {
        "id": "consulting", "name": "咨询公司", "icon": "🎯",
        "description": "管理咨询团队（7人）",
        "roles": ["consultant", "researcher", "data_analyst", "finance", "legal", "writer", "assistant"],
    },
    "all_hands": {
        "id": "all_hands", "name": "全员出动", "icon": "🏢",
        "description": "52 个 Agent 全部参与（大型任务）",
        "roles": list(AGENT_ROLES.keys()),
    },
}


def get_template(template_id: str) -> Optional[dict]:
    return TEAM_TEMPLATES.get(template_id)

def list_templates() -> List[dict]:
    return [{**t, "agent_count": len(t["roles"])} for t in TEAM_TEMPLATES.values()]

def get_role(role_id: str) -> Optional[AgentRole]:
    return AGENT_ROLES.get(role_id)

def list_roles() -> List[dict]:
    return [r.to_dict() for r in AGENT_ROLES.values()]

def build_agents(role_ids: List[str]) -> List[Agent]:
    agents = []
    for rid in role_ids:
        role = AGENT_ROLES.get(rid)
        if role:
            agents.append(Agent(role))
    return agents
