"""报告生成、评审和对比相关的 API 数据模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReportCreate(BaseModel):
    """为指定运行生成报告；run_id 为空时由接口按项目选择最近一次运行。"""

    run_id: str | None = None


class ReportReviewCreate(BaseModel):
    """提交报告人工评审结论。"""

    # 评审只能落在三种明确结果上，避免报告状态出现自由文本值。
    decision: Literal["approved", "rejected", "needs_more"]
    # 可选评审说明，长度限制防止异常大的文本进入报告快照链路。
    comment: str | None = Field(default=None, max_length=4000)


class ReportSnapshotRead(BaseModel):
    """一次报告生成结果的不可变只读视图。"""

    # 报告快照主键及其所属项目和运行。
    id: str
    project_id: str
    run_id: str
    # 报告生命周期状态。
    status: str
    title: str
    # 已固化的完整 Markdown，后续重新渲染不会改写历史版本。
    markdown_content: str
    # 确定性验证器的校验结果，是人工评审和后续合并判断的依据。
    verifier_result_json: dict
    # 人工评审结论、备注和评审时间；未评审时为空。
    review_decision: str | None
    review_comment: str | None
    reviewed_at: datetime | None
    # 报告快照的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class ReportMarkdownRead(BaseModel):
    """报告 Markdown 原文的轻量响应。"""

    markdown: str


class ReportDiffRead(BaseModel):
    """两个报告版本之间的结构化差异。"""

    # base_report_id 是基准版本，target_report_id 是待比较版本。
    base_report_id: str
    target_report_id: str
    # 由报告服务计算出的差异内容，保存为可直接序列化的 JSON。
    diff: dict
