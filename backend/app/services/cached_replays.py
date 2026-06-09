"""
Cached replay cases for live demos.

These cases avoid network, LLM, Neo4j, OASIS, Torch, and GPU dependencies. They
return the same payload shape as /api/simulation/<id>/replay so the existing
SimulationReplayView can present a stable Manus-style viewing mode.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid5, NAMESPACE_DNS


NB_PROJECT_ID = "proj_nb_hnw_ai_case"
NB_HNW_AI_CASE_ID = "sim_nb_hnw_ai_case"
NB_GRAPH_ID = "cached_nb_hnw_ai_graph"
NB_REPORT_ID = "report_nb_hnw_ai_case"
NB_REQUIREMENT = "以宁波银行大客户经理为核心，为高净值客户推介科技、AI相关理财产品组合，并预测产品组成与销售效果。"
NB_CREATED_AT = "2026-06-04T09:30:00"

COURSE_SIM_ID = "sim_16eb13645a7b"
COURSE_PROJECT_ID = "proj_f86a0145b608"
COURSE_GRAPH_ID = "foresight_12df9a5405604f92"
COURSE_REPORT_ID = "report_tongzhou_course_case"
COURSE_REQUIREMENT = (
    "一舟一课线下课第一期招生、收款、优惠结构、退款舆情与交付风险双世界模拟。"
    "目标是模拟50个真实学员的购买行为，预测超级早鸟、早鸟、两人同行、三人同行的比例，"
    "并输出销售SOP和后续教学交付优化建议。"
)
COURSE_CREATED_AT = "2026-06-08T21:10:09"


CASE_AGENTS = [
    (0, "宁波银行大客户经理", "KeyAccountManager", "负责高净值客户资产配置、产品组合推介与合规确认。"),
    (1, "高净值客户A", "HighNetWorthClient", "制造业企业主，关注长期稳健收益与科技主题成长性。"),
    (2, "私行投资顾问", "PrivateBankingAdvisor", "负责组合建议、风险匹配和产品说明。"),
    (3, "科技主题基金经理", "TechFundManager", "关注AI算力、半导体、云基础设施与软件生态。"),
    (4, "固收产品经理", "FixedIncomePM", "提供现金管理、短债、同业存单与中高等级信用债建议。"),
    (5, "风控合规经理", "RiskCompliance", "检查适当性、集中度、流动性和宣传口径。"),
    (6, "AI行业研究员", "AIIndustryAnalyst", "跟踪AI产业链变量、订单和估值波动。"),
    (7, "客户家族办公室代表", "FamilyOffice", "关注传承、回撤控制、税务与多账户执行。"),
    (8, "配偶共同决策人", "FamilyDecisionMaker", "关注家庭安全垫、教育金安排和回撤体验。"),
    (9, "二代继承人", "NextGenDecisionMaker", "关注AI技术机会、长期成长和家族企业数字化。"),
    (10, "企业财务负责人", "CorporateCFO", "关注企业现金流、闲置资金和资金使用窗口。"),
    (11, "分行财富主管", "BranchWealthLead", "关注AUM新增、客户经营节奏和团队复制。"),
    (12, "总行产品准入经理", "ProductAccessManager", "关注产品白名单、风险等级和准入口径。"),
    (13, "运营留痕专员", "OpsArchiveSpecialist", "关注客户确认、录音录像和材料归档。"),
    (14, "客户服务经理", "ServiceManager", "负责会后跟进、复盘提醒和客户体验维护。"),
    (15, "量化对冲产品经理", "QuantPM", "解释低相关资产和回撤控制工具。"),
    (16, "黄金多资产策略师", "MultiAssetStrategist", "解释黄金、多资产和汇率波动对冲逻辑。"),
    (17, "半导体研究员", "SemiconductorAnalyst", "跟踪国产替代、设备材料和先进封装机会。"),
    (18, "云计算研究员", "CloudAnalyst", "跟踪云厂商盈利弹性、AI应用和企业软件复苏。"),
    (19, "数据中心研究员", "DataCenterAnalyst", "跟踪算力基础设施、电力约束和REITs机会。"),
    (20, "利率策略师", "RateStrategist", "跟踪利率下行、久期风险和信用利差。"),
    (21, "汇率策略师", "FXStrategist", "跟踪人民币汇率、海外资产顾虑和黄金配置。"),
    (22, "同圈层企业主B", "PeerClient", "观察同类客户是否愿意接受AI主题配置。"),
    (23, "保守型客户C", "ConservativeClient", "代表低波动偏好客户，对权益主题保持谨慎。"),
    (24, "进取型客户D", "AggressiveClient", "代表高风险偏好客户，关注AI主题弹性。"),
    (25, "客户朋友推荐人", "ReferralSource", "观察客户满意度和转介绍机会。"),
    (26, "合规质检员", "ComplianceAuditor", "审查话术、适当性和留痕完整度。"),
    (27, "家族信托顾问", "TrustAdvisor", "承接税务传承、资产隔离和家庭治理需求。"),
    (28, "保险金信托顾问", "InsuranceTrustAdvisor", "承接保障、传承和交叉销售机会。"),
    (29, "销售管理看板", "SalesAnalytics", "聚合首轮成交、二次转化、AUM和服务满意度指标。"),
]


CASE_AGENT_PERSONAS = {
    0: {"display_name": "周明远", "title": "宁波银行宁波分行大客户经理", "organization": "宁波银行宁波分行", "persona_role": "银行客户经理", "age": 39, "mbti": "ENTJ"},
    1: {"display_name": "陈启航", "title": "舟山精密制造企业董事长", "organization": "启航精密制造集团", "persona_role": "高净值客户 / 制造业企业主", "age": 56, "mbti": "ISTJ"},
    2: {"display_name": "何婉清", "title": "宁波银行私人银行投资顾问", "organization": "宁波银行私人银行中心", "persona_role": "私行投资顾问", "age": 36, "mbti": "ENFJ"},
    3: {"display_name": "林泽宇", "title": "科技主题基金投资经理", "organization": "华东科技成长基金", "persona_role": "科技基金经理", "age": 41, "mbti": "INTJ"},
    4: {"display_name": "蒋亦辰", "title": "宁波银行固收产品经理", "organization": "宁波银行资产管理部", "persona_role": "固收产品经理", "age": 38, "mbti": "ISTJ"},
    5: {"display_name": "郑雅宁", "title": "宁波银行财富合规风控经理", "organization": "宁波银行财富合规部", "persona_role": "风控合规经理", "age": 42, "mbti": "ISTJ"},
    6: {"display_name": "罗景行", "title": "AI产业链首席研究员", "organization": "甬江产业研究院", "persona_role": "AI行业研究员", "age": 37, "mbti": "INTP"},
    7: {"display_name": "顾澜", "title": "陈启航家族办公室顾问", "organization": "启航家族办公室", "persona_role": "家族办公室代表", "age": 45, "mbti": "INFJ"},
    8: {"display_name": "沈雨薇", "title": "陈启航配偶 / 家庭共同决策人", "organization": "启航家庭资产委员会", "persona_role": "家庭共同决策人", "age": 53, "mbti": "ISFJ"},
    9: {"display_name": "陈知远", "title": "家族企业数字化负责人", "organization": "启航精密制造集团", "persona_role": "二代继承人", "age": 31, "mbti": "ENTP"},
    10: {"display_name": "赵立衡", "title": "舟山精密制造财务总监", "organization": "启航精密制造集团", "persona_role": "企业财务负责人", "age": 47, "mbti": "ISTJ"},
    11: {"display_name": "孙若谷", "title": "宁波银行分行财富管理部负责人", "organization": "宁波银行宁波分行", "persona_role": "分行财富主管", "age": 44, "mbti": "ESTJ"},
    12: {"display_name": "胡静姝", "title": "宁波银行总行产品准入经理", "organization": "宁波银行总行财富产品部", "persona_role": "总行产品准入经理", "age": 40, "mbti": "ISTJ"},
    13: {"display_name": "唐可", "title": "宁波银行运营留痕专员", "organization": "宁波银行运营支持中心", "persona_role": "运营留痕专员", "age": 32, "mbti": "ISFJ"},
    14: {"display_name": "许安澜", "title": "宁波银行私人银行客户服务经理", "organization": "宁波银行私人银行中心", "persona_role": "客户服务经理", "age": 34, "mbti": "ESFJ"},
    15: {"display_name": "马承骁", "title": "量化对冲产品经理", "organization": "东方量化资产管理", "persona_role": "量化对冲产品经理", "age": 40, "mbti": "INTJ"},
    16: {"display_name": "金若宁", "title": "黄金与多资产策略师", "organization": "甬江多资产研究中心", "persona_role": "多资产策略师", "age": 35, "mbti": "ENFP"},
    17: {"display_name": "邵砚", "title": "半导体设备行业研究员", "organization": "华东证券研究所", "persona_role": "半导体研究员", "age": 34, "mbti": "INTP"},
    18: {"display_name": "陆晨曦", "title": "云计算与企业软件研究员", "organization": "甬江产业研究院", "persona_role": "云计算研究员", "age": 33, "mbti": "ENTJ"},
    19: {"display_name": "谢知衡", "title": "数据中心基础设施研究员", "organization": "长三角基础设施研究中心", "persona_role": "数据中心研究员", "age": 36, "mbti": "INTJ"},
    20: {"display_name": "顾廷川", "title": "利率与信用策略师", "organization": "宁波银行金融市场部", "persona_role": "利率策略师", "age": 43, "mbti": "ISTJ"},
    21: {"display_name": "方舒越", "title": "外汇与黄金策略师", "organization": "宁波银行金融市场部", "persona_role": "汇率策略师", "age": 37, "mbti": "ENTP"},
    22: {"display_name": "俞博文", "title": "汽车零部件公司创始人", "organization": "博文汽车零部件", "persona_role": "同圈层高净值客户", "age": 54, "mbti": "ESTP"},
    23: {"display_name": "戴敏", "title": "连锁药房股东 / 保守型高净值客户", "organization": "民安连锁药房", "persona_role": "保守型客户", "age": 58, "mbti": "ISFJ"},
    24: {"display_name": "韩峥", "title": "互联网创业者 / 进取型高净值客户", "organization": "灵犀数据科技", "persona_role": "进取型客户", "age": 38, "mbti": "ENTP"},
    25: {"display_name": "叶楚航", "title": "宁波商会副会长 / 客户朋友推荐人", "organization": "宁波青年企业家商会", "persona_role": "转介绍推荐人", "age": 49, "mbti": "ENFJ"},
    26: {"display_name": "宋知夏", "title": "宁波银行合规质检员", "organization": "宁波银行财富合规部", "persona_role": "合规质检员", "age": 31, "mbti": "ISTJ"},
    27: {"display_name": "魏清和", "title": "家族信托顾问", "organization": "甬信家族办公室服务中心", "persona_role": "家族信托顾问", "age": 46, "mbti": "INFJ"},
    28: {"display_name": "乔若琳", "title": "保险金信托顾问", "organization": "甬诚保险经纪", "persona_role": "保险金信托顾问", "age": 39, "mbti": "ESFJ"},
    29: {"display_name": "彭越", "title": "分行财富销售数据分析师", "organization": "宁波银行数据经营团队", "persona_role": "销售数据分析师", "age": 33, "mbti": "INTP"},
}


def _agent_persona(agent_id: int, fallback_name: str, fallback_role: str, fallback_bio: str) -> Dict[str, Any]:
    persona = CASE_AGENT_PERSONAS.get(agent_id, {})
    display_name = persona.get("display_name", fallback_name)
    title = persona.get("title", fallback_role)
    role_name = persona.get("persona_role", fallback_name)
    organization = persona.get("organization", "宁波银行案例模拟世界")
    return {
        "display_name": display_name,
        "title": title,
        "organization": organization,
        "persona_role": role_name,
        "age": persona.get("age", 42),
        "mbti": persona.get("mbti", "ISTJ"),
        "bio": f"{display_name}，{title}，来自{organization}。{fallback_bio}",
    }


def _agent_profile_payload(agent_id: int, name: str, role: str, bio: str) -> Dict[str, Any]:
    persona = _agent_persona(agent_id, name, role, bio)
    agent_code = f"A{agent_id:02d}"
    return {
        "id": agent_id,
        "agent_id": agent_id,
        "name": agent_code,
        "handle": agent_code,
        "username": persona["display_name"],
        "display_name": persona["display_name"],
        "real_name": persona["display_name"],
        "entity_name": name,
        "entity_type": role,
        "role": persona["persona_role"],
        "title": persona["title"],
        "profession": persona["title"],
        "organization": persona["organization"],
        "bio": persona["bio"],
        "persona": f"{persona['display_name']}以“{persona['persona_role']}”身份参与本案例，围绕高净值客户AI理财组合推介讨论资产配置、风险边界、服务动作和销售转化。",
        "interested_topics": ["科技理财", "AI产业链", "资产配置", "合规销售"],
        "age": persona["age"],
        "gender": "other",
        "country": "CN",
        "mbti": persona["mbti"],
    }


def _case_time(minutes: int = 0) -> str:
    return (datetime.fromisoformat(NB_CREATED_AT) + timedelta(minutes=minutes)).isoformat()


def _stable_uuid(name: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"foresight.nb-hnw-ai.{name}"))


def _cached_files() -> List[Dict[str, Any]]:
    return [
        {"filename": "宁波银行高净值客户AI理财组合缓存案例.md", "size": 4096},
        {"filename": "产品组合与销售效果回放.json", "size": 8192},
        {"filename": "拜访提纲与合规话术.md", "size": 3072},
    ]


def get_cached_project(project_id: str) -> Optional[Dict[str, Any]]:
    if project_id != NB_PROJECT_ID:
        return None

    return {
        "project_id": NB_PROJECT_ID,
        "name": "宁波银行高净值客户AI理财组合推介",
        "status": "graph_completed",
        "created_at": NB_CREATED_AT,
        "updated_at": _case_time(70),
        "files": _cached_files(),
        "total_text_length": 4096,
        "ontology": {
            "entity_types": [
                {"name": "Bank", "description": "银行机构与经营主体"},
                {"name": "BusinessUnit", "description": "财富管理、私行和投顾中台"},
                {"name": "KeyAccountManager", "description": "银行大客户经理"},
                {"name": "HighNetWorthClient", "description": "高净值客户"},
                {"name": "DecisionMaker", "description": "家庭或企业决策参与人"},
                {"name": "ClientNeed", "description": "客户显性与隐性需求"},
                {"name": "PrivateBankingAdvisor", "description": "私行投资顾问"},
                {"name": "FinancialProduct", "description": "理财与资产配置产品"},
                {"name": "Portfolio", "description": "产品组合与配置方案"},
                {"name": "RiskCompliance", "description": "风控合规角色"},
                {"name": "MarketVariable", "description": "影响产品销售与配置的市场变量"},
                {"name": "ComplianceProcess", "description": "适当性、准入、留痕与风险揭示流程"},
                {"name": "SalesStage", "description": "客户经营与销售转化阶段"},
                {"name": "BusinessOutcome", "description": "销售、AUM、粘性与满意度结果"},
            ],
            "relationship_types": [
                "SERVES", "ADVISES", "RECOMMENDS", "CONTAINS", "CONSTRAINS", "PREDICTS", "MONITORS",
                "INFLUENCES", "REQUIRES", "VALIDATES", "APPROVES", "MITIGATES", "TRIGGERS",
                "SUPPORTS", "FOLLOWS_UP", "CONVERTS_TO", "ALLOCATES_TO", "HEDGES_WITH", "DEPENDS_ON"
            ],
        },
        "analysis_summary": "现场缓存案例：围绕宁波银行大客户经理、高净值客户、私行投顾、科技/AI主题产品、固收底仓和合规约束，构建可回溯的项目过程。",
        "graph_id": NB_GRAPH_ID,
        "graph_build_task_id": None,
        "simulation_requirement": NB_REQUIREMENT,
        "chunk_size": 250,
        "chunk_overlap": 50,
        "error": None,
    }


def get_cached_graph(graph_id: str) -> Optional[Dict[str, Any]]:
    if graph_id != NB_GRAPH_ID:
        return None

    entities = [
        ("宁波银行", "Bank", "提供私行、财富管理和企业金融服务的核心机构。"),
        ("总行财富管理部", "BusinessUnit", "负责产品策略、财富客群经营和销售支持。"),
        ("宁波银行私行中心", "BusinessUnit", "承接高净值客户资产配置、投顾服务和家族场景经营。"),
        ("分行经营管理层", "BusinessUnit", "关注大客户经营、AUM增长和合规销售质量。"),
        ("投顾中台", "BusinessUnit", "沉淀组合模型、市场观点和标准化材料。"),
        ("运营支持团队", "BusinessUnit", "负责材料准备、客户确认、回访与留痕归档。"),
        ("宁波银行大客户经理", "KeyAccountManager", "本次推介的主导角色，负责客户沟通、方案组织和服务切入。"),
        ("私行投资顾问", "PrivateBankingAdvisor", "负责组合建议、风险匹配和产品说明。"),
        ("科技主题基金经理", "PrivateBankingAdvisor", "解释科技权益仓的产业逻辑、估值风险和调仓纪律。"),
        ("固收产品经理", "PrivateBankingAdvisor", "解释短债、信用债、同业存单和固收增强底仓。"),
        ("AI行业研究员", "MarketVariable", "跟踪AI产业链、算力、半导体和云基础设施变量。"),
        ("风控合规经理", "RiskCompliance", "检查适当性、集中度、流动性和宣传口径。"),
        ("产品准入委员会", "RiskCompliance", "控制产品白名单、风险等级和销售适配边界。"),
        ("高净值客户A", "HighNetWorthClient", "制造业企业主，关注稳健收益、流动性和科技主题成长敞口。"),
        ("配偶共同决策人", "DecisionMaker", "关注家庭安全垫、子女安排和回撤体验。"),
        ("二代继承人", "DecisionMaker", "关注AI技术、长期成长和家族企业转型机会。"),
        ("客户家族办公室代表", "DecisionMaker", "关注传承、回撤控制、税务与多账户执行。"),
        ("企业财务负责人", "DecisionMaker", "关注企业现金流、闲置资金和资金使用窗口。"),
        ("企业现金流", "ClientNeed", "企业主家庭与经营资产之间的资金调度约束。"),
        ("家庭资产安全垫", "ClientNeed", "保证生活、教育、医疗和企业周转的基础资产。"),
        ("流动性需求", "ClientNeed", "要求组合保留可赎回、可调仓和应急资金比例。"),
        ("风险偏好画像", "ClientNeed", "中等风险偏好，可接受有限波动但反感单一押注。"),
        ("税务与传承诉求", "ClientNeed", "关注资产隔离、传承安排和家庭治理。"),
        ("教育金计划", "ClientNeed", "为下一代教育保留稳定现金流安排。"),
        ("海外资产顾虑", "ClientNeed", "关注汇率、跨境配置和境内替代方案。"),
        ("科技AI产品组合", "Portfolio", "推荐组合：现金20%、固收40%、科技权益22%、AI观察仓8%、黄金/多资产10%。"),
        ("稳健观察档", "Portfolio", "低波动版本，科技和AI主题仓位控制在20%以内。"),
        ("均衡参与档", "Portfolio", "现场主推版本，在稳健底仓上加入可解释的科技成长敞口。"),
        ("进取主题档", "Portfolio", "高波动版本，仅作为对比展示，不作为默认推荐。"),
        ("现金管理产品", "FinancialProduct", "保留家庭流动性和可调仓弹性。"),
        ("短债理财", "FinancialProduct", "作为现金替代与短期资金停泊工具。"),
        ("同业存单策略", "FinancialProduct", "提供稳健票息与低久期管理。"),
        ("固收增强产品", "FinancialProduct", "作为组合底仓，承担稳健收益和波动缓冲功能。"),
        ("高等级信用债", "FinancialProduct", "作为中低波动收益来源。"),
        ("科技主题基金", "FinancialProduct", "用于表达AI基础设施、半导体设备和云软件成长机会。"),
        ("半导体设备基金", "FinancialProduct", "覆盖国产替代、设备材料和先进封装机会。"),
        ("云计算软件基金", "FinancialProduct", "覆盖云厂商盈利弹性与企业软件复苏。"),
        ("国产算力主题产品", "FinancialProduct", "覆盖国产GPU、服务器、网络设备和数据中心产业链。"),
        ("AI主题理财产品", "FinancialProduct", "作为观察仓参与AI产业链主题，但控制比例和波动。"),
        ("结构化票据观察仓", "FinancialProduct", "用于降低直接权益波动，但需清楚解释敲入敲出情景。"),
        ("指数增强产品", "FinancialProduct", "提供宽基参与和超额收益尝试。"),
        ("量化对冲产品", "FinancialProduct", "用于降低组合相关性和回撤。"),
        ("数据中心REITs", "FinancialProduct", "表达数字基础设施资产收益。"),
        ("黄金多资产产品", "FinancialProduct", "作为组合分散和避险资产。"),
        ("保险金信托", "FinancialProduct", "承接家庭保障与传承安排。"),
        ("家族信托", "FinancialProduct", "用于长期传承、资产隔离和家庭治理。"),
        ("AI资本开支", "MarketVariable", "影响算力、服务器、数据中心和云基础设施景气度。"),
        ("国产芯片替代", "MarketVariable", "影响半导体设备、国产算力和软件生态预期。"),
        ("云厂商盈利弹性", "MarketVariable", "影响云计算软件、AI应用和平台公司估值。"),
        ("数据中心电力约束", "MarketVariable", "影响数据中心建设节奏、REITs和基础设施成本。"),
        ("利率下行", "MarketVariable", "影响固收类产品吸引力与久期策略。"),
        ("人民币汇率波动", "MarketVariable", "影响海外资产顾虑、黄金配置和企业资金安排。"),
        ("政策支持窗口", "MarketVariable", "影响科技主题风险偏好和客户接受度。"),
        ("市场估值分位", "MarketVariable", "决定科技权益仓位上限和分批建仓节奏。"),
        ("回撤预警线", "ComplianceProcess", "当组合回撤触及阈值时触发复盘与风险提示。"),
        ("组合波动率", "ComplianceProcess", "用于评估客户是否能接受科技和AI主题敞口。"),
        ("单产品集中度", "ComplianceProcess", "防止单一产品或单一主题过度集中。"),
        ("久期风险", "ComplianceProcess", "约束固收底仓的利率敏感度。"),
        ("信用利差", "MarketVariable", "影响高等级信用债和固收增强收益风险比。"),
        ("流动性压力测试", "ComplianceProcess", "验证客户在突发用钱场景下的可赎回能力。"),
        ("客户画像访谈", "SalesStage", "从家庭、企业、现金流和风险偏好理解客户真实需求。"),
        ("家庭资产诊断", "SalesStage", "将家庭资产结构、企业现金流和未来支出可视化。"),
        ("适当性风险测评", "ComplianceProcess", "先做适当性匹配，再进入产品推介。"),
        ("产品说明书", "ComplianceProcess", "正式产品介绍与风险揭示依据。"),
        ("风险揭示书", "ComplianceProcess", "明确不承诺收益、波动和极端情景。"),
        ("组合建议书", "SalesStage", "把多产品比例、逻辑和后续服务节奏写成可沟通材料。"),
        ("首次拜访", "SalesStage", "客户经理建立问题框架与机会认知。"),
        ("二次家庭会议", "SalesStage", "让共同决策人理解组合和风险边界。"),
        ("产品准入确认", "ComplianceProcess", "确认产品在销售白名单和客户风险等级范围内。"),
        ("客户确认录音录像", "ComplianceProcess", "保存客户知情、确认和风险揭示证据。"),
        ("季度复盘", "SalesStage", "按市场变量与组合表现进行复盘。"),
        ("再平衡触发", "SalesStage", "当估值、回撤或流动性变化时调整仓位。"),
        ("追加配置窗口", "SalesStage", "当客户认可服务且市场回撤提供机会时增加配置。"),
        ("客诉防火墙", "ComplianceProcess", "通过留痕、解释和预期管理降低后续争议。"),
        ("销售转化", "BusinessOutcome", "风险匹配后首轮成交概率约60%-70%，叠加家庭资产诊断后二次转化约75%。"),
        ("首轮成交概率", "BusinessOutcome", "首次拜访到产品配置的成交可能性。"),
        ("二次转化概率", "BusinessOutcome", "家庭会议、资产诊断和季度复盘后的追加配置概率。"),
        ("AUM新增规模", "BusinessOutcome", "新增管理资产规模，是分行经营层关注的结果指标。"),
        ("客户粘性提升", "BusinessOutcome", "通过持续复盘和家庭服务提升长期关系。"),
        ("交叉销售机会", "BusinessOutcome", "从财富管理延伸到企业金融、保险金信托和家族服务。"),
        ("合规留痕完整度", "BusinessOutcome", "衡量销售动作是否可审计、可解释、可复盘。"),
        ("低波动体验", "BusinessOutcome", "客户对组合过程的主观体验，影响续配和转介绍。"),
        ("转介绍机会", "BusinessOutcome", "高净值客户认可后带来的同圈层推荐机会。"),
        ("服务满意度", "BusinessOutcome", "由收益解释、风险提醒、复盘频率和响应速度共同决定。"),
    ]

    nodes = [
        {
            "uuid": _stable_uuid(name),
            "name": name,
            "labels": [label],
            "summary": summary,
            "attributes": {"name": name, "type": label},
            "created_at": NB_CREATED_AT,
        }
        for name, label, summary in entities
    ]

    rels: List[tuple[str, str, str]] = []
    entity_names = {name for name, _, _ in entities}
    seen_rels = set()

    def add(source: str, rel: str, target: str) -> None:
        if source not in entity_names or target not in entity_names:
            return
        key = (source, rel, target)
        if key in seen_rels:
            return
        seen_rels.add(key)
        rels.append(key)

    for source, rel, target in [
        ("宁波银行", "ORGANIZATION_HAS_UNIT", "总行财富管理部"),
        ("宁波银行", "ORGANIZATION_HAS_UNIT", "宁波银行私行中心"),
        ("宁波银行", "ORGANIZATION_HAS_UNIT", "分行经营管理层"),
        ("宁波银行", "EMPLOYS", "宁波银行大客户经理"),
        ("宁波银行私行中心", "HOSTS", "私行投资顾问"),
        ("宁波银行私行中心", "HOSTS", "投顾中台"),
        ("总行财富管理部", "GOVERNS", "产品准入委员会"),
        ("分行经营管理层", "SUPERVISES", "宁波银行大客户经理"),
        ("投顾中台", "SUPPORTS", "私行投资顾问"),
        ("运营支持团队", "SUPPORTS", "客户确认录音录像"),
        ("宁波银行大客户经理", "SERVES", "高净值客户A"),
        ("宁波银行大客户经理", "COLLABORATES_WITH", "私行投资顾问"),
        ("宁波银行大客户经理", "CONSULTS", "风控合规经理"),
        ("宁波银行大客户经理", "USES", "组合建议书"),
        ("私行投资顾问", "DESIGNS", "科技AI产品组合"),
        ("科技主题基金经理", "EXPLAINS", "科技主题基金"),
        ("固收产品经理", "EXPLAINS", "固收增强产品"),
        ("AI行业研究员", "MONITORS", "AI资本开支"),
        ("AI行业研究员", "MONITORS", "国产芯片替代"),
        ("AI行业研究员", "MONITORS", "云厂商盈利弹性"),
        ("AI行业研究员", "MONITORS", "数据中心电力约束"),
        ("风控合规经理", "GOVERNS", "适当性风险测评"),
        ("风控合规经理", "GOVERNS", "风险揭示书"),
        ("产品准入委员会", "APPROVES", "产品准入确认"),
        ("高净值客户A", "WORKS_WITH", "企业财务负责人"),
        ("高净值客户A", "HAS_DECISION_MAKER", "配偶共同决策人"),
        ("高净值客户A", "HAS_DECISION_MAKER", "二代继承人"),
        ("高净值客户A", "DELEGATES_TO", "客户家族办公室代表"),
    ]:
        add(source, rel, target)

    for need in ["企业现金流", "家庭资产安全垫", "流动性需求", "风险偏好画像", "税务与传承诉求", "教育金计划", "海外资产顾虑"]:
        add("高净值客户A", "HAS_NEED", need)
        add("客户画像访谈", "DISCOVERS", need)
        add(need, "INFLUENCES", "科技AI产品组合")

    for decision_maker in ["配偶共同决策人", "二代继承人", "客户家族办公室代表", "企业财务负责人"]:
        add(decision_maker, "PARTICIPATES_IN", "二次家庭会议")
        add(decision_maker, "INFLUENCES", "风险偏好画像")
        add(decision_maker, "REVIEWS", "组合建议书")

    for portfolio in ["稳健观察档", "均衡参与档", "进取主题档"]:
        add("科技AI产品组合", "HAS_SCENARIO", portfolio)
        add("组合建议书", "PRESENTS", portfolio)
        add(portfolio, "PREDICTS", "销售转化")

    portfolio_products = [
        "现金管理产品", "固收增强产品", "科技主题基金", "AI主题理财产品", "黄金多资产产品",
        "短债理财", "同业存单策略", "高等级信用债", "半导体设备基金", "云计算软件基金",
        "国产算力主题产品", "结构化票据观察仓", "指数增强产品", "量化对冲产品", "数据中心REITs",
    ]
    for product in portfolio_products:
        add("科技AI产品组合", "CONTAINS", product)
        add("均衡参与档", "ALLOCATES_TO", product)
        add(product, "CONTRIBUTES_TO", "销售转化")

    for product in ["现金管理产品", "短债理财", "同业存单策略"]:
        add("流动性需求", "REQUIRES", product)
        add(product, "SUPPORTS", "低波动体验")
        add(product, "MITIGATES", "流动性压力测试")

    for product in ["固收增强产品", "高等级信用债", "同业存单策略"]:
        add(product, "DEPENDS_ON", "利率下行")
        add(product, "DEPENDS_ON", "信用利差")
        add(product, "CONSTRAINED_BY", "久期风险")
        add(product, "SUPPORTS", "家庭资产安全垫")

    for product in ["科技主题基金", "半导体设备基金", "云计算软件基金", "国产算力主题产品", "AI主题理财产品"]:
        add(product, "DEPENDS_ON", "市场估值分位")
        add(product, "CONSTRAINED_BY", "回撤预警线")
        add(product, "CONSTRAINED_BY", "单产品集中度")
        add(product, "INFLUENCES", "首轮成交概率")

    for product in ["黄金多资产产品", "量化对冲产品"]:
        add("科技AI产品组合", "HEDGES_WITH", product)
        add(product, "MITIGATES", "组合波动率")
        add(product, "SUPPORTS", "低波动体验")

    for product in ["保险金信托", "家族信托"]:
        add("税务与传承诉求", "REQUIRES", product)
        add(product, "SUPPORTS", "交叉销售机会")
        add(product, "SUPPORTS", "客户粘性提升")

    market_map = {
        "AI资本开支": ["国产算力主题产品", "数据中心REITs", "科技主题基金"],
        "国产芯片替代": ["半导体设备基金", "国产算力主题产品", "AI主题理财产品"],
        "云厂商盈利弹性": ["云计算软件基金", "科技主题基金", "指数增强产品"],
        "数据中心电力约束": ["数据中心REITs", "国产算力主题产品", "AI主题理财产品"],
        "利率下行": ["固收增强产品", "同业存单策略", "高等级信用债"],
        "人民币汇率波动": ["黄金多资产产品", "海外资产顾虑", "企业现金流"],
        "政策支持窗口": ["科技主题基金", "半导体设备基金", "首轮成交概率"],
        "市场估值分位": ["再平衡触发", "追加配置窗口", "进取主题档"],
        "信用利差": ["固收增强产品", "高等级信用债", "低波动体验"],
    }
    for variable, targets in market_map.items():
        for target in targets:
            add(variable, "INFLUENCES", target)
        add("AI行业研究员", "EVALUATES", variable)

    risk_controls = [
        "适当性风险测评", "产品说明书", "风险揭示书", "产品准入确认", "客户确认录音录像",
        "回撤预警线", "组合波动率", "单产品集中度", "久期风险", "流动性压力测试", "客诉防火墙",
    ]
    for control in risk_controls:
        add("风控合规经理", "VALIDATES", control)
        add(control, "CONSTRAINS", "科技AI产品组合")
        add(control, "SUPPORTS", "合规留痕完整度")

    for source, rel, target in [
        ("首次拜访", "LEADS_TO", "客户画像访谈"),
        ("客户画像访谈", "LEADS_TO", "家庭资产诊断"),
        ("家庭资产诊断", "LEADS_TO", "适当性风险测评"),
        ("适当性风险测评", "LEADS_TO", "组合建议书"),
        ("组合建议书", "LEADS_TO", "二次家庭会议"),
        ("二次家庭会议", "LEADS_TO", "客户确认录音录像"),
        ("客户确认录音录像", "LEADS_TO", "销售转化"),
        ("销售转化", "LEADS_TO", "季度复盘"),
        ("季度复盘", "TRIGGERS", "再平衡触发"),
        ("再平衡触发", "TRIGGERS", "追加配置窗口"),
        ("家庭资产诊断", "INCREASES", "二次转化概率"),
        ("二次家庭会议", "INCREASES", "服务满意度"),
        ("季度复盘", "INCREASES", "客户粘性提升"),
        ("追加配置窗口", "INCREASES", "AUM新增规模"),
        ("服务满意度", "INCREASES", "转介绍机会"),
        ("销售转化", "CONVERTS_TO", "AUM新增规模"),
        ("销售转化", "CONVERTS_TO", "客户粘性提升"),
        ("销售转化", "CONVERTS_TO", "交叉销售机会"),
        ("首轮成交概率", "PART_OF", "销售转化"),
        ("二次转化概率", "PART_OF", "销售转化"),
        ("合规留痕完整度", "MITIGATES", "客诉防火墙"),
    ]:
        add(source, rel, target)

    for stage in ["首次拜访", "客户画像访谈", "家庭资产诊断", "组合建议书", "二次家庭会议", "季度复盘", "追加配置窗口"]:
        add("宁波银行大客户经理", "DRIVES", stage)
        add(stage, "SUPPORTS", "服务满意度")

    for outcome in ["首轮成交概率", "二次转化概率", "AUM新增规模", "客户粘性提升", "交叉销售机会", "低波动体验", "转介绍机会", "服务满意度"]:
        add("科技AI产品组合", "PREDICTS", outcome)
        add("均衡参与档", "OPTIMIZES", outcome)

    for source, rel, target in [
        ("家庭资产安全垫", "PRIORITIZES", "稳健观察档"),
        ("风险偏好画像", "MATCHES", "均衡参与档"),
        ("二代继承人", "PREFERS", "进取主题档"),
        ("配偶共同决策人", "PREFERS", "稳健观察档"),
        ("客户家族办公室代表", "PREFERS", "均衡参与档"),
        ("企业财务负责人", "REQUIRES", "现金管理产品"),
        ("海外资产顾虑", "HEDGES_WITH", "黄金多资产产品"),
        ("教育金计划", "REQUIRES", "固收增强产品"),
        ("企业现金流", "REQUIRES", "现金管理产品"),
        ("组合波动率", "INFLUENCES", "服务满意度"),
        ("回撤预警线", "TRIGGERS", "季度复盘"),
        ("单产品集中度", "LIMITS", "进取主题档"),
        ("流动性压力测试", "VALIDATES", "现金管理产品"),
        ("产品说明书", "SUPPORTS", "产品准入确认"),
        ("风险揭示书", "SUPPORTS", "客户确认录音录像"),
        ("客诉防火墙", "PROTECTS", "宁波银行"),
    ]:
        add(source, rel, target)

    edges = []
    for source, rel, target in rels:
        edges.append({
            "uuid": _stable_uuid(f"{source}-{rel}-{target}"),
            "name": rel,
            "fact": f"{source} 与 {target} 在宁波银行高净值客户AI理财组合推介案例中存在 {rel} 关系。",
            "fact_type": rel,
            "source_node_uuid": _stable_uuid(source),
            "target_node_uuid": _stable_uuid(target),
            "source_node_name": source,
            "target_node_name": target,
            "source_name": source,
            "target_name": target,
            "attributes": {"edge_type": rel},
            "created_at": NB_CREATED_AT,
        })

    return {
        "graph_id": NB_GRAPH_ID,
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "entity_types": sorted({label for _, label, _ in entities}),
        "fallback_source": "cached_demo_graph",
    }


def get_cached_simulation(simulation_id: str) -> Optional[Dict[str, Any]]:
    if simulation_id != NB_HNW_AI_CASE_ID:
        return None

    return {
        "simulation_id": NB_HNW_AI_CASE_ID,
        "project_id": NB_PROJECT_ID,
        "graph_id": NB_GRAPH_ID,
        "status": "completed",
        "enable_twitter": True,
        "enable_reddit": True,
        "entities_count": len(CASE_AGENTS),
        "profiles_count": len(CASE_AGENTS),
        "entity_types": [agent[2] for agent in CASE_AGENTS],
        "config_generated": True,
        "created_at": NB_CREATED_AT,
        "updated_at": _case_time(70),
    }


def get_cached_profiles(simulation_id: str, platform: str = "reddit") -> Optional[List[Dict[str, Any]]]:
    if simulation_id != NB_HNW_AI_CASE_ID:
        return None

    profiles = []
    for agent_id, name, role, bio in CASE_AGENTS:
        profiles.append(_agent_profile_payload(agent_id, name, role, bio))
    return profiles


def get_cached_config(simulation_id: str) -> Optional[Dict[str, Any]]:
    if simulation_id != NB_HNW_AI_CASE_ID:
        return None

    agent_configs = []
    for agent_id, name, role, _ in CASE_AGENTS:
        persona = _agent_persona(agent_id, name, role, "")
        active_hours = list(range(9, 19)) if agent_id in (0, 2, 4, 5, 6, 11, 12, 13, 14, 26, 29) else list(range(10, 22))
        agent_configs.append({
            "agent_id": agent_id,
            "name": persona["display_name"],
            "display_name": persona["display_name"],
            "entity_name": name,
            "entity_type": role,
            "role": persona["persona_role"],
            "title": persona["title"],
            "organization": persona["organization"],
            "active_time_period": "09:00-18:00" if active_hours[0] == 9 else "10:00-21:00",
            "active_hours": active_hours,
            "posts_per_hour": 0.7 if agent_id in (0, 2, 6, 11, 29) else 0.35,
            "comments_per_hour": 1.4 if agent_id in (1, 5, 7, 8, 9, 10, 26) else 0.9,
            "response_delay_minutes": 8 + (agent_id % 12),
            "response_delay_min": 5 + (agent_id % 5),
            "response_delay_max": 18 + (agent_id % 9),
            "activity_level": 0.85 if agent_id in (0, 2, 6, 11, 29) else 0.65,
            "sentiment_bias": 0.25 if agent_id in (0, 2, 3, 4, 6, 11, 24, 29) else (-0.15 if agent_id in (5, 23, 26) else 0.0),
            "stance": "support" if agent_id in (0, 2, 3, 4, 6, 11, 24, 29) else ("risk" if agent_id in (5, 23, 26) else "neutral"),
            "influence_weight": 0.95 if agent_id in (0, 1, 2, 5, 7, 11, 29) else 0.65,
        })

    return {
        "time_config": {
            "total_simulation_hours": 8,
            "minutes_per_round": 60,
            "agents_per_hour_min": 8,
            "agents_per_hour_max": 14,
            "peak_hours": [10, 14, 20],
            "peak_activity_multiplier": 1.4,
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "work_activity_multiplier": 1.1,
            "morning_hours": [8, 9, 10],
            "morning_activity_multiplier": 1.0,
            "off_peak_hours": [0, 1, 2, 3, 4, 5, 6],
            "off_peak_activity_multiplier": 0.3,
        },
        "agent_configs": agent_configs,
        "twitter_config": None,
        "reddit_config": {
            "recency_weight": 0.35,
            "popularity_weight": 0.25,
            "relevance_weight": 0.40,
            "viral_threshold": 0.72,
            "echo_chamber_strength": 0.18,
        },
        "event_config": {
            "narrative_direction": "从客户画像和风险测评出发，逐步推演科技/AI主题产品组合的组成、合规边界与销售转化效果。",
            "hot_topics": ["高净值客户", "AI产业链", "科技主题基金", "固收增强", "适当性管理", "销售转化"],
            "initial_posts": [
                {"poster_agent_id": 0, "poster_type": "KeyAccountManager", "content": "客户经理发起高净值客户AI主题组合推介，先确认家庭资产目标与风险边界。"},
                {"poster_agent_id": 2, "poster_type": "PrivateBankingAdvisor", "content": "投顾拆解现金管理、固收增强、科技权益、AI观察仓和黄金多资产的组合比例。"},
                {"poster_agent_id": 5, "poster_type": "RiskCompliance", "content": "合规经理确认不承诺收益，先做适当性匹配，再进行产品说明。"},
            ],
            "events": [
                {"name": "AI主题热度上升", "impact": "提高客户兴趣，同时放大波动担忧。"},
                {"name": "客户要求保留流动性", "impact": "提高现金管理和固收增强比例。"},
            ],
        },
        "generation_reasoning": "时间配置: 8小时现场回溯足以展示客户画像、组合设计、风险确认和销售预测。 | Agent配置: 30个角色覆盖客户家庭、银行前中后台、产品专家、市场变量、同圈层客户和结果看板。 | 初始激活: 从业务目标、双世界舆情、产品组合和合规约束四条线启动讨论。",
        "generated_at": _case_time(20),
        "llm_model": "cached-demo",
    }


def get_cached_config_realtime(simulation_id: str) -> Optional[Dict[str, Any]]:
    config = get_cached_config(simulation_id)
    if not config:
        return None
    return {
        "simulation_id": simulation_id,
        "file_exists": True,
        "file_modified_at": _case_time(20),
        "is_generating": False,
        "generation_stage": "completed",
        "config_generated": True,
        "config": config,
        "summary": {
            "total_agents": len(config.get("agent_configs", [])),
            "simulation_hours": config.get("time_config", {}).get("total_simulation_hours"),
            "initial_posts_count": len(config.get("event_config", {}).get("initial_posts", [])),
            "hot_topics_count": len(config.get("event_config", {}).get("hot_topics", [])),
            "has_twitter_config": False,
            "has_reddit_config": True,
            "generated_at": config.get("generated_at"),
            "llm_model": config.get("llm_model"),
        },
    }


REPORT_SECTIONS = [
    (
        "执行结论",
        "### 这次模拟回答了什么\n\n宁波银行大客户经理面向高净值客户推介科技、AI相关理财产品时，客户真正关心的不是“AI概念是否热门”，而是四件事：家庭资产安全垫是否被保护、科技仓位是否可解释、回撤风险是否有人提前提醒、后续复盘服务是否持续。\n\n### 推荐主路径\n\n- **产品组合**：现金管理20% + 固收增强40% + 科技主题权益22% + AI观察仓8% + 黄金/多资产10%。\n- **销售打法**：先做家庭资产诊断，再讲AI产业链变量，最后给出三档组合，不直接推最高风险档。\n- **预测效果**：完成适当性匹配后，首轮成交概率约60%-70%；加入家庭会议和季度复盘后，二次转化约75%。\n- **关键抓手**：把“理财产品推介”升级为“客户经理持续经营系统”，用可回溯模拟结果训练客户经理的话术、判断节点和合规边界。\n\n> 本报告是基于30个虚拟Agent、8轮双世界交互和48条行为记录生成的情景推演，不使用真实客户隐私或真实交易数据。",
    ),
    (
        "Agent问答暴露的问题",
        "### 关键Agent反馈\n\n- **高净值客户A**暴露的问题：客户接受科技成长敞口，但不接受“单一押注AI”。客户希望先看现金流安排、回撤提醒和季度复盘，而不是先听产品卖点。\n- **配偶共同决策人**暴露的问题：家庭共同决策人对收益叙事不敏感，对“家庭安全垫是否被影响”高度敏感。客户经理如果只对企业主本人讲产品，成交阻力会转移到家庭会议。\n- **企业财务负责人**暴露的问题：企业经营资金不能被锁定，理财方案必须区分家庭资产、企业现金流和临时周转资金。\n- **保守型客户C**暴露的问题：AI主题容易被理解成追热点，必须提供估值分位、分批建仓和仓位上限，否则会触发“高位接盘”的负面联想。\n- **二代继承人**暴露的问题：年轻共同决策人愿意接受AI主题，但偏好更高弹性。系统需要帮助客户经理把进取需求约束在观察仓，而不是让家庭风险偏好被单一成员带偏。\n- **风控合规经理 / 合规质检员**暴露的问题：所有表达必须从“预测收益”改成“情景推演”，并保留风险测评、产品说明、客户确认和会议纪要。\n\n### 问题归纳\n\n1. 客户不是缺产品，而是缺一套能让家庭成员共同理解的资产配置叙事。\n2. 客户经理不是缺话术，而是缺可复盘的判断流程：先问什么、何时进入产品、何时必须停下来做合规确认。\n3. 管理层不是缺销售数据，而是缺能解释“为什么成交/为什么没成交”的过程证据。",
    ),
    (
        "商业机会",
        "### 对银行的机会\n\n- **机会1：高净值客户资产诊断产品化**。把首次拜访从“介绍产品”改为“家庭资产诊断”，输出资产安全垫、现金流、风险偏好、科技主题参与度四张卡片，提升客户信任和复访率。\n- **机会2：AI主题产品组合工具化**。系统自动生成三档组合：稳健观察、均衡参与、进取主题，并给出仓位上限、回撤线、合规话术和下一次复盘触发条件。\n- **机会3：客户经理训练标准化**。把销冠经验拆成Agent工作流：客户画像、共同决策人识别、风险边界、产品组合、异议处理、会后跟进。\n- **机会4：私行团队管理看板**。管理层可以看到首轮成交、二次转化、AUM新增、客户满意度、合规留痕完整度，而不是只看最终成交结果。\n- **机会5：交叉销售线索沉淀**。家族信托、保险金信托、企业现金管理、数据中心REITs、黄金多资产产品都可以从同一次资产诊断中自然浮现。\n\n### 对我们系统的销售价值\n\n这类模拟可以在银行内部变成三种能力：客户经理训战、复杂产品推介预演、管理层复盘。它展示的不是“AI写报告”，而是“AI提前模拟大量客户、家庭成员、投顾和合规角色的真实反应”。",
    ),
    (
        "产品组合与销售路径",
        "### 主推组合：均衡参与档\n\n- 现金管理：20%，用于家庭流动性、临时周转和后续调仓。\n- 固收增强：40%，作为稳定器，承接客户对低波动体验的要求。\n- 科技主题权益：22%，覆盖AI基础设施、半导体设备、云软件。\n- AI观察仓：8%，控制主题热度风险，用小比例参与产业链机会。\n- 黄金/多资产：10%，对冲汇率、风险偏好下行和单一赛道波动。\n\n### 现场拜访路径\n\n1. **先问家庭与企业资金边界**：确认哪些钱不能动，哪些钱可以长期配置。\n2. **再做适当性匹配**：客户风险等级不匹配时，不进入产品推荐。\n3. **展示三档组合**：稳健观察、均衡参与、进取主题，默认推荐均衡参与。\n4. **解释AI变量**：算力资本开支、国产芯片替代、云厂商盈利弹性、数据中心电力约束。\n5. **确认复盘机制**：T+1发送摘要，T+30回访，季度更新变量看板。\n\n### 预测销售效果\n\n- 首轮成交：60%-70%，前提是客户已完成风险匹配并接受组合逻辑。\n- 二次转化：约75%，前提是完成家庭会议和季度复盘。\n- AUM机会：如果客户可投资资产中15%-20%进入组合，团队复制价值明显。\n- 转介绍：客户认可复盘机制后，同圈层企业主B和推荐人路径会被激活。",
    ),
    (
        "合规边界与风险控制",
        "### 必须守住的边界\n\n- 不说“AI产品确定会涨”，只说“在不同市场情景下的组合反应”。\n- 不把科技主题仓位做成主仓，科技权益与AI观察仓合计不超过35%。\n- 不用单一产品承载客户全部AI兴趣，单产品集中度不超过15%。\n- 不绕过适当性测评，不替代正式产品说明书和风险揭示。\n- 不输入真实客户隐私、账户、持仓、授信或交易数据。\n\n### 系统应该强制留痕\n\n- 风险测评结果\n- 产品白名单与风险等级匹配\n- 客户确认与会议纪要\n- 回撤提醒线\n- 季度复盘记录\n- 异议处理记录\n\n这些留痕不是后台负担，而是客户经理可复制、管理层可审计、合规部门可追溯的过程资产。",
    ),
    (
        "下一步系统化落地",
        "### 从Demo到银行采购场景\n\n建议把本案例包装成三层产品能力：\n\n1. **训战层**：输入客户画像，生成客户经理、客户、家庭成员、投顾、合规等多角色模拟，让客户经理练习拜访。\n2. **推介层**：输出三档产品组合、风险边界、拜访提纲、异议处理和会后跟进动作。\n3. **管理层**：形成可回溯报告，展示成交概率、二次转化、AUM机会、合规留痕和客户满意度。\n\n### 为什么银行客户会觉得有价值\n\n- 它把复杂销售过程从“凭经验”变成“可模拟、可复盘、可复制”。\n- 它让销冠经验变成组织流程，而不是停留在个人能力里。\n- 它可以在不接触真实客户隐私的情况下，先用虚拟客户群测试话术、产品组合和风险边界。\n- 它能让银行管理层看到：AI不是替代客户经理，而是让客户经理在见客户前完成一次高质量预演。",
    ),
]


AGENT_DIRECT_ANSWERS = [
    (1, "高净值客户A", "核心客户", "我愿意参与AI主题，但前提是不能把它包装成稳赚机会。客户经理要先告诉我哪些钱不能动、组合最大回撤大概在哪里、市场不好时谁来提醒我复盘。如果只是说AI很热，我会觉得是在卖产品；如果先把家庭资产安全垫、企业现金流和可投资资金分开，我会把这个方案带回家庭会议继续讨论。"),
    (8, "配偶共同决策人", "家庭安全垫", "我最担心的是企业主本人被主题热度带动，忽略家庭生活、教育金和医疗备用金。客户经理如果能先画出家庭安全垫，再解释科技仓位只是小比例参与，我会更容易接受。家庭会议不是形式，它决定这笔钱是不是全家都能睡得着。"),
    (10, "企业财务负责人", "资金分层", "企业经营资金和家庭可投资资产必须分开。企业周转资金不能被锁进长期主题产品，也不能因为客户本人看好AI就改变资金属性。我希望银行同时给企业现金管理、家庭资产配置和季度复盘方案，这样才像长期服务，不像一次销售。"),
    (2, "私行投资顾问", "组合设计", "均衡参与档的价值在于把客户兴趣和风险边界同时放进去。现金20%、固收40%是底盘，科技权益22%和AI观察仓8%表达主题机会，黄金/多资产10%做分散。好的组合不是最激进的组合，而是客户能坚持并愿意复盘的组合。"),
    (5, "风控合规经理", "适当性与话术", "所有确定性收益暗示都要禁止，不能把情景推演包装成收益预测。客户经理必须先完成风险测评和产品匹配，再进入组合建议。风险揭示、产品说明、客户确认、会议纪要、回撤提醒线和季度复盘记录都要留痕。"),
    (29, "销售管理看板", "管理层指标", "管理层最应该看的不是单次成交，而是首轮成交概率、二次转化概率、AUM新增、客户满意度和合规留痕完整度。系统的价值是把销冠经验拆成流程节点，让普通客户经理也知道什么时候问家庭目标、什么时候停下来做合规确认。"),
    (6, "AI行业研究员", "产业变量", "AI主题不能只讲概念，要拆成算力资本开支、国产芯片替代、云厂商盈利弹性、数据中心电力约束四类变量。客户听得懂变量，才会相信仓位控制不是随意拍脑袋。"),
    (7, "客户家族办公室代表", "传承与治理", "客户家族真正关心的是财富长期治理：这笔钱是否影响传承计划、是否影响家族企业现金流、是否需要信托或保险金信托承接。产品组合只是入口，家庭治理才是高净值客户愿意长期合作的理由。"),
    (9, "二代继承人", "成长诉求", "我对AI长期机会更感兴趣，但也希望看到清楚的学习和复盘机制。如果父母只听到风险，可能会太保守；如果我只听到机会，可能会太激进。系统应该让家庭成员在同一个事实面板上讨论。"),
    (11, "分行财富主管", "团队复制", "如果这套流程只服务一个客户，它就是案例；如果能把客户画像、组合建议、合规话术和会后跟进标准化，它就是分行训练工具。客户经理需要的不是更多产品，而是一套可复制的拜访节奏。"),
    (12, "总行产品准入经理", "产品白名单", "AI主题产品必须经过准入和风险等级匹配，不能因为客户资产规模大就放松边界。白名单、风险等级、销售范围、信息披露材料要和客户画像联动，否则产品越复杂，后续争议越难解释。"),
    (13, "运营留痕专员", "过程证据", "现场演示里最容易被忽略的是留痕。客户问过什么、客户经理解释过什么、客户是否确认理解风险，这些都应该自动沉淀。留痕不是后台负担，而是后续复盘、质检和客诉处理的证据资产。"),
    (14, "客户服务经理", "会后服务", "客户真正感受到服务价值，往往发生在会后。T+1摘要、T+30回访、季度复盘、市场波动提醒，这些动作决定客户会不会把银行视为长期顾问，而不是一次产品销售人员。"),
    (15, "量化对冲产品经理", "低相关资产", "如果客户担心科技主题波动，可以引入低相关策略解释回撤控制。但量化对冲不能被说成保本工具，要说明相关性、极端行情和策略失效场景。它适合作为组合稳定器，不适合作为收益承诺。"),
    (16, "黄金多资产策略师", "分散配置", "黄金和多资产不是为了追热点，而是为了在汇率波动、风险偏好下降、权益主题回撤时提供分散。客户如果理解这10%的作用，就更容易接受科技权益和AI观察仓存在波动。"),
    (17, "半导体研究员", "国产替代", "半导体设备和先进封装是AI产业链的重要变量，但它的波动也更高。客户经理应该把它放在科技主题权益的一部分，而不是单独放大成核心卖点。"),
    (18, "云计算研究员", "云软件机会", "云厂商盈利弹性和企业软件复苏更适合讲长期逻辑。客户不一定懂模型训练，但能理解企业数字化、降本增效和云服务需求，这部分可以帮助AI主题从概念回到现金流。"),
    (19, "数据中心研究员", "基础设施约束", "数据中心、电力和REITs能让AI投资逻辑更具体。客户经理可以用基础设施解释为什么AI不是单一股票故事，而是算力、电力、网络和运营效率共同决定的产业链。"),
    (20, "利率策略师", "固收底仓", "利率下行环境会提高固收类产品吸引力，但也带来久期风险。固收增强是组合底仓，不能为了追求票息忽视信用利差和流动性。"),
    (21, "汇率策略师", "海外资产顾虑", "部分高净值客户会问海外资产和人民币汇率。客户经理不必直接引导跨境配置，而是可以用黄金、多资产和境内科技主题替代方案解释风险分散。"),
    (22, "同圈层企业主B", "转介绍信号", "我不会因为朋友买了就跟着买，但如果朋友说银行帮他把家庭、企业、传承和科技机会讲清楚，我会愿意听一次。转介绍来自服务可信度，不来自产品名字。"),
    (23, "保守型客户C", "异议处理", "我听到AI理财会先想到追热点和高位接盘。客户经理如果能给仓位上限、分批建仓和退出条件，我会愿意了解；如果只讲未来空间，我会直接拒绝。"),
    (24, "进取型客户D", "风险约束", "我愿意提高AI仓位，但也需要系统提醒我不要把家庭资产都放进一个主题。进取需求可以存在，但必须被观察仓和回撤线约束。"),
    (25, "客户朋友推荐人", "口碑传播", "高净值客户愿意推荐的不是产品收益，而是银行是否把复杂问题讲得清楚、是否持续跟进、是否在市场波动时主动提醒。"),
    (26, "合规质检员", "质检口径", "质检最关注三件事：是否完成适当性，是否有收益暗示，是否把复杂产品风险讲完整。系统如果能自动标记高风险话术，会明显降低培训和复盘成本。"),
    (27, "家族信托顾问", "深度经营", "当客户开始讨论传承、资产隔离和家庭治理时，科技理财产品就不是终点，而是深度经营入口。客户经理要识别什么时候把话题转向家族信托和长期安排。"),
    (28, "保险金信托顾问", "保障承接", "如果客户家庭安全垫不足，不应该急着提高科技仓位，而要先补保障和传承结构。保险金信托可以承接一部分家庭安全垫和传承诉求。"),
    (0, "宁波银行大客户经理", "主导动作", "我的现场策略应该从问问题开始，而不是从讲产品开始。先确认客户家庭目标、企业资金边界、共同决策人和风险底线，再让投顾进入组合说明，这样客户才会觉得我们是在解决问题。"),
    (3, "科技主题基金经理", "主题解释", "AI主题基金要讲清楚波动来源、估值位置和行业周期。基金经理的表达必须服务于客户组合，而不是把主题讲得越兴奋越好。"),
    (4, "固收产品经理", "稳定器", "固收底仓的作用是让客户有耐心持有科技仓位。没有稳定器，AI主题再有吸引力也会在市场回撤时变成客诉压力。"),
]


def _agent_answer_appendix() -> str:
    lines = [
        "### Agent直接回答证据库",
        "",
        "以下内容来自本次30个虚拟Agent的双世界问答与行为回放。每个编号都可以作为 Report Agent 回复时的引用证据。"
    ]
    for agent_id, name, theme, answer in AGENT_DIRECT_ANSWERS:
        lines.extend([
            "",
            f"#### A{agent_id:02d} {name}｜{theme}",
            f"> {answer}",
            f"**可引用结论**：A{agent_id:02d} 的反馈说明，客户经理需要把产品销售动作改写成可解释、可复盘、可留痕的顾问流程。"
        ])
    return "\n".join(lines)


def _section_expansions() -> Dict[int, str]:
    return {
        1: """### 结论背后的证据索引

