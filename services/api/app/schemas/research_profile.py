"""调研档位的对外只读模型。"""

from pydantic import BaseModel


class ResearchProfileRead(BaseModel):
    """描述一种调研目标对应的检查清单、评分权重和报告结构。"""

    # 稳定标识，用于项目创建和运行恢复；label 仅用于界面展示。
    key: str
    label: str
    description: str
    # 分析过程中需要逐项回答的调研任务。
    checklist: list[str]
    # 质量评分所采用的维度权重，正常配置下各维度权重之和为 1。
    quality_weights: dict[str, float]
    # 该档位要求验证器执行的确定性检查项。
    verifier_checks: list[str]
    # 报告需要包含的档位专属章节。
    report_sections: list[str]
    # 形成有效结论前必须出现的证据类型。
    required_evidence_types: list[str]
