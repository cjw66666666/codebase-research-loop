"""项目、输入源和审计事件的 API 数据模型。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.research.profiles import DEFAULT_RESEARCH_PROFILE


class ProjectCreate(BaseModel):
    """创建分析项目时提交的参数。"""

    # 项目名用于列表展示，topic 描述需要调研的业务或技术主题。
    name: str = Field(min_length=1, max_length=160)
    topic: str = Field(min_length=1)
    # 可选的分析目标；缺失时运行流程可能暂停并向用户追问。
    analysis_goal: str | None = None
    # 调研档位必须是研究档位注册表中的有效 key。
    research_profile: str = Field(default=DEFAULT_RESEARCH_PROFILE, min_length=1, max_length=80)
    # 限制 Loop 最多执行的轮数，避免分析失去停止边界。
    max_turns: int = Field(default=6, ge=1, le=20)


class ProjectRead(BaseModel):
    """项目详情的只读响应。"""

    # 项目主键、展示信息和分析目标。
    id: str
    name: str
    topic: str
    analysis_goal: str | None
    # 项目生命周期状态以及创建时选定的调研策略。
    status: str
    research_profile: str
    max_turns: int
    # 项目记录的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class SourceCreate(BaseModel):
    """向项目添加单个输入源时提交的参数。"""

    # source_type 决定采集器采用哪条解析路径，uri 保留用户输入。
    source_type: str = Field(min_length=1, max_length=40)
    uri: str = Field(min_length=1)


class SourceRead(BaseModel):
    """输入源的只读响应。"""

    # 输入源主键及其所属项目。
    id: str
    project_id: str
    # source_type 和 uri 保留用户提交的原始来源信息。
    source_type: str
    uri: str
    # normalized_uri 是用于去重和实际采集的稳定地址。
    normalized_uri: str
    # 当前采集状态及采集器附加的信息。
    status: str
    metadata_json: dict
    # 输入源记录的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class AuditEventRead(BaseModel):
    """项目审计时间线中的单条事件。"""

    # 事件主键及其所属项目；系统级事件可能没有 project_id。
    id: str
    project_id: str | None
    # sequence 在单个项目内单调递增，前端可据此增量读取事件。
    sequence: int
    # 事件类型、可读消息和触发者。
    event_type: str
    message: str
    actor_id: str
    # 事件的结构化补充信息以及发生时间。
    payload_json: dict
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}