- 家庭资产安全垫来自 A01 高净值客户A、A08 配偶共同决策人、A10 企业财务负责人的共同反馈：他们不是反对科技主题，而是要求先确认哪些资金不能动、哪些资金可以长期配置、哪些资金需要随时可赎回。
- 科技仓位可解释来自 A02 私行投资顾问、A06 AI行业研究员、A17 半导体研究员、A18 云计算研究员和 A19 数据中心研究员的交叉判断：AI产品必须从概念拆成产业链变量，再回到仓位上限和分批建仓。
- 回撤预警和复盘机制来自 A05 风控合规经理、A13 运营留痕专员、A14 客户服务经理的过程要求：客户真正购买的是持续服务，而不是一次性推荐。
- 管理层价值来自 A11 分行财富主管和 A29 销售管理看板：系统要把销冠经验变成团队可复制流程，把成交概率、AUM机会和合规留痕放在同一张管理面板中。

因此，本报告的执行结论不是“AI理财值得卖”，而是“宁波银行可以把科技与AI主题产品推介变成一套可模拟、可复盘、可复制、可审计的高净值客户经营系统”。""",
        2: _agent_answer_appendix(),
        3: """### 商业机会扩充：从单点成交到组织能力

第一类机会是客户侧的“资产诊断产品化”。高净值客户并不缺产品信息，他们缺的是一套能把家庭目标、企业现金流、风险偏好、传承诉求和主题机会放在同一张图上的解释框架。系统可以在首次拜访后自动生成四张卡片：家庭安全垫、企业资金边界、科技主题参与度、复盘与留痕计划。客户看到的是顾问服务，管理层看到的是标准化过程。

