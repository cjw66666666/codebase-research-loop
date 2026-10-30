"""只读工具注册信息和工具调用审计记录的数据模型。"""

from datetime import datetime

from pydantic import BaseModel


class ToolRegistrationRead(BaseModel):
    """工具注册表中的一项工具能力。"""

    # 工具主键和展示信息。
    id: str
    name: str
    description: str
    # 权限级别决定工具是否允许在当前运行策略下执行。
    permission_level: str
    # 工具的输入参数定义，以及对 API 调用方是否可见的开关。
    input_schema_json: dict
    enabled: bool
    # 注册记录的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class ToolCallRead(BaseModel):
    """一次工具调用的审计记录。"""

    # 调用主键及可选的上下文关联，部分工具调用可能不属于具体运行。
    id: str
    project_id: str | None
    run_id: str | None
    turn_id: str | None
    # 被调用工具及其权限级别，便于审计越权风险。
    tool_name: str
    permission_level: str
    # 调用状态、输入输出摘要和失败原因。
    status: str
    input_summary_json: dict
    output_summary_json: dict
    error_message: str | None
    # 调用耗时（毫秒），以及记录的创建和最后更新时间。
    latency_ms: int | None
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}
