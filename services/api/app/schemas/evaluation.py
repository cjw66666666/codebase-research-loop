"""Evaluation Harness 的 API 响应模型。"""

from datetime import datetime

from pydantic import BaseModel


class EvaluationRunRead(BaseModel):
    """一次回归评估执行的只读快照。"""

    # 评估运行主键，用于查询单次执行结果。
    id: str
    # 执行状态，当前取值为 running、succeeded 或 failed。
    status: str
    # 汇总指标和逐用例明细分开保存，便于列表展示与问题定位。
    summary_json: dict
    case_results_json: list
    # 执行开始和结束时间；运行中尚未结束时 completed_at 为空。
    started_at: datetime
    completed_at: datetime | None
    # 记录快照本身的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}