第二类机会是客户经理侧的“训战流程产品化”。过去销冠经验靠口传心授，很难复制。通过虚拟Agent，系统可以把一次复杂拜访拆成可训练节点：开场如何问家庭目标，何时识别共同决策人，何时停止产品讲解进入适当性确认，何时引入投顾，何时给三档组合，何时安排T+1摘要和T+30回访。每个节点都能被复盘、评分和优化。

第三类机会是管理层侧的“过程指标看板”。银行管理层通常能看到最终成交和AUM，但很难看到成交之前发生了什么。Foresight 可以把模拟过程中的异议、家庭成员态度、合规风险点、产品理解程度、复盘响应速度都转成过程指标。这样管理层不只是问“卖了多少”，而是能问“为什么这个客户愿意买，为什么那个客户还没买，下一步该由谁介入”。

第四类机会是合规侧的“主动风险防火墙”。复杂产品推介最大的风险不是客户不买，而是客户在不理解的情况下买。系统可以在话术层自动标记收益暗示、风险揭示不足、集中度过高、产品白名单不匹配等问题，把合规从事后抽检前移到销售预演阶段。""",
        4: """### 销售路径扩充：三次接触模型

第一次接触不以成交为目标，而以建立问题框架为目标。客户经理需要确认家庭资产安全垫、企业现金流、共同决策人、风险偏好和过往投资体验。系统根据这些信息生成客户画像，并提示哪些问题必须先问，哪些产品暂时不能进入。

