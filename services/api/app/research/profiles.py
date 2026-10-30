"""调研档位定义与注册表。

调研档位决定一次项目分析的检查清单、质量评分权重、验证器检查和报告章节。
这些配置是确定性业务规则，不依赖数据库，也不包含供应商相关的模型参数。
"""

from __future__ import annotations

from dataclasses import dataclass


# 项目未指定档位或指定了未知 key 时使用的默认调研目标。
DEFAULT_RESEARCH_PROFILE = "quick_onboarding"


@dataclass(frozen=True)
class ResearchProfile:
    """一种调研目标的不可变配置。"""

    # 稳定 key 用于持久化和接口传参，label 仅用于人类阅读。
    key: str
    label: str
    description: str
    # 分析过程中需要逐项回答的检查清单。
    checklist: list[str]
    # 六维质量评分的权重，正常配置下总和应为 1。
    quality_weights: dict[str, float]
    # 该档位要求的确定性验证项。
    verifier_checks: list[str]
    # 最终报告需要包含的档位专属章节。
    report_sections: list[str]
    # 形成结论前必须覆盖的证据类别。
    required_evidence_types: list[str]


# 注册表是项目调研策略的唯一事实来源；新增档位时必须同时维护完整字段。
PROFILE_REGISTRY: dict[str, ResearchProfile] = {
    # 面向新成员快速接手，优先覆盖项目用途、入口、依赖和阅读路线。
    "quick_onboarding": ResearchProfile(
        key="quick_onboarding",
        label="快速接手",
        description="帮助新人理解项目用途、启动方式、入口文件、核心模块和继续阅读路径。",
        checklist=[
            "识别项目用途",
            "识别启动或主要入口",
            "识别依赖文件",
            "识别配置线索",
            "提供后续阅读路径",
            "列出无法判断的问题",
        ],
        quality_weights={
            "structure_completeness": 0.24,
            "evidence_coverage": 0.20,
            "codebase_coverage": 0.24,
            "risk_transparency": 0.10,
            "question_resolution": 0.08,
            "recommendation_confidence": 0.14,
        },
        verifier_checks=["has_entrypoint", "has_dependency_clues", "has_reading_path"],
        report_sections=["新人接手路径", "30 分钟阅读路线"],
        required_evidence_types=["source", "codebase", "readme"],
    ),
    # 面向架构评审，侧重模块边界、主流程、外部依赖和扩展点。
    "architecture_understanding": ResearchProfile(
        key="architecture_understanding",
        label="架构理解",
        description="梳理模块关系、数据流、边界、外部依赖和扩展点。",
        checklist=[
            "识别模块或目录边界",
            "识别主要入口和主流程线索",
            "识别外部依赖或集成点",
            "识别结构线索",
            "说明扩展点和耦合风险",
        ],
        quality_weights={
            "structure_completeness": 0.25,
            "evidence_coverage": 0.25,
            "codebase_coverage": 0.25,
            "risk_transparency": 0.10,
            "question_resolution": 0.05,
            "recommendation_confidence": 0.10,
        },
        verifier_checks=["has_module_boundaries", "has_entrypoint", "has_architecture_clues"],
        report_sections=["模块边界", "主流程与数据流", "扩展点"],
        required_evidence_types=["codebase", "dependency", "entrypoint"],
    ),
    # 面向二次开发评估，提高证据、风险和问题关闭率的权重。
    "extension_evaluation": ResearchProfile(
        key="extension_evaluation",
        label="二开评估",
        description="判断维护成本、改造风险、测试与配置复杂度。",
        checklist=[
            "识别测试线索",
            "识别配置复杂度",
            "识别依赖和框架版本",
            "列出改造风险和缓解建议",
            "给出证据化二开判断",
        ],
        quality_weights={
            "structure_completeness": 0.12,
            "evidence_coverage": 0.24,
            "codebase_coverage": 0.16,
            "risk_transparency": 0.24,
            "question_resolution": 0.14,
            "recommendation_confidence": 0.10,
        },
        verifier_checks=["has_test_clues", "has_risk_register", "has_mitigation"],
        report_sections=["二开可行性", "改造风险", "测试与配置复杂度"],
        required_evidence_types=["codebase", "test", "config"],
    ),
    # 面向教学拆解，要求形成章节顺序、关键代码讲解和练习任务。
    "teaching_breakdown": ResearchProfile(
        key="teaching_breakdown",
        label="教学拆解",
        description="拆成学习路径、章节、关键代码、难点和练习任务。",
        checklist=[
            "识别适合讲解的章节顺序",
            "列出关键代码文件",
            "说明学习难点和前置知识",
            "给出练习或验证任务",
            "标注教学材料风险",
        ],
        quality_weights={
            "structure_completeness": 0.25,
            "evidence_coverage": 0.20,
            "codebase_coverage": 0.15,
            "risk_transparency": 0.10,
            "question_resolution": 0.08,
            "recommendation_confidence": 0.22,
        },
        verifier_checks=["has_key_files", "has_learning_path", "has_exercises"],
        report_sections=["课程章节建议", "关键代码讲解顺序", "练习任务"],
        required_evidence_types=["codebase", "entrypoint", "test"],
    ),
    # 面向交付验收，侧重完整性、可启动性、文档缺口和待确认问题。
    "delivery_acceptance": ResearchProfile(
        key="delivery_acceptance",
        label="交付验收",
        description="检查完整性、可启动性、文档缺口和待确认项。",
        checklist=[
            "识别项目完整性线索",
            "识别启动或配置文档",
            "识别缺失文档或缺口",
            "列出待确认问题",
            "给出交付可接手结论",
        ],
        quality_weights={
            "structure_completeness": 0.14,
            "evidence_coverage": 0.24,
            "codebase_coverage": 0.12,
            "risk_transparency": 0.22,
            "question_resolution": 0.18,
            "recommendation_confidence": 0.10,
        },
        verifier_checks=["has_runbook_clues", "has_open_questions", "has_delivery_readiness_summary"],
        report_sections=["交付完整性", "可启动性", "验收问题清单"],
        required_evidence_types=["source", "readme", "config"],
    ),
}


def list_research_profiles() -> list[ResearchProfile]:
    """按注册顺序返回全部调研档位，供接口和评测列举使用。"""

    return list(PROFILE_REGISTRY.values())


def get_research_profile(key: str | None) -> ResearchProfile:
    """按 key 获取调研档位；缺失或未知 key 都回退到默认档位。"""

    return PROFILE_REGISTRY.get(key or DEFAULT_RESEARCH_PROFILE) or PROFILE_REGISTRY[DEFAULT_RESEARCH_PROFILE]


def research_profile_exists(key: str) -> bool:
    """判断项目提交的调研档位 key 是否已注册。"""

    return key in PROFILE_REGISTRY
