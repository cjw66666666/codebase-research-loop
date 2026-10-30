"""Codebase Research Loop 的 SQLAlchemy ORM 模型。

本文件定义数据库存储模型，与 app/schemas 中的 API 请求/响应模型相互独立。
业务数据大致按以下顺序组织：

- 项目与输入资料：Project、Source*、CodebaseMap；
- 分析运行与 Loop 过程：AnalysisRun、LoopTurn；
- 分析产物：EvidenceItem、Finding、Risk、Question、Recommendation、ReportSnapshot；
- LLM、工具、评估和审计账本；
- 后台任务、运行事件和 LangGraph checkpoint。

JSON 字段用于保存结构可能扩展的补充信息；核心查询字段仍使用独立列和索引。
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db.base import Base

# MySQL 的 TEXT 容量不足时使用 LONGTEXT；其他数据库继续使用普通 Text。
LONG_TEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")


class UTCDateTime(TypeDecorator[datetime]):
    """数据库可能丢失时区信息，读写时统一按 UTC 归一化。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        """写入前统一转为 UTC；无时区值按 UTC 解释，避免依赖服务器本地时区。"""

        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        """读取后补齐或转换时区，保证业务层始终拿到带 UTC 时区的时间。"""

        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def new_id() -> str:
    """生成业务表使用的 UUID 字符串主键。"""

    return str(uuid4())


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(UTC)


def utc_now_second() -> datetime:
    """队列调度时间按整秒取整。

    MySQL 的 DATETIME 默认精度是秒，插入带微秒的值会四舍五入，可能被进位到未来，
    导致刚入队的任务在 `available_at <= now` 判断里被当成"还没到执行时间"。
    写入前先抹掉微秒，保证存进去的值永远不会晚于真实时刻。
    """

    return datetime.now(UTC).replace(microsecond=0)


class TimestampMixin:
    """为业务表提供统一的创建时间和最后更新时间。"""

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
    )


# ---------------------------------------------------------------------------
# 项目与输入资料
# ---------------------------------------------------------------------------