第二次接触进入组合解释。默认呈现三档组合：稳健观察档、均衡参与档、进取主题档。现场主推均衡参与档，因为它既保留现金和固收底盘，又能让客户参与科技与AI主题。客户经理需要解释为什么科技权益和AI观察仓合计不超过35%，为什么单产品集中度不超过15%，为什么黄金/多资产不是装饰项，而是分散风险的工具。

第三次接触进入家庭会议和复盘承诺。配偶、二代、企业财务负责人往往会提出不同问题，系统应帮助客户经理准备不同版本的解释材料：给配偶看安全垫和回撤线，给二代看AI产业链变量，给企业财务负责人看资金分层，给客户本人看组合与服务节奏。成交后还要进入T+1摘要、T+30回访和季度复盘。""",
        5: """### 合规与证据扩充：哪些内容必须被系统捕捉

一是适当性证据。系统需要记录客户风险等级、产品风险等级、客户确认时间、客户是否理解产品说明书、是否存在共同决策人参与。没有这些证据，复杂产品推介就只是口头过程。

二是话术证据。系统要识别并阻断“确定会涨”“AI必然爆发”“这个产品很安全”等高风险表达。正确说法应该是“在某种情景下组合可能如何反应”“这个仓位用于表达主题机会但需要承受波动”“这不是收益承诺，需要结合正式产品说明和风险揭示”。

三是后续服务证据。客户最怕的不是买之前没人解释，而是买之后没人提醒。回撤预警、市场变量更新、季度复盘、客户异议处理、调仓建议都应被留存。对银行来说，这些记录既是服务证明，也是团队训练材料。

四是数据边界。现场演示和系统采购阶段都应使用虚拟客户、脱敏样例和公开信息，不输入真实客户隐私、账户、持仓、授信或交易数据。""",
        6: """### 落地路线扩充：从Demo到采购决策

第一阶段建议做“客户经理训战版”。选择3到5个典型客户画像：保守型企业主、科技兴趣型二代、家庭共同决策复杂客户、企业现金流敏感客户、传承诉求客户。每个画像都可以生成虚拟Agent群，让客户经理在见真实客户前完成预演。

第二阶段做“产品推介协同版”。把投顾中台、产品准入、合规质检、运营留痕都纳入流程。客户经理输入客户画像后，系统生成三档组合、拜访提纲、风险揭示重点、异议处理脚本和会后跟进任务。

第三阶段做“管理层复盘版”。分行财富主管可以看到每个客户经理的预演质量、客户异议分布、产品理解难点、合规风险点和下一步行动建议。系统价值从一个好看的AI Demo，变成银行内部可持续运营的客户经营基础设施。

现场采购沟通时，建议把价值表达压成一句话：Foresight 不是替银行替代客户经理，而是让客户经理在真实拜访前，先和30个虚拟客户、家属、投顾、合规、管理层角色完成一次高密度预演。银行买到的不是一份报告，而是复杂财富销售流程的预演、训练、复盘和审计能力。"""
    }


def _expanded_report_sections() -> List[tuple[str, str]]:
    expanded = []
    additions = _section_expansions()
    for idx, (title, content) in enumerate(REPORT_SECTIONS, start=1):
        extra = additions.get(idx, "")
        expanded.append((title, f"{content}\n\n{extra}" if extra else content))
    return expanded


def _chat_citations() -> List[Dict[str, Any]]:
    return [
        {"id": "S01", "anchor_id": "S01", "label": "S01", "title": "执行结论", "section_index": 1},
        {"id": "S02", "anchor_id": "S02", "label": "S02", "title": "Agent问答暴露的问题", "section_index": 2},
        {"id": "S03", "anchor_id": "S03", "label": "S03", "title": "商业机会", "section_index": 3},
        {"id": "A01", "anchor_id": "A01", "label": "A01", "title": "高净值客户A｜核心客户", "section_index": 2, "agent_id": 1},
        {"id": "A08", "anchor_id": "A08", "label": "A08", "title": "配偶共同决策人｜家庭安全垫", "section_index": 2, "agent_id": 8},
        {"id": "A10", "anchor_id": "A10", "label": "A10", "title": "企业财务负责人｜资金分层", "section_index": 2, "agent_id": 10},
        {"id": "A05", "anchor_id": "A05", "label": "A05", "title": "风控合规经理｜适当性与话术", "section_index": 2, "agent_id": 5},
        {"id": "A29", "anchor_id": "A29", "label": "A29", "title": "销售管理看板｜管理层指标", "section_index": 2, "agent_id": 29},
    ]


def _ensure_chat_citations(response: str) -> str:
    if "[[" in response:
        return response
    return (
        f"{response.rstrip()}\n\n"
        "证据来源：[[S01]] [[S02]] [[A01]] [[A08]] [[A10]] [[A05]] [[A29]]"
    )


def _report_outline() -> Dict[str, Any]:
    return {
        "title": "宁波银行高净值客户AI理财组合推介分析报告",
        "summary": "围绕大客户经理服务高净值客户的现场推介场景，回溯客户画像、产品组合、销售转化和合规边界。",
        "sections": [{"title": title, "content": ""} for title, _ in REPORT_SECTIONS],
    }


def _report_markdown() -> str:
    sections = "\n\n".join(f"## {title}\n\n{content}" for title, content in _expanded_report_sections())
    return f"# {_report_outline()['title']}\n\n> {_report_outline()['summary']}\n\n{sections}\n"


def _agent_interview_result() -> str:
    return """**采访主题:** 宁波银行高净值客户科技与AI理财产品组合推介，会暴露哪些问题与商业机会？
**采访人数:** 6 / 30 位模拟Agent

### 采访对象选择理由
1. **高净值客户A（index=1）**：核心购买者，能暴露真实成交阻力。
2. **配偶共同决策人（index=8）**：家庭共同决策人，影响高净值客户最终确认。
3. **企业财务负责人（index=10）**：代表企业现金流约束，避免把经营资金误纳入长期配置。
4. **私行投资顾问（index=2）**：负责把客户需求转成产品组合。
5. **风控合规经理（index=5）**：识别销售口径和留痕风险。
6. **销售管理看板（index=29）**：聚合转化率、AUM机会和团队复制价值。

---

### 采访实录

#### 采访 #1: 高净值客户A
**高净值客户A** (HighNetWorthClient)
_简介: 制造业企业主，关注长期稳健收益与科技主题成长性。_

**Q:**
1. 你愿意接受科技与AI主题产品组合吗？
2. 什么情况会让你暂缓成交？

**A:**
【Twitter平台回答】
我愿意参与AI主题，但不能变成单一押注。现金流、安全垫和回撤提示说清楚，我才会把这件事带回家庭会议。

【Reddit平台回答】
如果客户经理只讲AI很热，我会担心高位接盘；如果能看到现金20%、固收40%和季度复盘，我愿意先用均衡档试运行。

**关键引言:**
> "我买的不是AI概念，我买的是有人能持续帮我解释风险和调整组合。"

---

#### 采访 #2: 配偶共同决策人
**配偶共同决策人** (FamilyDecisionMaker)
_简介: 关注家庭安全垫、教育金安排和回撤体验。_

**Q:**
1. 你最担心这套方案的什么？
2. 哪个动作会提高你的信任？

**A:**
【Twitter平台回答】
我最担心企业主本人被主题热度带动，忽略家庭资产安全垫。先说明哪些钱不能动、最大可能波动在哪里，我才会参与讨论。

【Reddit平台回答】
如果客户经理能把教育金、医疗备用金和企业周转资金分开，我对科技仓位的接受度会明显提高。

**关键引言:**
> "家庭会议不是形式，它决定这笔钱是不是全家都能睡得着。"

---

#### 采访 #3: 企业财务负责人
**企业财务负责人** (CorporateCFO)
_简介: 关注企业现金流、闲置资金和资金使用窗口。_

**Q:**
1. 企业资金和家庭资产应该如何区分？
2. 对银行有什么服务期待？

**A:**
【Twitter平台回答】
企业经营资金不能被锁进长期主题产品。客户经理需要先做资金分层，再谈哪些资金可以进入科技权益。

【Reddit平台回答】
如果银行能同时给出企业现金管理、家庭资产配置和季度复盘，我会认为这不是单次销售，而是长期服务方案。

**关键引言:**
> "最危险的不是产品波动，而是把企业周转钱误当成可投资闲钱。"

---

#### 采访 #4: 私行投资顾问
**私行投资顾问** (PrivateBankingAdvisor)
_简介: 负责组合建议、风险匹配和产品说明。_

**Q:**
1. 为什么推荐均衡参与档？
2. AI主题应该怎么讲才不冒进？

**A:**
【Twitter平台回答】
均衡档能把客户兴趣和风险边界同时放进去。科技权益22%加AI观察仓8%，让客户参与主题，但不让主题决定整个组合。

【Reddit平台回答】
讲AI不能只讲应用爆发，要拆成算力、半导体、云软件和数据中心约束，再配合估值分位和分批建仓。

**关键引言:**
> "好的组合不是最激进的组合，而是客户能坚持并愿意复盘的组合。"

---

#### 采访 #5: 风控合规经理
**风控合规经理** (RiskCompliance)
_简介: 检查适当性、集中度、流动性和宣传口径。_

**Q:**
1. 哪些话术必须禁止？
2. 哪些材料必须留痕？

**A:**
【Twitter平台回答】
禁止确定性收益暗示，禁止把情景推演包装成收益预测。所有表达都必须回到适当性、风险揭示和产品说明书。

【Reddit平台回答】
风险测评、产品白名单、客户确认、会议纪要、回撤提醒线、季度复盘记录都必须留存，否则后续客诉无法解释。

**关键引言:**
> "合规不是拖慢销售，而是让销售结果经得起复盘。"

---

#### 采访 #6: 销售管理看板
**销售管理看板** (SalesAnalytics)
_简介: 聚合首轮成交、二次转化、AUM和服务满意度指标。_

**Q:**
1. 这次模拟最值得管理层看的指标是什么？
2. 这个系统对团队复制有什么价值？

**A:**
【Twitter平台回答】
最关键不是单次成交，而是首轮成交60%-70%、家庭诊断后二次转化约75%、AUM新增15%-20%这三组指标能否被持续复盘。

【Reddit平台回答】
系统能把销冠经验拆成流程节点，让普通客户经理也知道什么时候问家庭目标、什么时候停下来做合规确认、什么时候进入产品建议。

**关键引言:**
> "管理层需要看的不是一个漂亮答案，而是一条可复制的成交路径。"

### 采访摘要与核心观点
- 客户的主要阻力来自家庭安全垫、流动性、回撤体验和主题集中度，而不是对AI完全没有兴趣。
- 商业机会在于把高净值客户推介升级成“资产诊断 + 产品组合 + 季度复盘 + 合规留痕”的系统化服务。
- 对银行来说，系统价值不是替代客户经理，而是把客户经理见客户前的预演、推介、复盘和团队复制标准化。"""


def _insight_result() -> str:
    return """分析问题: 宁波银行高净值客户AI理财组合推介的关键机会与风险是什么？
预测场景: 以大客户经理为核心，为高净值客户推介科技、AI相关理财产品组合，并预测产品组成与销售效果。
相关预测事实: 12
涉及实体: 18
关系链: 16

### 分析的子问题
1. 客户为什么会接受或拒绝AI主题产品？
2. 产品组合如何兼顾科技成长和家庭安全垫？
3. 客户经理如何把销售动作变成可复盘流程？
4. 合规边界如何嵌入推介过程而不是事后补救？

### 【关键事实】
1. 高净值客户A愿意参与AI主题，但明确要求不做单一押注。
2. 配偶共同决策人要求先确认家庭资产安全垫和教育金安排。
3. 企业财务负责人要求企业周转资金与家庭可投资资金分层。
4. 风控合规经理要求所有AI表达改成情景推演，不承诺收益。
5. 私行投资顾问把主推方案调整为现金20%、固收增强40%、科技权益22%、AI观察仓8%、黄金/多资产10%。
6. 销售管理看板预测首轮成交60%-70%，家庭诊断后二次转化约75%。

### 【核心实体】
- **宁波银行大客户经理** (KeyAccountManager)
  摘要: 负责客户沟通、方案组织和服务切入。
  相关事实: 5
- **高净值客户A** (HighNetWorthClient)
  摘要: 制造业企业主，关注稳健收益、流动性和科技主题成长敞口。
  相关事实: 4
- **私行投资顾问** (PrivateBankingAdvisor)
  摘要: 负责组合建议、风险匹配和产品说明。
  相关事实: 4
- **风控合规经理** (RiskCompliance)
  摘要: 检查适当性、集中度、流动性和宣传口径。
  相关事实: 4
- **销售管理看板** (SalesAnalytics)
  摘要: 聚合成交概率、二次转化、AUM和满意度指标。
  相关事实: 3

