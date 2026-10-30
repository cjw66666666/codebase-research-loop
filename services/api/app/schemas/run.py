"""Loop 运行、过程产物、后台任务和事件流的 API 数据模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class AnalysisRunRead(BaseModel):
    """一次 Loop 分析运行的只读状态快照。"""

    # 运行主键及其所属项目。
    id: str
    project_id: str
    # 运行生命周期状态，例如 running、completed 或 paused_for_input。
    status: str
    # 当前轮次和运行允许的最大轮数。
    current_turn: int
    max_turns: int
    # LangGraph checkpoint 线程标识；恢复和继续执行依赖该关联。
    thread_id: str | None = None
    # sync 表示请求内执行，background 表示由后台 worker 执行。
    execution_mode: str = "sync"
    # 最近一次成功落库的检查点，用于运行恢复。
    last_checkpoint_id: str | None = None
    # 从暂停状态恢复的次数，用于限制异常重复恢复。
    resume_count: int = 0
    # 运行停止或暂停的业务原因；仍在执行时可为空。
    stop_reason: str | None
    # 运行开始、完成以及记录创建和更新的时间。
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class LoopTurnRead(BaseModel):
    """Loop 单轮节点的执行记录。"""

    # 轮次记录主键及其所属运行和项目。
    id: str
    run_id: str
    project_id: str
    # 轮次在单个 run 内递增，用于时间线排序和问题排查。
    turn_index: int
    # 执行节点、采取的动作和观察结果。
    node_name: str
    action: str
    observation: str
    # 当前节点状态及节点级补充信息。
    status: str
    metadata_json: dict
    # 轮次记录创建时间。
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class EvidenceItemRead(BaseModel):
    """可追溯的事实证据，后续发现和风险通过 ID 引用它。"""

    # 证据主键及其所属项目和运行。
    id: str
    project_id: str
    run_id: str
    # 部分运行级证据不对应单一输入源，因此 source_id 允许为空。
    source_id: str | None
    # 证据标题、摘要和证据类别。
    title: str
    summary: str
    evidence_type: str
    # 文件路径、URL 或 commit 等可复核定位信息。
    reference: str | None
    # 证据可信度和扩展元数据。
    confidence: int
    metadata_json: dict
    # 证据记录创建时间。
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class FindingRead(BaseModel):
    """基于证据形成的分析发现。"""

    # 发现主键及其所属项目和运行。
    id: str
    project_id: str
    run_id: str
    # 发现内容和分类信息。
    title: str
    summary: str
    category: str
    # 业务影响级别和判断可信度。
    impact_level: str
    confidence: int
    # 引用 EvidenceItem.id 的列表，质量评分据此计算证据覆盖度。
    evidence_refs_json: list
    metadata_json: dict
    # 发现记录创建时间。
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class RiskRead(BaseModel):
    """风险登记项，包括严重程度和可执行的缓解措施。"""

    # 风险主键及其所属项目和运行。
    id: str
    project_id: str
    run_id: str
    # 风险摘要、严重级别和缓解方案。
    title: str
    summary: str
    severity: str
    mitigation: str
    # 支撑风险判断的证据引用及扩展元数据。
    evidence_refs_json: list
    metadata_json: dict
    # 风险记录创建时间。
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class QuestionRead(BaseModel):
    """分析过程中需要用户补充信息或作出决策的问题。"""

    # 问题主键及其所属项目和运行。
    id: str
    project_id: str
    run_id: str
    # 向用户展示的问题、提问原因和缺失信息的影响。
    prompt: str
    reason: str
    impact: str
    # 问题状态；high 影响的 open 问题可能阻断运行。
    status: str
    # 用户回答，状态转为 answered 后可进入下一轮上下文。
    answer_text: str | None
    metadata_json: dict
    # 问题记录创建时间。
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class RecommendationRead(BaseModel):
    """调研结论和后续行动建议。"""

    # 建议主键及其所属项目和运行。
    id: str
    project_id: str
    run_id: str
    # 建议摘要和形成该建议的论证。
    summary: str
    rationale: str
    # 建议可信度以及可直接执行或继续调研的下一步。
    confidence: int
    next_steps_json: list
    metadata_json: dict
    # 建议记录创建时间。
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class QualityScoreRead(BaseModel):
    """一轮 Analysis Quality Rubric 的评分结果。"""

    # 评分主键及其所属项目和运行。
    id: str
    project_id: str
    run_id: str
    # 产生本次评分的 Loop 轮次；历史数据可能没有该关联。
    turn_id: str | None
    # 六个维度均为 0-100 分，overall_score 按调研档位权重加权得到。
    overall_score: int
    structure_completeness: int
    evidence_coverage: int
    codebase_coverage: int
    risk_transparency: int
    question_resolution: int
    recommendation_confidence: int
    # 与同项目上一次总分的差值；首次评分时等于当前总分。
    score_delta: int
    # 低于阈值维度的原因解释和下一轮改进动作。
    reasons_json: list
    next_actions_json: list
    metadata_json: dict
    # 评分记录创建时间。
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class AnalysisPackageRead(BaseModel):
    """一次运行的完整分析包，用于报告生成、评审和前端展示。"""

    # 运行元数据及过程记录。
    run: AnalysisRunRead
    turns: list[LoopTurnRead]
    # 证据和基于证据形成的发现、风险、问题与建议。
    evidence_items: list[EvidenceItemRead]
    findings: list[FindingRead]
    risks: list[RiskRead]
    questions: list[QuestionRead]
    recommendations: list[RecommendationRead]
    # 各轮质量评分，供趋势展示和停止决策追踪。
    quality_scores: list[QualityScoreRead]


class QuestionAnswerCreate(BaseModel):
    """用户回答阻塞问题的请求体。"""

    # 回答不能为空，提交后接口会恢复或继续对应运行。
    answer_text: str = Field(min_length=1)


class RunJobRead(BaseModel):
    """后台运行任务的排队状态和 worker 租约信息。"""

    # 任务主键及其所属项目和运行。
    id: str
    project_id: str
    run_id: str
    # job_type 决定 worker 执行 start、resume 还是 retry 路径。
    job_type: str
    status: str
    # 已尝试次数和最大尝试次数，用于控制租约过期后的重试。
    attempt_count: int
    max_attempts: int
    # 队列名称，用于区分不同 worker 的领取范围。
    queue_name: str = "default"
    # 以下字段共同构成租约：领取者、领取时间、过期时间和心跳时间。
    locked_by: str | None = None
    locked_at: datetime | None = None
    locked_until: datetime | None = None
    heartbeat_at: datetime | None = None
    # 最早可执行时间，以及延迟或重试后的计划执行时间。
    available_at: datetime
    next_run_at: datetime | None = None
    # 最近一次失败原因和任务级结构化参数。
    last_error: str | None
    payload_json: dict
    # 任务记录的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class RunEventRead(BaseModel):
    """运行事件流中的单条 durable 事件。"""

    # 事件主键及其所属项目和运行。
    id: str
    project_id: str
    run_id: str
    # 事件类型和 run 内单调递增序号。
    event_type: str
    sequence: int
    # 事件结构化载荷及发生时间。
    payload_json: dict
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class RunEnqueueRead(BaseModel):
    """创建或重试运行后的入队响应。"""

    # 返回运行当前状态及对应的后台任务，便于客户端立即跟踪。
    run: AnalysisRunRead
    job: RunJobRead