class Project(TimestampMixin, Base):
    """分析项目是 Loop Runtime 的主实体，后续 run、证据和报告都挂在项目下。"""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_goal: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    research_profile: Mapped[str] = mapped_column(String(80), nullable=False, default="quick_onboarding")
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=6)

    # 删除项目时级联清理从属数据；项目是这些记录的业务聚合根。
    sources: Mapped[list["Source"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    source_bundles: Mapped[list["SourceBundle"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    source_snapshots: Mapped[list["SourceSnapshot"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    codebase_maps: Mapped[list["CodebaseMap"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    report_snapshots: Mapped[list["ReportSnapshot"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class Source(TimestampMixin, Base):
    """输入源只记录元数据和规范化位置；读取、clone、扫描由采集服务统一完成。"""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    # normalized_uri 是去重和后续采集使用的稳定地址，uri 保留用户原始输入。
    normalized_uri: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    # 采集器附加的来源信息，例如分支、commit、本地路径或跳过原因。
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    project: Mapped[Project] = relationship(back_populates="sources")
    source_snapshots: Mapped[list["SourceSnapshot"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )
    codebase_maps: Mapped[list["CodebaseMap"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class SourceBundle(TimestampMixin, Base):
    """资料包把用户一次提交的多个输入固定下来，采集任务按条目状态处理它。"""

    __tablename__ = "source_bundles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    # 汇总一次提交的采集信息，不替代每个 item 自己的状态和错误。
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    project: Mapped[Project] = relationship(back_populates="source_bundles")
    items: Mapped[list["SourceBundleItem"]] = relationship(
        back_populates="bundle",
        cascade="all, delete-orphan",
        order_by="SourceBundleItem.created_at, SourceBundleItem.id",
    )


class SourceBundleItem(TimestampMixin, Base):
    """资料包条目保留原始输入、规范化结果和失败原因，避免无效输入丢失上下文。"""

    __tablename__ = "source_bundle_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bundle_id: Mapped[str] = mapped_column(
        ForeignKey("source_bundles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"),
        index=True,
    )
    input_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # raw_value 保留用户原始输入；normalized_uri 是解析后的可采集地址。
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_uri: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    # 失败条目仍保留，方便前端展示原因和用户修正输入。
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    bundle: Mapped[SourceBundle] = relationship(back_populates="items")
    source: Mapped[Source | None] = relationship()


class SourceSnapshot(TimestampMixin, Base):
    """输入源采集结果快照，保存可审计的只读事实摘要和跳过原因。"""

    __tablename__ = "source_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="collected")
    title: Mapped[str | None] = mapped_column(Text)
    content_excerpt: Mapped[str | None] = mapped_column(Text)
    # 大内容通常落盘，数据库只保存可检索摘要和内容路径。
    content_path: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # 记录被跳过的敏感文件、大文件或生成目录，保证采集结果可审计。
    skipped_items_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="source_snapshots")
    source: Mapped[Source] = relationship(back_populates="source_snapshots")


class CodebaseMap(TimestampMixin, Base):
    """代码库地图保存确定性扫描结果，后续 Loop 只能基于这些证据做分析。"""

    __tablename__ = "codebase_maps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    root_label: Mapped[str] = mapped_column(Text, nullable=False)
    # 以下字段共同构成 codebase_coverage 的确定性证据来源。
    tech_stack_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dependency_files_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    config_files_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    test_files_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    entrypoint_files_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    readme_excerpt: Mapped[str | None] = mapped_column(Text)
    # file_tree_json 保存供后续阅读路径和报告使用的目录快照。
    file_tree_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 扫描阶段跳过的路径及原因，避免“没找到”和“被策略排除”混为一谈。
    skipped_items_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    project: Mapped[Project] = relationship(back_populates="codebase_maps")
    source: Mapped[Source] = relationship(back_populates="codebase_maps")


# ---------------------------------------------------------------------------
# 分析运行与 Loop 过程
# ---------------------------------------------------------------------------


class AuditEvent(TimestampMixin, Base):
    """审计事件记录用户和系统关键动作，保证分析过程可追溯。"""

    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("project_id", "sequence", name="uq_audit_events_project_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    # sequence 与 project_id 组合唯一，支持按单调递增游标增量读取事件。
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(80), nullable=False, default="local-user")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    project: Mapped[Project | None] = relationship(back_populates="audit_events")


class AnalysisRun(TimestampMixin, Base):
    """一次 Loop 运行，是分析过程、产物和停止原因的聚合根。"""

    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="running")
    current_turn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    # thread_id 将业务 run 与 LangGraph checkpoint 线程关联起来。
    thread_id: Mapped[str | None] = mapped_column(String(120), index=True)
    # sync 表示请求内执行，background 表示由 run_jobs worker 异步执行。
    execution_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="sync")
    # 最近一次成功落库的 checkpoint；完整检查点仍保存在 graph_checkpoints。
    last_checkpoint_id: Mapped[str | None] = mapped_column(String(120))
    # 从 paused_for_input 恢复的次数，用于限制重复恢复和排查循环。
    resume_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 记录 failed、paused_for_input 或正常评审停止的业务原因。
    stop_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    project: Mapped[Project] = relationship(back_populates="analysis_runs")
    turns: Mapped[list["LoopTurn"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    risks: Mapped[list["Risk"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    quality_scores: Mapped[list["QualityScore"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    report_snapshots: Mapped[list["ReportSnapshot"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class LoopTurn(TimestampMixin, Base):
    """Loop 每个节点的执行记录，用于恢复、审计和解释为什么继续或停止。"""

    __tablename__ = "loop_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    # turn_index 在单个 run 内递增，用于前端时间线和人工排查。
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    node_name: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="completed")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=utc_now)
    # 记录决策、暂停来源、工具输出摘要等节点级补充信息。
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[AnalysisRun] = relationship(back_populates="turns")
    quality_scores: Mapped[list["QualityScore"]] = relationship(back_populates="turn")


class EvidenceItem(TimestampMixin, Base):
    """证据项保存可追溯事实，发现和风险只能引用证据而不是凭空判断。"""

    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    # 部分运行级证据没有直接对应的输入源，因此 source_id 允许为空。
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(80), nullable=False)
    # reference 保存文件路径、URL 或 commit 等可复核定位信息。
    reference: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[AnalysisRun] = relationship(back_populates="evidence_items")


class Finding(TimestampMixin, Base):
    """分析发现，必须尽量通过 evidence_refs_json 指向证据项。"""

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    impact_level: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=75)
    # 保存 EvidenceItem.id 列表，质量评分据此计算 evidence_coverage。
    evidence_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[AnalysisRun] = relationship(back_populates="findings")


class Risk(TimestampMixin, Base):
    """风险登记项记录严重级别、影响和缓解建议。"""

    __tablename__ = "risks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    # 没有缓解措施的风险会降低风险透明度和可评审性。
    mitigation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[AnalysisRun] = relationship(back_populates="risks")


class Question(TimestampMixin, Base):
    """高风险缺口通过问题暂停 Loop，等待用户回答后恢复。"""

    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # impact 为 high 的 open 问题会阻断 Loop 并触发 LangGraph interrupt。
    impact: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open")
    # answer_text 由用户填写；状态转为 answered 后可作为下一轮上下文。
    answer_text: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[AnalysisRun] = relationship(back_populates="questions")


class Recommendation(TimestampMixin, Base):
    """推荐结论和下一步建议，是 Analysis Package 的收束点。"""

    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    # 当前质量评分取所有建议中的最高 confidence 作为建议可信度。
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    next_steps_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[AnalysisRun] = relationship(back_populates="recommendations")


class QualityScore(TimestampMixin, Base):
    """Analysis Quality Rubric 每轮评分，驱动继续、暂停或停止决策。"""

    __tablename__ = "quality_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    # 关联产生这次评分的 verify_package 节点；历史数据允许为空。
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("loop_turns.id"), index=True)
    # 六个维度均为 0-100，overall_score 由调研档位的权重加权得到。
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    structure_completeness: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_coverage: Mapped[int] = mapped_column(Integer, nullable=False)
    codebase_coverage: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_transparency: Mapped[int] = mapped_column(Integer, nullable=False)
    question_resolution: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    # 与同项目上一次 overall_score 的差值；首次运行时等于当前总分。
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 低于阈值的维度解释和下一轮改进动作，供报告和前端直接展示。
    reasons_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    next_actions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    run: Mapped[AnalysisRun] = relationship(back_populates="quality_scores")
    turn: Mapped[LoopTurn | None] = relationship(back_populates="quality_scores")


# ---------------------------------------------------------------------------
# 报告、LLM 与工具产物
# ---------------------------------------------------------------------------


class ReportSnapshot(TimestampMixin, Base):
    """报告快照把一次 Analysis Package 的校验结果、Markdown 和人工评审结论固化下来。"""

    __tablename__ = "report_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # 报告一旦生成就保存完整 Markdown 快照，避免后续重渲染改变历史内容。
    markdown_content: Mapped[str] = mapped_column(LONG_TEXT, nullable=False)
    # 保存确定性 verifier 的结果，人工评审需要基于这份校验证据判断。
    verifier_result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    review_decision: Mapped[str | None] = mapped_column(String(40))
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    project: Mapped[Project] = relationship(back_populates="report_snapshots")
    run: Mapped[AnalysisRun] = relationship(back_populates="report_snapshots")


class LLMProfile(TimestampMixin, Base):
    """LLM 任务档位。API key 只通过环境变量名引用，不入库。"""

    __tablename__ = "llm_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # task_type 当前区分 analyzer、verifier 和 report 三类模型配置。
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    # 只保存环境变量名，避免密钥进入数据库或测试快照。
    api_key_env_name: Mapped[str | None] = mapped_column(String(120))
    api_key_required: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # 以分为单位限制单日预算；NULL 表示不额外限制。
    daily_budget_cents: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)


class LLMCall(TimestampMixin, Base):
    """每次 LLM 调用的可审计账本，不保存 API key。"""

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("report_snapshots.id"), index=True)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("llm_profiles.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    # 只保存 prompt 哈希，避免账本重复保存完整敏感文本。
    prompt_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    # 记录本次调用的输入引用、外部输出位置和 token 用量，便于审计和成本统计。
    input_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output_ref: Mapped[str | None] = mapped_column(Text)
    usage_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    error_message: Mapped[str | None] = mapped_column(Text)


class LLMAnalysisArtifact(TimestampMixin, Base):
    """LLM 输出的结构化产物。只有 accepted=True 的内容可合并进 Analysis Package。"""

    __tablename__ = "llm_analysis_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_calls.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # 只有通过结构、证据和业务校验的产物才允许合并进正式分析包。
    accepted: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)


class ToolRegistration(TimestampMixin, Base):
    """Tool Gateway 的只读工具登记表，只描述能力和权限级别，不承载执行逻辑。"""

    __tablename__ = "tool_registrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # L0 等权限级别由 Tool Gateway 在执行前校验，登记表本身不执行工具。
    permission_level: Mapped[str] = mapped_column(String(20), nullable=False, default="L0")
    # 工具输入参数的结构约定，供调用校验和前端展示使用。
    input_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Integer, nullable=False, default=True)


class ToolCall(TimestampMixin, Base):
    """工具调用审计账本，记录 run 相关上下文、输入摘要、输出摘要和错误信息。"""

    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("loop_turns.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    permission_level: Mapped[str] = mapped_column(String(20), nullable=False, default="L0")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    # 只保存输入输出摘要，完整敏感内容不进入审计账本。
    input_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class LLMReportArtifact(TimestampMixin, Base):
    """LLM 报告生成产物，保存候选内容和校验结果，供后续确定性流程裁决。"""

    __tablename__ = "llm_report_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("report_snapshots.id"), index=True)
    call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_calls.id"), index=True)
    # 候选报告需经过验证器裁决后才能关联到正式 ReportSnapshot。
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class EvaluationRun(TimestampMixin, Base):
    """Evaluation Harness 的运行记录，保存摘要和 case 结果。"""

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="running", index=True)
    # summary_json 保存总体指标，case_results_json 保存逐用例明细。
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    case_results_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


# ---------------------------------------------------------------------------
# 后台任务、事件流与 LangGraph checkpoint
# ---------------------------------------------------------------------------


class RunJob(TimestampMixin, Base):
    """后台运行任务，负责把 HTTP 请求和实际 LangGraph 执行解耦。"""

    __tablename__ = "run_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    # start、resume、retry 等类型决定 worker 采用哪条执行路径。
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    # attempt_count 与 max_attempts 控制租约过期后的自动重试上限。
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    queue_name: Mapped[str] = mapped_column(String(80), nullable=False, default="default", index=True)
    # 以下字段共同构成 worker 租约，防止多个 worker 同时处理同一个 job。
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now_second)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    # 保存 resume 输入、重试原因或报告评审反馈等任务级参数。
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class RunEvent(TimestampMixin, Base):
    """运行事件是前端订阅和恢复 UI 状态的 durable 事件流。"""

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_events_run_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    # run_id + sequence 唯一，前端按 sequence 游标恢复 SSE/轮询事件流。
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class GraphCheckpoint(TimestampMixin, Base):
    """LangGraph checkpoint tuple 的 MySQL 保存格式。

    一行代表某个 superstep 边界上的完整 Graph State 快照。业务事实仍以
    analysis_runs、loop_turns 和分析产物表为准，这里只服务于 Graph 恢复。
    """

    __tablename__ = "graph_checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # thread_id 对应 analysis_runs.thread_id；namespace 为子图和嵌套执行预留隔离。
    thread_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    # 指向上一个快照，用于检查点链回溯和时间旅行。
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(120))
    # channel_values 被拆到独立列，其余 checkpoint 字段保存在 checkpoint_json。
    checkpoint_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    channel_values_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class GraphCheckpointWrite(TimestampMixin, Base):
    """LangGraph pending writes，用于 interrupt/resume 恢复。

    一个 checkpoint 可以关联多条 writes；task_id + write_index 保证同一任务
    多个输出以及重复回调的幂等性。channel 既可能是 Graph State 字段，也可能是
    branch:to:*、__interrupt__、__no_writes__ 等控制信号。
    """

    __tablename__ = "graph_checkpoint_writes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(120), nullable=False)
    write_index: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(160), nullable=False)
    # 普通 JSON 值直接保存；Interrupt 等非 JSON 对象由 JsonPlusSerializer 编码。
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # 记录产生写入的任务路径，便于定位 interrupt 或失败发生在哪个节点。
    task_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