### 【关系链】
- 宁波银行大客户经理 --[SERVES]--> 高净值客户A
- 宁波银行大客户经理 --[COLLABORATES_WITH]--> 私行投资顾问
- 私行投资顾问 --[DESIGNS]--> 科技AI产品组合
- 风控合规经理 --[GOVERNS]--> 适当性风险测评
- 科技AI产品组合 --[CONTAINS]--> 现金管理产品
- 科技AI产品组合 --[CONTAINS]--> 固收增强产品
- 科技AI产品组合 --[CONTAINS]--> 科技主题基金
- 科技AI产品组合 --[CONTAINS]--> AI主题理财产品
- 销售管理看板 --[PREDICTS]--> 首轮成交概率
- 销售管理看板 --[PREDICTS]--> 二次转化概率"""


def get_cached_report(report_id: str) -> Optional[Dict[str, Any]]:
    if report_id == COURSE_REPORT_ID:
        return {
            "report_id": COURSE_REPORT_ID,
            "simulation_id": COURSE_SIM_ID,
            "graph_id": COURSE_GRAPH_ID,
            "simulation_requirement": COURSE_REQUIREMENT,
            "status": "completed",
            "outline": _course_report_outline(),
            "markdown_content": _course_report_markdown(),
            "created_at": COURSE_CREATED_AT,
            "completed_at": _course_time(8),
            "error": None,
        }
    if report_id != NB_REPORT_ID:
        return None

    return {
        "report_id": NB_REPORT_ID,
        "simulation_id": NB_HNW_AI_CASE_ID,
        "graph_id": NB_GRAPH_ID,
        "simulation_requirement": NB_REQUIREMENT,
        "status": "completed",
        "outline": _report_outline(),
        "markdown_content": _report_markdown(),
        "created_at": _case_time(62),
        "completed_at": _case_time(70),
        "error": None,
    }


def get_cached_report_by_simulation(simulation_id: str) -> Optional[Dict[str, Any]]:
    if simulation_id == COURSE_SIM_ID:
        return get_cached_report(COURSE_REPORT_ID)
    if simulation_id != NB_HNW_AI_CASE_ID:
        return None
    return get_cached_report(NB_REPORT_ID)


def _course_time(minutes: int) -> str:
    return (datetime.fromisoformat(COURSE_CREATED_AT) + timedelta(minutes=minutes)).isoformat()


COURSE_REPORT_SECTIONS = [
    (
        "S01 执行结论：招生不是卖课，是把不确定感降到可付款",
        """本轮双世界模拟的核心判断是：第一期50人线下课的成交，不取决于课程名称是否足够宏大，也不取决于优惠力度是否足够夸张，而取决于学员在付款前能否确认三件事。第一，自己交钱后能拿到高密度、可落地、能复用的能力，而不是听一场情绪价值很强但回去无法执行的演讲。第二，现场组织、分组反馈、案例演练、课后作业和复盘机制足够明确，不会出现“现场很热闹，回家又归零”的体验。第三，早鸟、同行、退款、资料回看、社群服务等规则清晰，让学员感觉价格公平、权益确定、风险可控。

从模拟行为看，付款意愿最高的人并不是完全陌生的观望者，而是已经被AI工具刺激过、在自媒体/销售/产品/个人IP/企业运营中遇到真实问题的人。他们并不需要再被说服“AI很重要”，他们需要被说服的是：这门课能不能帮我把一个卡住的问题推进到可以执行。A03林岚反复提到，她愿意为“现场带走选题库、提示词、自动化流程和复盘模板”付款，而不是为趋势判断付款。A07陈亦桥则代表价格敏感但高需求的人，他对课程的质疑不是不认可AI，而是担心听完之后不会用。两类人共同指向一个结论：招生页和销售话术必须把抽象价值转成可交付对象。

因此，最稳的转化路径不是直接推销“名额有限”，而是先做诊断，再承诺交付，最后推动付款。诊断阶段问清楚学员当前业务、AI使用水平、最想解决的问题、过去学习失败的原因；交付阶段明确课前问卷、现场案例、实操模板、分组反馈、课后作业、资料回看、复盘节点；付款阶段再匹配超级早鸟、普通早鸟、两人同行或三人同行。这个顺序会显著降低强销售感，也让优惠机制从“便宜”变成“锁定交付权益”。

对现场演示而言，Foresight的价值也在这里：它不是简单帮团队生成一段招生文案，而是在正式投放和正式销售前，先用30个虚拟Agent模拟不同学员、运营人员、拼团组织者、退款敏感用户、同行观察者和交付负责人会怎样反应。系统提前暴露犹豫点、误解点、付款触发点和舆情风险，再把这些反应整理成可执行的销售SOP和交付SOP。客户看到的不是一份漂亮报告，而是一套可以在真实招生前降低不确定性的经营系统。"""
    ),
    (
        "S02 Agent问答暴露的问题：学员真正担心的是交付密度和机会成本",
        """30个Agent的问答显示，学员真正担心的不是“AI有没有前景”，而是“我付出的时间、钱和注意力能不能换回确定的进步”。这种担心可以拆成四类。第一类是交付密度：现场到底是讲概念，还是带着我把一个真实问题做出来。第二类是机会成本：我是否需要请假、坐车、住酒店、放弃周末，如果最后只是听了一堆原则，就很难接受。第三类是后续反馈：我回去做作业遇到问题，有没有人看、有没有复盘、有没有同伴压力。第四类是规则公平：同样买课的人，超级早鸟、早鸟、同行、临时报名之间权益是否清楚，是否会让早付款的人吃亏。

#### A00 方见舟｜课程发起人 / 同舟会线下课主理人
**Q:** 你最担心第一期招生哪一步失控？
**A:** 我不担心大家没有兴趣，我担心大家都在等最后一刻确认。等的人越多，销售越容易被动。所以要把课前诊断、席位机制和交付清单提前说清楚，让学员知道现在确认不是为了便宜，而是为了提前进入准备流程。

#### A03 林岚｜高意愿学员 / 自媒体创业者
**Q:** 什么会促使你立刻付款？
**A:** 如果我知道现场能带走一套选题方法、提示词、自动化流程、内容复盘模板，并且这些东西能直接用于我接下来一个月的账号更新，我愿意买早鸟。单纯说趋势、认知、未来机会，我会觉得听过很多次，不会马上动。

#### A07 陈亦桥｜价格敏感学员 / 职场转型产品经理
**Q:** 你为什么犹豫？
**A:** 我怕课程太贵但听完不会用。我的问题不是不知道AI重要，而是不知道怎么把AI放进自己的工作流。最好有课前问卷和课后作业反馈，让我知道自己不是只来听热闹。

#### A11 孟知秋｜同行拼团组织者 / 知识付费社群运营者
**Q:** 同行优惠的最大风险是什么？
**A:** 拼团能带来转介绍，但规则必须简单。如果三人同行核销复杂，销售会被大量沟通消耗。最好把同行权益写成一页图，不要让学员自己猜谁付款、谁登记、谁进群、谁拿资料。

#### A18 许若安｜退款敏感学员 / 企业培训采购负责人
**Q:** 什么情况会触发退款情绪？
**A:** 如果宣传说得很满，但现场案例和我的行业不相关，我会觉得预期落差大。退款规则要提前写明，哪些情况可以退，哪些是课程开始后不能退，不能等学员不满意时才解释。

#### A24 唐逸舟｜交付运营负责人 / 课程项目经理
**Q:** 课后最重要的动作是什么？
**A:** T+1交付资料，T+7收作业，T+14做一次复盘，T+30筛选转介绍线索。否则线下课热度很快散掉，学员会觉得当场很燃，回去没有后劲。

这些回答共同说明：销售页、私聊话术和现场控场都要围绕“交付确定性”组织。能成交的人要被快速推到付款动作；犹豫的人要被引导到诊断和样例；风险敏感的人要提前看到规则边界；拼团传播者要获得简单、可转发、可解释的规则。只要把这些问题在付款前处理，课程的转化就会更像一个有节奏的招生经营过程，而不是靠讲师个人影响力临场推动。

进一步看，Agent之间的差异也提示团队不能用同一套话术覆盖所有人。A03林岚要的是内容生产效率，A05周予白要的是销售团队工作流，A09陆佳宁要的是企业培训可复制性，A21沈知微要的是金融客户经营案例。对这些人都说“AI时代必须学习”没有意义，真正有效的是把课程价值翻译成他们各自的业务场景。也就是说，销售系统要先识别角色，再匹配证据：自媒体用户看选题和内容流程；销售负责人看客户研究和拜访提纲；企业培训负责人看组织复制；金融客户经理看客户分析和产品推介。"""
    ),
    (
        "S03 收款结构预测：早鸟机制会放大行动，但必须避免规则混乱",
        """收款结构的关键不是让价格看起来更低，而是让不同决策状态的人都有一个顺手的付款理由。模拟中，超级早鸟适合承担首批信任背书，主要面向熟人、老学员、已明确需求的人；普通早鸟适合承接有意愿但需要再确认的人；两人同行和三人同行适合激活熟人传播，但不能让拼团变成销售团队的主要工作量。

本轮预测中，50人目标的较稳结构是：超级早鸟8-12人，普通早鸟18-24人，两人同行贡献8-12人，三人同行贡献4-6人，临近开课原价或少量特殊确认名额补足余量。这个结构的好处是既能制造第一批已付款样本，又不会让三人同行占比过高，导致订单确认、资料分发、入群登记和发票沟通过于复杂。A11孟知秋的反馈尤其重要：如果同行优惠规则需要反复解释，传播者会从帮你招生的人变成制造沟通成本的人。

优惠权益建议从“少多少钱”改写成“提前获得什么”。超级早鸟可以绑定课前诊断优先权、席位确认、分组优先、案例征集优先；普通早鸟强调价格窗口和课前准备材料；两人同行强调共同作业和现场同组；三人同行强调团队问题可以被纳入案例池，但不额外承诺讲师单独服务。这样做可以避免用户把优惠理解成纯折扣，也能让早付款的人觉得自己获得了确定性，而不是承担了先付款风险。

销售节奏上，建议分四个窗口。第一窗口是老用户内测确认，目标是拿到第一批付款和真实问题；第二窗口是公开早鸟，目标是把课程价值讲清楚；第三窗口是同行传播，目标是让已付款学员带来同伴；第四窗口是临近开课提醒，目标是处理犹豫但高意愿的人。每个窗口都要有对应话术和素材，不要把所有信息堆在一个招生海报里。"""
    ),
    (
        "S04 舆情与退款风险：最大的负面不是退款本身，而是预期不一致",
        """模拟中的负面舆情并不集中在“价格贵”本身，而集中在预期不一致。学员可以接受高价格，但不能接受高价格背后没有清晰交付；可以接受课程密度高，但不能接受没有资料回看和复盘；可以接受现场案例不可能覆盖所有行业，但不能接受自己在报名时完全不知道案例范围；可以接受退款边界严格，但不能接受付款后才被告知规则。

A18许若安的回答代表企业采购和理性用户：只要宣传说得过满，而现场案例与自己行业差距过大，就会触发预期落差。A24唐逸舟则从交付侧提醒，线下课结束后如果没有T+1资料、T+7作业、T+14复盘、T+30转介绍筛选，课程热度会迅速衰减。这两个视角放在一起看，退款风险其实不是一个财务动作，而是一个信任信号。用户提出退款时，往往已经经历了价值感下降、预期落差、沟通无回应、同伴讨论放大这几个阶段。

因此，建议把退款和交付规则前置到销售材料里，而不是藏在付款后须知里。规则可以分为四层。第一层是报名确认前：说明适合人群、不适合人群、课程强度和前置准备。第二层是付款后到开课前：提供课前问卷、资料预习、问题征集，如果学员发现明显不匹配，可以在规定时间内处理。第三层是开课当天：明确签到、资料、录屏或回看、作业提交方式。第四层是课后：明确反馈窗口、复盘节点和社群边界。

舆情处理上，不要让运营人员临场自由发挥。应提前准备三类回应模板：价值解释模板，用于解释课程交付物；规则解释模板，用于解释退款、名额、同行权益；情绪安抚模板，用于面对“我听不懂”“跟不上”“不适合我”的反馈。系统演示时，可以把这些模板展示成Foresight从模拟中自动提炼出的风险预案，让客户看到系统不仅预测销售，也预测交付争议。"""
    ),
    (
        "S05 商业机会：从一次线下课升级为可复制的招生经营系统",
        """这次模拟最值得展示的商业机会，不是“第一期能不能卖满50人”，而是从一次线下课中抽象出一套可复制的招生经营系统。这个系统包括八个模块：用户画像分层、需求诊断问卷、优惠与权益设计、私聊销售SOP、课前准备机制、现场交付机制、课后复盘机制、退款与转介绍预警。只要这些模块跑通，后续无论是第二期课程、企业内训、私董会工作坊，还是银行/保险/咨询行业的高客经营场景，都可以复用。

从商业角度看，Foresight的产品价值可以被包装成“经营预演”。传统团队常常先做海报、先投放、先销售，然后在真实用户反馈中被动调整。Foresight的做法是先把用户、销售、运营、交付、风险和舆情都变成Agent，让它们在一个模拟世界里提前互动。系统不是替代真实市场，而是在真实市场前给团队一次低成本的压力测试。它可以告诉团队：哪些话术会触发付款，哪些承诺会放大退款，哪些优惠会制造混乱，哪些交付动作能带来复购。

对银行客户或企业客户演示时，可以把这个能力迁移到他们的业务语境。银行推理财产品时，客户也会关心收益、风险、流动性、家庭共同决策和售后服务；企业卖高客服务时，客户也会关心价格、交付、案例、同伴和后续跟进。也就是说，这个线下课案例虽然是教育产品，但它展示的是一套普遍的“高客决策模拟能力”。这正是系统后续商业化的重点：不是卖一个demo，而是卖一种在复杂客户决策前进行多Agent、多变量、多时间轮次推演的能力。

本案例还暴露出一个增量机会：报告页可以成为销售资产。右侧Report Agent能够基于总结和Agent问答回答问题，并用角标引用具体证据；左侧报告可以跳转到对应章节和Agent原话。这种设计让客户看到“AI不是自己瞎想”，而是从模拟过程、访谈结果和结构化报告中提取结论。后续如果给企业客户交付，可以把每一次模拟沉淀为一个可追问、可回看、可复盘的互动报告，而不是只发一份PDF。

如果把这个能力再往商业化推进一层，可以形成三种产品形态。第一种是售前策略模拟：在课程、理财、企业服务、咨询项目正式销售前，先跑一轮不同客户角色的反应，产出销售话术、异议处理和风险提示。第二种是交付压力测试：在承诺客户之前，先模拟交付过程中的投诉、延期、信息误解、人员协作和复盘缺口。第三种是经营复盘资产：项目完成后，把真实反馈继续沉淀进报告，让下一轮销售和交付不再从零开始。这样，Foresight就不是一个临时演示工具，而是一套可以嵌入业务团队日常经营的智能预演层。

对客户来说，最直观的购买理由是“少踩坑”。很多团队不是没有方案，而是方案进入真实用户之后才发现话术不清、规则复杂、承诺过满、交付跟不上。Foresight提前把这些问题可视化，能帮团队在付出真实市场成本前先做修正。对于银行、保险、教育、咨询、企业服务等高信任行业，这个价值尤其明显，因为每一次高客成交都不只是一次付款，而是一次长期关系的开始。"""
    ),
    (
        "S06 推荐SOP：先诊断，再承诺交付，最后推动付款",
        """推荐采用三段式销售SOP：先诊断，再承诺交付，最后推动付款。第一段诊断不要超过5分钟，但必须问到关键问题：你现在最想用AI解决什么业务问题？过去用过哪些工具？目前卡在选题、提示词、流程、自动化、团队协作还是变现？你这次来线下课最希望带走什么？如果这些问题问不出来，销售就只能回到抽象价值，很容易让学员感觉被推销。

第二段交付要尽量具体。不要说“帮你掌握AI能力”，而要说“课前会收集你的业务问题，现场会拆解选题、提示词、工作流和案例，课后会交付资料包、作业反馈和复盘节点”。对于A03林岚这样的高意愿学员，要强调可直接用于内容生产的模板；对于A07陈亦桥这样的价格敏感学员，要强调从不会用到能执行的路径；对于A18许若安这样的理性采购型用户，要强调适合/不适合人群和退款边界；对于A11孟知秋这样的传播型用户，要给他一页能转发的同行规则。

第三段决策要避免强压。可以用四类句式。对已确认需求的人，说“你现在最适合超级早鸟，先锁课前诊断和分组权益”。对还在犹豫的人，说“你可以先把问题发来，我们判断是否适合，不适合就不要报”。对想拉朋友的人，说“两人同行更适合共同做作业，三人同行适合团队问题，但登记规则要一次确认”。对价格敏感的人，说“如果你只是想听趋势，不建议报；如果你要现场做出一套流程，早鸟会更合适”。

运营侧SOP也要同步。付款后自动发送课前问卷；开课前48小时确认问题和分组；现场签到时提示资料包和作业路径；课程结束T+1交付资料；T+7收作业；T+14复盘；T+30筛选转介绍和二期线索。这个SOP的价值在于把一次线下课变成连续经营，而不是当天成交结束就松散掉。

为了让SOP可检查，建议每一步都对应一个“完成证据”。诊断阶段的证据是用户问题卡片；交付承诺阶段的证据是资料清单和案例清单；付款阶段的证据是权益确认单；课前阶段的证据是问卷回收率和分组表；课中阶段的证据是现场产出文件；课后阶段的证据是作业提交、反馈记录和复盘纪要。没有证据的动作很容易变成口头承诺，有证据的动作才能被团队复盘、复制和改进。

如果给销售团队培训，可以把这套SOP拆成三句核心口播。第一句：“我们先判断你是否适合，不适合不用报。”这句话降低防备。第二句：“适合的话，你会带走这些具体产出。”这句话建立价值。第三句：“如果你确定要来，我帮你匹配最合适的报名方式。”这句话推动决策。三句话背后对应的是诊断、交付、付款，而不是情绪煽动。"""
    ),
    (
        "S07 双世界模拟口径：用Info Plaza看传播，用Topic Community看真实顾虑",
        """本案例采用双世界并行模拟。Info Plaza更像公开传播场，适合观察招生海报、讲师表达、老学员背书、优惠窗口、名额稀缺和公开舆论如何影响决策；Topic Community更像深层讨论场，适合观察学员在熟人、小群、私下问答中真正担心什么。两个世界同时运行，能避免只看公开点赞而忽略私下犹豫，也能避免只看负面担心而低估传播势能。

Info Plaza中的积极信号主要来自三类内容：第一，课程发起人明确交付边界后，早期信任用户更愿意转发；第二，已付款用户如果能说出自己要解决的问题，会带动同类人询问；第三，优惠窗口和席位机制对有明确需求的人有效。Topic Community中的风险信号更细：有人担心现场案例不贴近行业，有人担心作业无人反馈，有人担心同行拼团登记复杂，有人担心退款规则不透明。

因此，总结页不应该只给一个“转化率预测”，而要给出传播层、决策层、交付层和风险层的组合判断。传播层看哪些内容能被转发；决策层看哪些用户会付款；交付层看哪些承诺必须兑现；风险层看哪些问题会变成退款或负面口碑。这个结构能让客户理解，Foresight不是在做单点预测，而是在模拟一个业务系统跨时间的运行效果。"""
    ),
    (
        "S08 关键数据与预测：50人目标可达，但依赖前置诊断和课后复盘",
        """按本轮30个Agent、8轮互动、18条关键动作的模拟结果，50人目标具备可达性，但前提是不能把招生理解成一次性宣传。若只靠讲师影响力和朋友圈转发，系统预测会出现大量“感兴趣但不付款”的用户；若加入课前诊断、早鸟权益、同行规则和课后复盘，付款转化会明显改善。模拟给出的稳态判断是：第一批熟人和老用户可以形成8-12人的超级早鸟；公开早鸟可形成18-24人；同行机制贡献12人上下；剩余名额由临近开课的高意愿用户补足。

需要注意的是，数据是演示用模拟结果，不是对真实市场的确定性承诺。它的价值在于帮助团队看见变量之间的关系：课前诊断会提高高意愿用户的付款速度；交付清单会降低价格敏感用户的犹豫；退款规则会降低理性用户的风险感；同行规则会提高传播，但规则复杂会反噬销售效率；课后复盘会提高满意度和转介绍，但如果没有运营承接，线下课热度会在一周内明显衰减。

建议现场给客户展示时，不要把数字讲成绝对预测，而要讲成经营假设。比如：“如果我们只做公开招募，转化会偏低；如果把课前诊断和交付权益前置，超级早鸟和普通早鸟的占比会提高；如果同行机制规则清楚，转介绍贡献会增加；如果课后复盘不到位，退款和负面反馈会滞后出现。”这种表达更符合系统定位，也更容易让客户相信它能服务真实业务。"""
    ),
    (
        "S09 模块化落地建议：销售、交付、风控、复购四张表",
        """为了把模拟结论落地，建议把本报告转成四张运营表。第一张是销售线索表，字段包括姓名、职业、AI使用水平、核心问题、付款意愿、价格敏感度、适合权益、下一步动作。第二张是交付准备表，字段包括课前问卷、案例匹配、分组安排、资料包、现场任务、作业要求、反馈负责人。第三张是风险预警表，字段包括退款敏感点、预期落差、行业不匹配、规则误解、沟通记录、处理状态。第四张是复购转介绍表，字段包括作业完成度、满意度、可展示成果、是否愿意分享、是否适合二期或企业内训。

这四张表对应四类负责人。销售负责人关注线索推进和收款节奏；课程负责人关注现场内容和案例匹配；运营负责人关注资料、作业、群管理和反馈；商业负责人关注复购、转介绍、企业客户和长期产品化。Foresight的报告不应该停留在“发现问题”，而应该把问题变成负责人、动作、时间点和检查标准。

对于客户演示，这一节可以作为成交点：系统输出的不是一个漂亮结论，而是可以直接接进团队日常工作的行动清单。银行客户看这个案例时，也能映射到自己的客户经营：客户经理表、客户需求表、产品适配表、合规留痕表、复盘跟进表。本质上，Foresight可以把复杂决策推演结果翻译成团队能执行的运营表格。

这四张表还可以形成一个闭环看板。销售线索表负责回答“谁最可能付款”；交付准备表负责回答“我们承诺的东西准备好了没有”；风险预警表负责回答“谁可能不满意，为什么不满意”；复购转介绍表负责回答“课程结束后还有哪些商业机会”。如果只看收款金额，团队会高估招生成功；如果只看满意度，团队会低估销售效率；如果只看作业提交，团队又可能忽略转介绍。因此，看板必须同时看现金、交付、风险和复购。

建议为每张表设置最少三个指标。销售线索表看咨询人数、诊断完成率、付款转化率；交付准备表看问卷回收率、案例匹配率、资料交付准时率；风险预警表看退款咨询数、负面关键词、未响应问题数；复购转介绍表看作业完成率、可展示成果数、主动推荐人数。这样，模拟报告就能从“讲得很有道理”进入“团队明天就能执行”。这也是客户购买系统的理由：不是为了得到一个结论，而是为了获得一套能持续校准业务动作的仪表盘。"""
    ),
    (
        "S10 现场展示话术：强调可回溯、可追问、可复用",
        """现场展示这份报告时，建议用三句话收束。第一句：这不是一个视频回放，而是一个可交互的模拟结果页面，客户可以点进每个阶段、每个Agent和每个结论。第二句：Report Agent的回答不是自己想象，而是引用左侧报告章节和Agent问答，点击角标可以跳回证据位置。第三句：这套能力可以从线下课招生迁移到银行高净值客户经营、企业客户策略分析、理财产品推介、课程销售和复杂服务成交。

演示顺序建议是：先打开总结页，让客户看到完整结构；再提问“这个项目最大的成交阻力是什么”；接着点击回答里的A03、A07、A18等角标，让页面跳到具体Agent原话；然后追问“如果我要提高早鸟付款率，应该改哪里”；最后展示S06到S09，把结论落成SOP和四张表。这样客户会感受到系统不是在播放一个已经录好的文件，而是在一个真实页面里基于模拟结果进行追问、定位、解释和复盘。

现场追问可以准备四个问题。第一个问题问：“这个项目最大的成交阻力是什么？”系统应回答交付密度和机会成本，并引用A03、A07。第二个问题问：“怎样提高早鸟付款率？”系统应回答权益绑定和窗口节奏，并引用S03、A11。第三个问题问：“最容易出负面舆情的地方是什么？”系统应回答预期不一致和退款规则，并引用S04、A18、A24。第四个问题问：“这套方法对银行客户有什么价值？”系统应回答高客经营也需要提前模拟客户顾虑、共同决策、合规边界和售后服务，并引用S05、S09、S10。

这样的追问顺序能形成很强的现场效果：客户先看到完整报告，再看到AI能够回答问题，然后看到每个回答都能跳回证据。它会把“AI很聪明”的印象转成“系统真的记录了推演过程，并能复用推演结果”的信任。尤其是银行客户，他们不会只被炫技打动，更关心系统是否可解释、可追责、可复盘。角标、跳转、Agent原话和模块化报告正好回答这些顾虑。

最后要明确边界：所有数据和Agent回答都是模拟结果，用于经营预演和方案讨论，不代表真实市场承诺；系统价值在于提前暴露问题、比较方案、组织证据和形成行动，不替代真实投放、真实销售和真实合规审查。这个边界讲清楚后，反而会让客户更信任系统，因为它展示的是“降低不确定性”的能力，而不是“保证结果”的幻觉。"""
    ),
]


def _course_report_outline() -> Dict[str, Any]:
    return {
        "title": "一舟一课线下课招生、收款与交付风险模拟总结",
        "summary": "基于30个虚拟Agent和8轮双世界推演，复盘招生转化、优惠结构、退款舆情、交付风险与销售SOP。",
        "sections": [{"title": title, "content": ""} for title, _ in COURSE_REPORT_SECTIONS],
    }


def _course_report_markdown() -> str:
    sections = "\n\n".join(f"## {title}\n\n{content}" for title, content in COURSE_REPORT_SECTIONS)
    return f"# {_course_report_outline()['title']}\n\n> {_course_report_outline()['summary']}\n\n{sections}\n"


def _course_agent_interview_result() -> str:
    return """**采访主题:** 一舟一课线下课第一期招生，会暴露哪些成交阻力和交付风险？
**采访人数:** 10 / 30 位模拟Agent

### 关键问答摘录

#### A00 方见舟｜课程发起人 / 同舟会线下课主理人
**Q:** 最担心第一期招生哪一步失控？
**A:** 我不担心大家没有兴趣，我担心大家都在等最后一刻确认。等的人越多，销售越容易被动。所以要把课前诊断、席位机制和交付清单提前说清楚。

#### A02 赵沐阳｜企业主学员 / 智能制造公司创始人
**Q:** 你最希望课程解决什么问题？
**A:** 我想知道AI怎么进入企业销售、客服和管理流程，不想只听工具清单。如果现场能把一个企业流程拆出来，我会考虑带管理层来第二期。

#### A03 林岚｜高意愿学员 / 自媒体创业者
**Q:** 什么会促使你立刻付款？
**A:** 如果我知道现场能带走一套选题方法、提示词、自动化流程、内容复盘模板，并且这些东西能直接用于我接下来一个月的账号更新，我愿意买早鸟。

#### A05 周予白｜销售负责人 / B2B软件公司销售总监
**Q:** 你会被什么打动？
**A:** 我关心的不是AI酷不酷，而是能不能让销售团队更快做客户研究、写拜访提纲、跟进线索。如果课程只讲个人效率，我兴趣会下降。

#### A07 陈亦桥｜价格敏感学员 / 职场转型产品经理
**Q:** 你为什么犹豫？
**A:** 我怕课程太贵但听完不会用。我的问题不是不知道AI重要，而是不知道怎么把AI放进自己的工作流。

#### A09 陆佳宁｜HR培训负责人 / 中型企业组织发展经理
**Q:** 企业培训采购看重什么？
**A:** 我需要看到课程目标、适合人群、课后产出和可复制的内部训练方案。个人报名热度不能直接证明它适合企业内训。

#### A11 孟知秋｜同行拼团组织者 / 知识付费社群运营者
**Q:** 同行优惠的最大风险是什么？
**A:** 拼团能带来转介绍，但规则必须简单。如果三人同行核销复杂，销售会被大量沟通消耗。

#### A15 顾南星｜老学员 / 同舟会活跃成员
**Q:** 你愿意帮忙转介绍吗？
**A:** 愿意，但我需要一段很清楚的话告诉朋友这门课适合谁、不适合谁。否则我怕朋友报了不匹配，最后影响信任。

#### A18 许若安｜退款敏感学员 / 企业培训采购负责人
**Q:** 什么情况会触发退款情绪？
**A:** 如果宣传说得很满，但现场案例和我的行业不相关，我会觉得预期落差大。退款规则要提前写明。

#### A21 沈知微｜观望学员 / 金融行业客户经理
**Q:** 你为什么还没有付款？
**A:** 我想知道课程案例是否能迁移到我的客户经营工作。如果只是教自媒体，我可能不适合；如果能做客户分析和拜访提纲，我会更感兴趣。

#### A24 唐逸舟｜交付运营负责人 / 课程项目经理
**Q:** 课后最重要的动作是什么？
**A:** T+1交付资料，T+7收作业，T+14做一次复盘，T+30筛选转介绍线索。否则线下课热度很快散掉。
"""


def _ensure_course_chat_citations(response: str) -> str:
    if not response:
        return _course_chat_response("")
    normalized = response.strip()
    if "分析路径" not in normalized:
        normalized = (
            "### 分析路径\n"
            "我先检索左侧总结报告，再对照Agent问答和双世界模拟变量，最后只保留能够被章节或Agent原话支撑的判断。\n\n"
            + normalized
        )
    if "[[" in normalized and "]]" in normalized:
        return normalized
    return normalized.rstrip() + "\n\n证据来源：[[S01]] [[S02]] [[A03]] [[A07]]"


def _course_chat_response(message: str) -> str:
    normalized = message.strip()
    if any(k in normalized for k in ["收款", "早鸟", "优惠", "付款", "成交"]):
        return (
            "### 分析路径\n"
            "我先看付款触发点，再对照早鸟/同行机制和Agent原话：高意愿用户要具体交付，拼团组织者要简单规则，运营负责人要后续承接。\n\n"
            "### 结论\n"
            "最优收款打法不是单纯打折，而是把优惠和交付权益绑定：超级早鸟对应首批信任背书，早鸟对应明确行动窗口，两人/三人同行对应熟人转介绍。建议现场主推“确认席位 + 课前诊断 + 优先分组反馈”，不要只说便宜。[[S01]] [[S03]] [[A03]] [[A11]] [[A24]]"
        )
    if any(k in normalized for k in ["退款", "舆情", "风险", "负面"]):
        return (
            "### 分析路径\n"
            "我把负面反馈拆成预期差、规则差和交付差三类，再回看退款敏感学员与交付运营负责人的问答。\n\n"
            "### 结论\n"
            "最大的风险不是退款本身，而是学员觉得宣传和交付不一致。需要提前写清楚课前问卷、现场产出、资料回看、作业反馈和退款边界，把不确定性从付款前就降下来。[[S02]] [[S04]] [[A18]] [[A24]]"
        )
    if any(k in normalized for k in ["SOP", "销售", "话术", "怎么卖"]):
        return (
            "### 分析路径\n"
            "我按成交链路看：先处理用户问题，再证明交付，再选择付款方案；这样能同时回应高意愿、价格敏感和传播型用户。\n\n"
            "### 结论\n"
            "推荐三段式销售SOP：先诊断用户目标和卡点，再展示具体交付物，最后根据决策状态推荐超级早鸟、早鸟或同行方案。这样会比直接推价格更稳，也能减少强销售感。[[S05]] [[S06]] [[A00]] [[A07]] [[A15]]"
        )
    return (
        "### 分析路径\n"
        "我先看执行结论，再看Agent问答暴露出的顾虑，最后把它们归纳成可复制的招生经营系统。\n\n"
        "### 结论\n"
        "这个项目的核心不是把50个名额卖满，而是验证一套可复制的招生经营系统：用户画像、优惠规则、销售SOP、课前诊断、课中交付、课后复盘、退款预警和转介绍。演示时可以强调：Foresight提前模拟真实用户反应，帮团队在正式销售前发现风险和机会。[[S01]] [[S05]] [[S09]] [[S10]]"
    )


def _course_chat_citations() -> List[Dict[str, Any]]:
    citations = [
        {"id": f"S{idx:02d}", "type": "section", "title": title, "anchor": f"section-{idx - 1}"}
        for idx, (title, _content) in enumerate(COURSE_REPORT_SECTIONS, start=1)
    ]
    citations.extend([
        {"id": "A00", "type": "agent", "title": "方见舟｜课程发起人 / 同舟会线下课主理人", "anchor": "agent-0"},
        {"id": "A02", "type": "agent", "title": "赵沐阳｜企业主学员 / 智能制造公司创始人", "anchor": "agent-2"},
        {"id": "A03", "type": "agent", "title": "林岚｜高意愿学员 / 自媒体创业者", "anchor": "agent-3"},
        {"id": "A05", "type": "agent", "title": "周予白｜销售负责人 / B2B软件公司销售总监", "anchor": "agent-5"},
        {"id": "A07", "type": "agent", "title": "陈亦桥｜价格敏感学员 / 职场转型产品经理", "anchor": "agent-7"},
        {"id": "A09", "type": "agent", "title": "陆佳宁｜HR培训负责人 / 中型企业组织发展经理", "anchor": "agent-9"},
        {"id": "A11", "type": "agent", "title": "孟知秋｜同行拼团组织者 / 知识付费社群运营者", "anchor": "agent-11"},
        {"id": "A15", "type": "agent", "title": "顾南星｜老学员 / 同舟会活跃成员", "anchor": "agent-15"},
        {"id": "A18", "type": "agent", "title": "许若安｜退款敏感学员 / 企业培训采购负责人", "anchor": "agent-18"},
        {"id": "A21", "type": "agent", "title": "沈知微｜观望学员 / 金融行业客户经理", "anchor": "agent-21"},
        {"id": "A24", "type": "agent", "title": "唐逸舟｜交付运营负责人 / 课程项目经理", "anchor": "agent-24"},
    ])
    return citations


def _fallback_cached_chat_response(message: str) -> str:
    normalized = message.strip()
    if "最在意" in normalized or "关心" in normalized or "客户" in normalized:
        return _ensure_chat_citations(
            "宁波银行这类高净值客户最在意的不是“AI产品听起来有多热”，而是这几个更底层的问题：\n\n"
            "1. **家庭资产安全垫是否被保护**：现金管理和固收底仓要先讲清楚，尤其是教育金、医疗备用金、企业周转资金不能被科技主题仓位挤占。[[S01]] [[A08]] [[A10]]\n"
            "2. **科技/AI仓位是否可解释**：客户愿意参与AI机会，但不接受单一押注，所以模拟里最终收敛到科技权益22% + AI观察仓8%。[[S04]] [[A01]] [[A02]]\n"
            "3. **回撤和流动性是否有人负责提醒**：客户真正买的是持续复盘服务，而不是一次性产品推荐。[[S02]] [[A05]] [[A14]]\n"
            "4. **家庭共同决策人是否能听懂**：配偶、二代、企业财务负责人都会影响成交，客户经理必须把产品话术改成家庭资产诊断语言。[[A08]] [[A09]] [[A10]]\n"
            "5. **合规边界是否清晰**：不能承诺收益，只能表达情景推演，并要留存风险测评、产品说明、客户确认和季度复盘记录。[[S05]] [[A05]] [[A26]]\n\n"
            "因此，最有价值的销售切入点是：先做家庭资产诊断，再给出“现金20% + 固收增强40% + 科技权益22% + AI观察仓8% + 黄金/多资产10%”的均衡参与档。[[S01]] [[S04]]"
        )

    return _ensure_chat_citations(
        "基于宁波银行高净值客户AI理财组合模拟，我的判断是：这不是一个单纯的产品推荐场景，而是一个“客户经理持续经营系统”场景。"
        "系统需要同时回答客户画像、家庭共同决策、产品组合、销售转化、合规留痕和季度复盘六类问题。"
        "建议现场先看执行结论，再展开 Agent问答暴露的问题和商业机会两章，那里最能体现模拟系统的价值。"
    )


def get_cached_report_chat(
    simulation_id: str,
    message: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    if simulation_id == COURSE_SIM_ID:
        chat_history = chat_history or []
        report = get_cached_report(COURSE_REPORT_ID) or {}
        report_markdown = report.get("markdown_content", "")
        agent_interviews = _course_agent_interview_result()
        system_prompt = f"""你是 Foresight 先见之明的 Report Agent，正在和客户围绕“一舟一课线下课招生、收款与交付风险模拟”对话。

回答要求：
- 使用中文，专业、清晰、适合现场演示。
- 先给一个可展示的“分析路径”，这不是隐藏思维链，而是公开的证据路线：你参考了哪些报告章节、哪些Agent问答、哪些模拟变量。
- 然后给“结论”和“建议动作”。回答要和左侧总结报告一致，不能编造报告之外的新设定。
- 每个关键判断后必须带证据角标，格式只能使用 [[S01]]、[[S02]]、[[S03]]、[[A03]] 这类标记。
- S01-S10 对应报告十个章节；A00、A02、A03、A05、A07、A09、A11、A15、A18、A21、A24 对应具体Agent问答。
- 优先引用：S01执行结论、S02 Agent问答、S03收款结构、S04退款风险、S05商业机会、S06销售SOP、S09落地表、S10展示话术。
- 如果用户问到成交、早鸟、收款，引用 S03、A03、A11；如果问退款或舆情，引用 S04、A18、A24；如果问怎么卖，引用 S06、A00、A07；如果问商业价值，引用 S05、S09、S10。
- 明确说明模拟数据用于经营预演，不是对真实市场结果的承诺。

模拟需求：
{COURSE_REQUIREMENT}

报告正文：
{report_markdown[:12000]}

Agent问答证据：
{agent_interviews}

模拟统计：
- Agent数量：30
- 双世界轮次：8
- 关键动作：18
- 平台：Info Plaza 9条公开传播动作，Topic Community 9条深层讨论动作
"""

        messages = [{"role": "system", "content": system_prompt}]
        for item in chat_history[-8:]:
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})

        try:
            from ..config import Config
            from ..utils.llm_client import LLMClient

            model_name = (
                os.environ.get("REPORT_CHAT_MODEL_NAME")
                or os.environ.get("REPORT_LLM_MODEL_NAME")
                or Config.LLM_MODEL_NAME
            )
            timeout_seconds = float(os.environ.get("REPORT_CHAT_LLM_TIMEOUT_SECONDS", "45"))
            llm = LLMClient(
                api_key=os.environ.get("REPORT_CHAT_LLM_API_KEY") or os.environ.get("REPORT_LLM_API_KEY") or None,
                base_url=os.environ.get("REPORT_CHAT_LLM_BASE_URL") or os.environ.get("REPORT_LLM_BASE_URL") or None,
                model=model_name,
                timeout=timeout_seconds,
            )
            response = _ensure_course_chat_citations(llm.chat(messages=messages, temperature=0.45, max_tokens=1600))
            return {
                "response": response,
                "citations": [],
                "tool_calls": [
                    {
                        "name": "course_report_context_review",
                        "parameters": {
                            "report_id": COURSE_REPORT_ID,
                            "simulation_id": COURSE_SIM_ID,
                            "sections": len(COURSE_REPORT_SECTIONS),
                            "agent_interviews": 10,
                        },
                    },
                    {
                        "name": "llm_synthesis",
                        "parameters": {
                            "model": llm.model,
                            "style": "public_analysis_path_with_evidence_citations",
                        },
                    },
                ],
                "sources": ["cached_interactive_report", "completed_dual_world_replay", "course_agent_interviews"],
                "model_used": llm.model,
                "llm_used": True,
            }
        except Exception as exc:
            model_name = (
                os.environ.get("REPORT_CHAT_MODEL_NAME")
                or os.environ.get("REPORT_LLM_MODEL_NAME")
                or os.environ.get("LLM_MODEL_NAME")
            )
            return {
                "response": _course_chat_response(message),
                "citations": [],
                "tool_calls": [
                    {
                        "name": "course_report_context_fallback",
                        "parameters": {
                            "report_id": COURSE_REPORT_ID,
                            "simulation_id": COURSE_SIM_ID,
                            "llm_error": f"{type(exc).__name__}: {str(exc)[:160]}",
                        },
                    }
                ],
                "sources": ["cached_interactive_report", "completed_dual_world_replay", "course_agent_interviews"],
                "model_used": model_name or "configured-default",
                "llm_used": False,
            }

    if simulation_id != NB_HNW_AI_CASE_ID:
        return None

    chat_history = chat_history or []
    report = get_cached_report(NB_REPORT_ID) or {}
    replay = get_cached_replay(NB_HNW_AI_CASE_ID) or {}
    aggregate = replay.get("aggregate", {})
    rounds = replay.get("rounds", [])
    sampled_actions = []
    for round_data in rounds:
        for action in round_data.get("actions", [])[:3]:
            sampled_actions.append(
                f"R{action.get('round_num')} {action.get('platform')} / {action.get('agent_name')}: "
                f"{action.get('action_args', {}).get('content', '')}"
            )

    system_prompt = f"""你是 Foresight 先见之明的 Report Agent，正在和银行客户围绕一份已完成的模拟报告对话。

回答要求：
- 直接回答用户问题，不要说自己不能访问系统。
- 使用中文，口吻专业、克制、适合宁波银行客户经理和管理层现场演示。
- 优先引用报告结论、Agent问答和双世界模拟结果。
- 涉及金融产品时必须说明这是情景推演，不承诺收益，不替代正式适当性评估。
- 回答要有可执行建议，避免空泛。
- 每个关键判断后必须带证据角标，格式只能使用 [[S01]]、[[S02]]、[[A01]]、[[A08]] 这类标记。
- S01-S06 对应报告六个章节；A00-A29 对应虚拟Agent。优先引用 S01执行结论、S02 Agent问答、A01高净值客户A、A08配偶共同决策人、A10企业财务负责人、A05风控合规经理、A29销售管理看板。
- 不要编造不存在的Agent编号；如果不确定，用 [[S01]] 或 [[S02]]。

模拟需求：
{NB_REQUIREMENT}

报告正文：
{report.get('markdown_content', '')[:7000]}

模拟统计：
- Agent数量：{len(CASE_AGENTS)}
- 总动作：{aggregate.get('total_actions')}
- 轮次：{aggregate.get('rounds_with_actions')}
- 平台动作：{aggregate.get('platform_totals')}

部分Agent行为证据：
{chr(10).join(sampled_actions[:18])}
"""

    messages = [{"role": "system", "content": system_prompt}]
    for item in chat_history[-8:]:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    try:
        from ..config import Config
        from ..utils.llm_client import LLMClient

        model_name = (
            os.environ.get("REPORT_CHAT_MODEL_NAME")
            or os.environ.get("REPORT_LLM_MODEL_NAME")
            or Config.LLM_MODEL_NAME
        )
        timeout_seconds = float(os.environ.get("REPORT_CHAT_LLM_TIMEOUT_SECONDS", "45"))
        llm = LLMClient(
            api_key=os.environ.get("REPORT_CHAT_LLM_API_KEY") or os.environ.get("REPORT_LLM_API_KEY") or None,
            base_url=os.environ.get("REPORT_CHAT_LLM_BASE_URL") or os.environ.get("REPORT_LLM_BASE_URL") or None,
            model=model_name,
            timeout=timeout_seconds,
        )
        response = _ensure_chat_citations(llm.chat(messages=messages, temperature=0.45, max_tokens=1200))
        return {
            "response": response,
            "citations": [],
            "tool_calls": [
                {
                    "name": "cached_report_context",
                    "parameters": {
                        "report_id": NB_REPORT_ID,
                        "simulation_id": NB_HNW_AI_CASE_ID,
                        "model": llm.model,
                    },
                }
            ],
            "sources": ["cached_interactive_report", "cached_dual_world_replay"],
            "model_used": llm.model,
            "llm_used": True,
        }
    except Exception as exc:
        model_name = (
            os.environ.get("REPORT_CHAT_MODEL_NAME")
            or os.environ.get("REPORT_LLM_MODEL_NAME")
            or os.environ.get("LLM_MODEL_NAME")
        )
        return {
            "response": _fallback_cached_chat_response(message),
            "citations": [],
            "tool_calls": [
                {
                    "name": "cached_report_context_fallback",
                    "parameters": {
                        "report_id": NB_REPORT_ID,
                        "simulation_id": NB_HNW_AI_CASE_ID,
                        "llm_error": f"{type(exc).__name__}: {str(exc)[:160]}",
                    },
                }
            ],
            "sources": ["cached_interactive_report", "cached_dual_world_replay"],
            "model_used": model_name or "configured-default",
            "llm_used": False,
        }


def get_cached_report_logs(report_id: str, from_line: int = 0) -> Optional[Dict[str, Any]]:
    if report_id == COURSE_REPORT_ID:
        logs: List[Dict[str, Any]] = [
            {
                "timestamp": _course_time(0),
                "elapsed_seconds": 0,
                "report_id": COURSE_REPORT_ID,
                "action": "report_start",
                "stage": "pending",
                "details": {
                    "simulation_id": COURSE_SIM_ID,
                    "graph_id": COURSE_GRAPH_ID,
                    "simulation_requirement": COURSE_REQUIREMENT,
                    "message": "开始回溯一舟一课线下课招生与交付风险模拟。",
                },
            },
            {
                "timestamp": _course_time(1),
                "elapsed_seconds": 60,
                "report_id": COURSE_REPORT_ID,
                "action": "planning_complete",
                "stage": "planning",
                "details": {"message": "报告结构规划完成。", "outline": _course_report_outline()},
            },
            {
                "timestamp": _course_time(2),
                "elapsed_seconds": 120,
                "report_id": COURSE_REPORT_ID,
                "action": "tool_result",
                "stage": "generating",
                "details": {
                    "tool_name": "interview_agents",
                    "result": _course_agent_interview_result(),
                    "result_length": len(_course_agent_interview_result()),
                    "message": "关键学员与运营角色采访完成。",
                },
            },
        ]
        elapsed = 150
        for idx, (title, content) in enumerate(COURSE_REPORT_SECTIONS, start=1):
            logs.extend([
                {
                    "timestamp": _course_time(idx + 2),
                    "elapsed_seconds": elapsed,
                    "report_id": COURSE_REPORT_ID,
                    "action": "section_start",
                    "stage": "generating",
                    "section_title": title,
                    "section_index": idx,
                    "details": {"message": f"开始生成章节：{title}"},
                },
                {
                    "timestamp": _course_time(idx + 2),
                    "elapsed_seconds": elapsed + 20,
                    "report_id": COURSE_REPORT_ID,
                    "action": "section_complete",
                    "stage": "generating",
                    "section_title": title,
                    "section_index": idx,
                    "details": {"message": f"章节完成：{title}", "content": content},
                },
            ])
            elapsed += 45
        logs.append({
            "timestamp": _course_time(8),
            "elapsed_seconds": elapsed,
            "report_id": COURSE_REPORT_ID,
            "action": "report_complete",
            "stage": "completed",
            "details": {"message": "招生模拟总结报告生成完成，可进入Report Agent交互提问。"},
        })
        return {
            "logs": logs[from_line:],
            "total_lines": len(logs),
            "from_line": from_line,
            "has_more": False,
        }

    if report_id != NB_REPORT_ID:
        return None

    logs: List[Dict[str, Any]] = [
        {
            "timestamp": _case_time(62),
            "elapsed_seconds": 0,
            "report_id": NB_REPORT_ID,
            "action": "report_start",
            "stage": "pending",
            "details": {
                "simulation_id": NB_HNW_AI_CASE_ID,
                "graph_id": NB_GRAPH_ID,
                "simulation_requirement": NB_REQUIREMENT,
                "message": "开始回溯宁波银行高净值客户AI理财组合案例。",
            },
        },
        {
            "timestamp": _case_time(63),
            "elapsed_seconds": 60,
            "report_id": NB_REPORT_ID,
            "action": "planning_start",
            "stage": "planning",
            "details": {"message": "读取图谱、Agent行为和销售转化变量，规划报告结构。"},
        },
        {
            "timestamp": _case_time(64),
            "elapsed_seconds": 120,
            "report_id": NB_REPORT_ID,
            "action": "planning_complete",
            "stage": "planning",
            "details": {"message": "报告结构规划完成。", "outline": _report_outline()},
        },
        {
            "timestamp": _case_time(64),
            "elapsed_seconds": 135,
            "report_id": NB_REPORT_ID,
            "action": "tool_call",
            "stage": "generating",
            "details": {
                "iteration": 1,
                "tool_name": "interview_agents",
                "parameters": {
                    "topic": "客户问答暴露的问题与商业机会",
                    "agent_count": 6,
                    "simulation_id": NB_HNW_AI_CASE_ID,
                },
                "message": "采访关键虚拟Agent，提取客户阻力、家庭决策、合规边界和团队复制线索。",
            },
        },
        {
            "timestamp": _case_time(64),
            "elapsed_seconds": 150,
            "report_id": NB_REPORT_ID,
            "action": "tool_result",
            "stage": "generating",
            "details": {
                "tool_name": "interview_agents",
                "result": _agent_interview_result(),
                "result_length": len(_agent_interview_result()),
                "message": "Agent采访完成，可展开查看各角色问答。",
            },
        },
        {
            "timestamp": _case_time(64),
            "elapsed_seconds": 165,
            "report_id": NB_REPORT_ID,
            "action": "tool_call",
            "stage": "generating",
            "details": {
                "iteration": 1,
                "tool_name": "insight_forge",
                "parameters": {
                    "query": "宁波银行高净值客户AI理财组合推介的机会、风险和销售路径",
                    "simulation_id": NB_HNW_AI_CASE_ID,
                },
                "message": "汇总图谱、Agent行为和销售变量，生成深度洞察。",
            },
        },
        {
            "timestamp": _case_time(64),
            "elapsed_seconds": 180,
            "report_id": NB_REPORT_ID,
            "action": "tool_result",
            "stage": "generating",
            "details": {
                "tool_name": "insight_forge",
                "result": _insight_result(),
                "result_length": len(_insight_result()),
                "message": "深度洞察完成。",
            },
        },
    ]

    elapsed = 210
    minute = 65
    for idx, (title, content) in enumerate(_expanded_report_sections(), start=1):
        logs.extend([
            {
                "timestamp": _case_time(minute),
                "elapsed_seconds": elapsed,
                "report_id": NB_REPORT_ID,
                "action": "section_start",
                "stage": "generating",
                "section_title": title,
                "section_index": idx,
                "details": {"message": f"开始生成章节：{title}"},
            },
            {
                "timestamp": _case_time(minute),
                "elapsed_seconds": elapsed + 15,
                "report_id": NB_REPORT_ID,
                "action": "tool_call",
                "stage": "generating",
                "section_title": title,
                "section_index": idx,
                "details": {
                    "iteration": 1,
                    "tool_name": "simulation_replay_search",
                    "parameters": {"query": title, "simulation_id": NB_HNW_AI_CASE_ID},
                    "message": "检索缓存推演动作与图谱变量。",
                },
            },
            {
                "timestamp": _case_time(minute + 1),
                "elapsed_seconds": elapsed + 45,
                "report_id": NB_REPORT_ID,
                "action": "section_complete",
                "stage": "generating",
                "section_title": title,
                "section_index": idx,
                "details": {"message": f"章节完成：{title}", "content": content},
            },
        ])
        elapsed += 75
        minute += 1

    logs.append({
        "timestamp": _case_time(70),
        "elapsed_seconds": 480,
        "report_id": NB_REPORT_ID,
        "action": "report_complete",
        "stage": "completed",
        "details": {"message": "分析报告生成完成，可进入历史回溯查看。"},
    })

    sliced = logs[from_line:]
    return {
        "logs": sliced,
        "total_lines": len(logs),
        "from_line": from_line,
        "has_more": False,
    }


def get_cached_console_log(report_id: str, from_line: int = 0) -> Optional[Dict[str, Any]]:
    if report_id == COURSE_REPORT_ID:
        lines = [
            "[21:10:09] INFO: 加载一舟一课线下课双世界模拟结果",
            "[21:10:18] INFO: 双世界并行模拟完成：8轮 / 30个Agent / 18条关键动作",
            "[21:10:20] INFO: 提取招生转化、早鸟优惠、同行拼团、退款舆情与交付风险变量",
            "[21:10:22] INFO: Report Agent 生成总结页和可提问上下文",
            "[21:10:24] INFO: 交互总结页已就绪",
        ]
        return {
            "logs": lines[from_line:],
            "total_lines": len(lines),
            "from_line": from_line,
            "has_more": False,
        }

    if report_id != NB_REPORT_ID:
        return None
    lines = [
        "[09:32:00] INFO: 加载宁波银行缓存推演案例",
        "[09:33:00] INFO: 读取30个虚拟Agent、8轮双世界动作和销售转化变量",
        "[09:34:00] INFO: Report Agent 完成互动报告结构规划",
        "[09:34:15] INFO: Agent Interview 完成：客户、家庭成员、投顾、合规、管理看板",
        "[09:34:30] INFO: Deep Insight 完成：提取机会、风险和销售路径",
        "[09:35:00] INFO: 生成执行结论",
        "[09:36:00] INFO: 生成Agent问答暴露的问题",
        "[09:37:00] INFO: 生成商业机会",
        "[09:38:00] INFO: 生成产品组合与销售路径",
        "[09:39:00] INFO: 生成合规边界与风险控制",
        "[09:40:00] INFO: 报告生成完成",
    ]
    return {
        "logs": lines[from_line:],
        "total_lines": len(lines),
        "from_line": from_line,
        "has_more": False,
    }


def get_cached_infographic(report_id: str) -> Optional[Dict[str, Any]]:
    if report_id == COURSE_REPORT_ID:
        return {
            "key_metrics": {
                "total_agents": 30,
                "total_posts": 18,
                "total_engagement": 18,
                "avg_activity": "0.6",
                "total_rounds": 8,
            },
            "action_distribution": {
                "by_type": {"CREATE_POST": 18},
                "by_platform": {"twitter": {"CREATE_POST": 9}, "reddit": {"CREATE_POST": 9}},
            },
            "sentiment_breakdown": {
                "positive_ratio": 56,
                "neutral_ratio": 28,
                "negative_ratio": 16,
            },
            "top_agents": [
                {"agent_id": 0, "agent_name": "课程发起人", "agent_title": "招生负责人", "total_actions": 3},
                {"agent_id": 3, "agent_name": "高意愿学员", "agent_title": "自媒体创业者", "total_actions": 2},
                {"agent_id": 7, "agent_name": "价格敏感学员", "agent_title": "职场转型者", "total_actions": 2},
                {"agent_id": 24, "agent_name": "交付运营负责人", "agent_title": "课程交付负责人", "total_actions": 2},
            ],
            "timeline": [{"round_num": i, "total": 18 if i == 1 else 0} for i in range(1, 9)],
            "portfolio": [
                {"name": "超级早鸟", "value": 10},
                {"name": "早鸟", "value": 22},
                {"name": "两人同行", "value": 12},
                {"name": "三人同行", "value": 6},
            ],
            "sales_effect": {
                "first_conversion": "60%-72%",
                "diagnosis_followup": "课前诊断显著降低犹豫",
                "compliance": "明确退款边界与交付清单",
            },
        }

    if report_id != NB_REPORT_ID:
        return None

    by_type: Dict[str, int] = {}
    by_platform: Dict[str, Dict[str, int]] = {"twitter": {}, "reddit": {}}
    agent_counts: Dict[int, Dict[str, Any]] = {}
    timeline = []

    for round_idx, round_actions in enumerate(ROUND_ACTIONS, start=1):
        timeline.append({"round_num": round_idx, "total": len(round_actions)})
        for entry in round_actions:
            platform, agent_id, action_type, _content = entry
            by_type[action_type] = by_type.get(action_type, 0) + 1
            by_platform[platform][action_type] = by_platform[platform].get(action_type, 0) + 1
            agent = next((a for a in CASE_AGENTS if a[0] == agent_id), CASE_AGENTS[0])
            persona = _agent_persona(agent_id, agent[1], agent[2], agent[3])
            bucket = agent_counts.setdefault(agent_id, {
                "agent_id": agent_id,
                "agent_name": persona["display_name"],
                "agent_title": persona["title"],
                "entity_name": agent[1],
                "total_actions": 0,
            })
            bucket["total_actions"] += 1

    total_actions = sum(by_type.values())
    top_agents = sorted(agent_counts.values(), key=lambda x: x["total_actions"], reverse=True)

    return {
        "key_metrics": {
            "total_agents": len(CASE_AGENTS),
            "total_posts": by_type.get("CREATE_POST", 0),
            "total_engagement": total_actions,
            "avg_activity": f"{total_actions / len(CASE_AGENTS):.1f}",
            "total_rounds": len(ROUND_ACTIONS),
        },
        "action_distribution": {
            "by_type": by_type,
            "by_platform": by_platform,
        },
        "sentiment_breakdown": {
            "positive_ratio": 62,
            "neutral_ratio": 26,
            "negative_ratio": 12,
        },
        "top_agents": top_agents[:8],
        "timeline": timeline,
        "portfolio": [
            {"name": "现金管理", "value": 20},
            {"name": "固收增强", "value": 40},
            {"name": "科技主题权益", "value": 22},
            {"name": "AI观察仓", "value": 8},
            {"name": "黄金/多资产", "value": 10},
        ],
        "sales_effect": {
            "first_conversion": "60%-70%",
            "diagnosis_followup": "75%",
            "compliance": "不承诺收益，先做适当性匹配",
        },
    }


ROUND_ACTIONS = [
    [
        ("twitter", 0, "CREATE_POST", "Info Plaza开场：大客户经理提出为高净值客户设计科技与AI主题组合，要求同时预测产品组成、销售转化和合规风险。"),
        ("twitter", 11, "CREATE_COMMENT", "分行财富主管关注可复制打法：如果能把客户画像、家庭会议和季度复盘串起来，这套方法可以复制给整个私行团队。"),
        ("twitter", 29, "CREATE_POST", "销售管理看板初始化：监控首轮成交概率、二次转化、AUM新增、合规留痕和服务满意度五个指标。"),
        ("reddit", 1, "CREATE_POST", "Topic Community中客户表达偏好：可接受中等波动，但不希望AI主题过度集中，必须保留家庭流动性。"),
        ("reddit", 8, "CREATE_COMMENT", "配偶共同决策人补充：先保证家庭资产安全垫，再讨论科技成长，不要只讲概念热度。"),
        ("reddit", 5, "CREATE_COMMENT", "合规经理提示：先完成风险承受能力匹配，再做产品范围筛选，不承诺收益。"),
    ],
    [
        ("twitter", 2, "CREATE_POST", "投顾给出初始框架：现金20%、固收35%、科技权益25%、AI观察仓10%、黄金/多资产10%。"),
        ("twitter", 4, "CREATE_COMMENT", "固收产品经理建议用短债、同业存单和中高等级信用债做底仓，保持3到6个月可调仓窗口。"),
        ("twitter", 15, "CREATE_COMMENT", "量化对冲产品经理建议加入低相关工具，降低科技主题仓位对整体波动的冲击。"),
        ("reddit", 7, "CREATE_POST", "家族办公室要求组合必须能解释给家庭成员，并设置季度复盘触发条件。"),
        ("reddit", 10, "CREATE_COMMENT", "企业财务负责人提醒：企业经营资金不能被锁死，流动性产品比例必须清楚。"),
        ("reddit", 23, "CREATE_COMMENT", "保守型客户C质疑：AI主题听起来太热，是否会在高位接盘？"),
    ],
    [
        ("twitter", 6, "CREATE_POST", "AI行业研究员拆解变量：算力资本开支、国产芯片替代、数据中心电力约束、云厂商盈利弹性。"),
        ("twitter", 17, "CREATE_COMMENT", "半导体研究员提示：国产替代机会明确，但估值分位和订单兑现节奏要纳入仓位控制。"),
        ("twitter", 18, "CREATE_COMMENT", "云计算研究员补充：云厂商盈利弹性会影响AI软件和平台类资产的二阶表现。"),
        ("reddit", 3, "CREATE_POST", "科技基金经理建议权益仓拆成AI基础设施、半导体设备、云软件三条线，避免只押单一热点。"),
        ("reddit", 19, "CREATE_COMMENT", "数据中心研究员提醒：电力约束和资本开支节奏会影响数据中心REITs和算力链条。"),
        ("reddit", 0, "LIKE_POST", "客户经理标记该变量拆解可用于客户拜访开场。"),
    ],
    [
        ("twitter", 5, "CREATE_POST", "风控合规经理提出硬约束：科技权益与AI观察仓合计不超过35%，单产品不超过15%，设置回撤提醒线。"),
        ("twitter", 12, "CREATE_COMMENT", "总行产品准入经理确认：推荐范围必须落在白名单和客户风险等级匹配范围内。"),
        ("twitter", 26, "CREATE_COMMENT", "合规质检员要求：所有AI主题表达都改成情景推演，不出现确定性收益暗示。"),
        ("reddit", 2, "CREATE_POST", "投顾将组合改为均衡参与档：现金20%、固收增强40%、科技权益22%、AI观察仓8%、黄金/多资产10%。"),
        ("reddit", 1, "CREATE_COMMENT", "客户认为调整后更符合家庭资产安全垫，希望看到销售转化和后续服务节奏。"),
        ("reddit", 8, "CREATE_COMMENT", "共同决策人认可现金与固收比例，但要求每季度复盘并提前提示回撤风险。"),
    ],
    [
        ("twitter", 0, "CREATE_POST", "客户经理设计推介路径：先讲家庭目标和风险边界，再讲AI产业链机会，最后给出三档组合。"),
        ("twitter", 14, "CREATE_COMMENT", "客户服务经理补充会后机制：T+1发送组合摘要，T+30回访体验，季度更新变量看板。"),
        ("twitter", 13, "CREATE_COMMENT", "运营留痕专员同步：风险测评、产品说明、客户确认、会议纪要全部进入留痕包。"),
        ("reddit", 2, "CREATE_POST", "三档组合为稳健观察、均衡参与、进取主题；默认推荐均衡参与，不主动推最高风险档。"),
        ("reddit", 5, "CREATE_COMMENT", "合规经理确认口播：这是资产配置建议与情景推演，不是收益预测。"),
        ("reddit", 9, "CREATE_COMMENT", "二代继承人更偏好进取主题档，但接受先用均衡参与档建立观察仓。"),
    ],
    [
        ("twitter", 3, "CREATE_POST", "基金经理预测产品组成：科技权益用主动基金+指数增强，AI观察仓用低杠杆结构或净值型主题产品。"),
        ("twitter", 16, "CREATE_COMMENT", "黄金多资产策略师建议：黄金/多资产维持10%，用于对冲汇率和风险偏好下行。"),
        ("twitter", 20, "CREATE_COMMENT", "利率策略师提示：若利率下行延续，固收增强底仓仍有解释优势，但久期不能过长。"),
        ("reddit", 4, "CREATE_POST", "固收经理预测底仓销售接受度高，客户容易理解，预计可承担约40%配置比例。"),
        ("reddit", 6, "CREATE_COMMENT", "研究员提醒短期波动来自估值和政策预期，建议用分批建仓降低择时压力。"),
        ("reddit", 21, "CREATE_COMMENT", "汇率策略师认为海外资产顾虑会提高黄金和境内多资产产品的接受度。"),
    ],
    [
        ("twitter", 29, "CREATE_POST", "看板预测：完成适当性匹配后首轮成交概率60%-70%；加入家庭资产诊断后二次转化约75%。"),
        ("twitter", 11, "CREATE_COMMENT", "分行财富主管判断：如果AUM新增达到客户可投资资产的15%-20%，团队复制价值明显。"),
        ("twitter", 25, "CREATE_COMMENT", "推荐人观察：客户若认可复盘机制，有机会把同圈层企业主介绍给客户经理。"),
        ("reddit", 0, "CREATE_POST", "客户经理总结成交关键：不是AI概念，而是现金流、回撤、产品集中度和后续复盘机制。"),
        ("reddit", 7, "CREATE_COMMENT", "家族办公室同意：家庭成员能理解组合后，成交阻力明显下降。"),
        ("reddit", 1, "CREATE_COMMENT", "客户表示愿意先配置均衡参与档，并保留下一季度追加科技权益的选择权。"),
    ],
    [
        ("twitter", 2, "CREATE_POST", "最终建议：以均衡参与档作为主推，配置比例为现金20%、固收增强40%、科技权益22%、AI观察仓8%、黄金/多资产10%。"),
        ("twitter", 27, "CREATE_COMMENT", "家族信托顾问建议把传承诉求列入后续服务，不在首次成交中强推。"),
        ("twitter", 28, "CREATE_COMMENT", "保险金信托顾问建议将保障和传承作为后续交叉销售线索。"),
        ("reddit", 5, "CREATE_POST", "合规结论：必须留存风险测评、产品说明、客户确认和不保证收益提示。"),
        ("reddit", 0, "CREATE_COMMENT", "客户经理输出拜访提纲：客户画像、资产目标、组合建议、AI变量、风险边界、复盘安排。"),
        ("reddit", 29, "CREATE_COMMENT", "销售管理看板标记本轮完成：成交概率、二次转化、AUM新增和服务满意度均进入可复盘状态。"),
    ],
]


def _action(agent_id: int, round_num: int, action_type: str, content: str, timestamp: str, platform: str = "reddit") -> Dict[str, Any]:
    agent = next((a for a in CASE_AGENTS if a[0] == agent_id), CASE_AGENTS[0])
    persona = _agent_persona(agent_id, agent[1], agent[2], agent[3])
    return {
        "round_num": round_num,
        "timestamp": timestamp,
        "platform": platform,
        "agent_id": agent_id,
        "agent_name": persona["display_name"],
        "agent_title": persona["title"],
        "entity_name": agent[1],
        "action_type": action_type,
        "action_args": {
            "content": content,
            "topic": "宁波银行大客户经理面向高净值客户推介科技、AI相关理财产品组合",
        },
        "result": content,
        "success": True,
    }


def get_cached_replay(simulation_id: str) -> Optional[Dict[str, Any]]:
    if simulation_id != NB_HNW_AI_CASE_ID:
        return None

    start = datetime.fromisoformat(NB_CREATED_AT)
    rounds: List[Dict[str, Any]] = []
    all_actions: List[Dict[str, Any]] = []

    for round_idx, entries in enumerate(ROUND_ACTIONS, start=1):
        actions = []
        for offset, entry in enumerate(entries):
            if len(entry) == 4:
                platform, agent_id, action_type, content = entry
            else:
                agent_id, action_type, content = entry
                platform = "reddit"
            ts = (start + timedelta(minutes=(round_idx - 1) * 8 + offset * 2)).isoformat()
            item = _action(agent_id, round_idx, action_type, content, ts, platform)
            actions.append(item)
            all_actions.append(item)

        by_type: Dict[str, int] = {}
        active_agents = set()
        for item in actions:
            by_type[item["action_type"]] = by_type.get(item["action_type"], 0) + 1
            active_agents.add(item["agent_id"])

        rounds.append({
            "round_num": round_idx,
            "simulated_hour": 9 + round_idx,
            "simulated_day": 1,
            "first_timestamp": actions[0]["timestamp"],
            "last_timestamp": actions[-1]["timestamp"],
            "actions": actions,
            "stats": {
                "total_actions": len(actions),
                "active_agents_count": len(active_agents),
                "by_type": by_type,
                "by_platform": {
                    "twitter": len([a for a in actions if a["platform"] == "twitter"]),
                    "reddit": len([a for a in actions if a["platform"] == "reddit"]),
                },
            },
        })

    action_type_dist: Dict[str, int] = {}
    agent_counts: Dict[int, Dict[str, Any]] = {}
    for item in all_actions:
        action_type_dist[item["action_type"]] = action_type_dist.get(item["action_type"], 0) + 1
        bucket = agent_counts.setdefault(item["agent_id"], {
            "agent_id": item["agent_id"],
            "agent_name": item["agent_name"],
            "count": 0,
        })
        bucket["count"] += 1

    top_agents = sorted(agent_counts.values(), key=lambda x: x["count"], reverse=True)
    platform_totals = {
        "twitter": len([a for a in all_actions if a["platform"] == "twitter"]),
        "reddit": len([a for a in all_actions if a["platform"] == "reddit"]),
    }

    return {
        "simulation": {
            "simulation_id": NB_HNW_AI_CASE_ID,
            "project_id": NB_PROJECT_ID,
            "graph_id": NB_GRAPH_ID,
            "status": "completed",
            "enable_twitter": True,
            "enable_reddit": True,
            "entities_count": len(CASE_AGENTS),
            "profiles_count": len(CASE_AGENTS),
            "created_at": start.isoformat(),
            "updated_at": (start + timedelta(minutes=70)).isoformat(),
        },
        "project": {
            "project_id": NB_PROJECT_ID,
            "name": "宁波银行高净值客户AI理财组合推介",
            "status": "graph_completed",
            "graph_id": NB_GRAPH_ID,
            "simulation_requirement": NB_REQUIREMENT,
            "files": _cached_files(),
            "total_text_length": 4096,
            "analysis_summary": "现场缓存案例：从客户画像、风险边界、产品组合、销售路径和合规话术五个角度重放推演过程。",
            "ontology_entity_types": [a[2] for a in CASE_AGENTS],
        },
        "workflow": [
            {"step": 1, "name": "客户画像与目标确认", "status": "completed", "metadata": {"files": [{"filename": "cached_case_nb_hnw_ai.md", "size": 4096}], "requirement": "高净值客户科技/AI产品组合推介", "text_length": 4096, "analysis_summary": "已确认客户风险偏好、流动性要求和科技主题兴趣。"}},
            {"step": 2, "name": "关系图谱与变量提取", "status": "completed", "metadata": {"graph_id": NB_GRAPH_ID, "entity_types": [a[2] for a in CASE_AGENTS], "entities_count": len(CASE_AGENTS), "ontology_entity_types": [a[2] for a in CASE_AGENTS]}},
            {"step": 3, "name": "Agent 角色生成", "status": "completed", "metadata": {"profiles_count": len(CASE_AGENTS), "agents_loaded": len(CASE_AGENTS)}},
            {"step": 4, "name": "产品组合与销售路径配置", "status": "completed", "metadata": {"config_reasoning": "按稳健底仓、科技成长、AI观察仓和避险资产构建组合，并加入适当性与合规边界。", "total_simulation_hours": 8, "minutes_per_round": 60, "peak_hours": [10, 14, 20], "agents_per_hour_min": 8, "agents_per_hour_max": 14, "initial_posts_count": 3}},
            {"step": 5, "name": "缓存回放：双世界销售效果推演", "status": "completed", "metadata": {"total_rounds_executed": len(rounds), "total_actions": len(all_actions), "twitter_enabled": True, "reddit_enabled": True, "by_platform": platform_totals, "current_run_started_at": start.isoformat(), "simulation_created_at": start.isoformat(), "updated_at": (start + timedelta(minutes=70)).isoformat()}},
        ],
        "config": {
            "time_config": {
                "total_simulation_hours": 8,
                "minutes_per_round": 60,
                "agents_per_hour_min": 8,
                "agents_per_hour_max": 14,
                "peak_hours": [10, 14, 20],
            },
            "event_config": {
                "initial_posts": [
                    {"content": "客户经理发起高净值客户AI主题组合推介。"},
                    {"content": "投顾拆解稳健底仓与科技成长仓。"},
                    {"content": "合规经理确认适当性和风险提示。"},
                ],
                "events": [
                    {"name": "AI主题热度上升", "impact": "提高客户兴趣，但放大波动担忧。"},
                    {"name": "客户要求保留流动性", "impact": "提高现金和固收增强比例。"},
                ],
            },
            "agent_configs_count": len(CASE_AGENTS),
        },
        "agents": [
            _agent_profile_payload(agent_id, name, role, bio)
            for agent_id, name, role, bio in CASE_AGENTS
        ],
        "rounds": rounds,
        "aggregate": {
            "total_actions": len(all_actions),
            "rounds_with_actions": len(rounds),
            "action_type_distribution": action_type_dist,
            "platform_totals": platform_totals,
            "top_agents": top_agents[:10],
            "cached_case": True,
            "case_summary": {
                "recommended_portfolio": "现金管理20% + 固收增强40% + 科技主题权益22% + AI观察仓8% + 黄金/多资产10%",
                "sales_effect": "风险匹配通过后首轮成交概率约60%-70%；叠加家庭资产诊断后二次转化约75%。",
                "compliance_note": "仅作资产配置情景推演，不承诺收益，不替代正式适当性评估。",
            },
        },
    }


def get_cached_run_status(simulation_id: str) -> Optional[Dict[str, Any]]:
    replay = get_cached_replay(simulation_id)
    if not replay:
        return None

    aggregate = replay.get("aggregate", {})
    platform_totals = aggregate.get("platform_totals", {})
    total_rounds = len(replay.get("rounds", []))
    return {
        "simulation_id": simulation_id,
        "runner_status": "completed",
        "current_round": total_rounds,
        "total_rounds": total_rounds,
        "progress_percent": 100,
        "simulated_hours": 8,
        "total_simulation_hours": 8,
        "twitter_running": False,
        "reddit_running": False,
        "twitter_completed": True,
        "reddit_completed": True,
        "twitter_current_round": total_rounds,
        "reddit_current_round": total_rounds,
        "twitter_simulated_hours": 8,
        "reddit_simulated_hours": 8,
        "twitter_actions_count": platform_totals.get("twitter", 0),
        "reddit_actions_count": platform_totals.get("reddit", 0),
        "total_actions_count": aggregate.get("total_actions", 0),
        "started_at": NB_CREATED_AT,
        "updated_at": _case_time(70),
        "completed_at": _case_time(70),
        "process_pid": None,
        "cached_case": True,
    }


def get_cached_run_detail(simulation_id: str, platform_filter: Optional[str] = None) -> Optional[Dict[str, Any]]:
    replay = get_cached_replay(simulation_id)
    if not replay:
        return None

    all_actions = []
    for round_data in replay.get("rounds", []):
        all_actions.extend(round_data.get("actions", []))

    if platform_filter in ("twitter", "reddit"):
        visible_actions = [a for a in all_actions if a.get("platform") == platform_filter]
    else:
        visible_actions = all_actions

    twitter_actions = [a for a in all_actions if a.get("platform") == "twitter"]
    reddit_actions = [a for a in all_actions if a.get("platform") == "reddit"]
    status = get_cached_run_status(simulation_id) or {}
    status.update({
        "all_actions": visible_actions,
        "twitter_actions": twitter_actions if platform_filter in (None, "twitter") else [],
        "reddit_actions": reddit_actions if platform_filter in (None, "reddit") else [],
        "recent_actions": replay.get("rounds", [])[-1].get("actions", []) if replay.get("rounds") else [],
        "rounds_count": len(replay.get("rounds", [])),
    })
    return status


def get_cached_history_items() -> List[Dict[str, Any]]:
    """Return completed replay cases shown as first-class history cards."""
    start = datetime.fromisoformat("2026-06-04T09:30:00")
    end = start + timedelta(minutes=70)

    return [
        {
            "simulation_id": NB_HNW_AI_CASE_ID,
            "project_id": NB_PROJECT_ID,
            "graph_id": NB_GRAPH_ID,
            "report_id": NB_REPORT_ID,
            "has_replay": True,
            "is_cached_case": True,
            "cached_label": "已完成回放",
            "project_name": "宁波银行高净值客户AI理财组合推介",
            "simulation_requirement": NB_REQUIREMENT,
            "status": "completed",
            "runner_status": "completed",
            "entities_count": len(CASE_AGENTS),
            "profiles_count": len(CASE_AGENTS),
            "entity_types": [agent[2] for agent in CASE_AGENTS],
            "files": [
                {"filename": "宁波银行高净值客户AI理财组合缓存案例.md", "size": 4096},
                {"filename": "产品组合与销售效果回放.json", "size": 8192},
            ],
            "created_at": start.isoformat(),
            "updated_at": end.isoformat(),
            "created_date": start.date().isoformat(),
            "total_rounds": len(ROUND_ACTIONS),
            "current_round": len(ROUND_ACTIONS),
            "total_actions": sum(len(round_actions) for round_actions in ROUND_ACTIONS),
            "version": "demo-replay",
        }
    ]
