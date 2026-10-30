"""v4 runtime patrol schema（任务租约、工具账本和报告候选）

补充后台任务的队列与租约字段，并建立只读工具注册表、工具调用审计、LLM 报告
候选和评估运行表，为后台巡检及人工评审提供持久化基础。

Revision ID: 20260701_0009
Revises: 20260701_0008
Create Date: 2026-07-01 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260701_0009"
down_revision: Union[str, Sequence[str], None] = "20260701_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 队列、过期时间和心跳共同支持 worker 租约；next_run_at 用于延迟或重试。
    op.add_column(
        "run_jobs",
        sa.Column("queue_name", sa.String(length=80), nullable=False, server_default="default"),
    )
    op.add_column("run_jobs", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("run_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("run_jobs", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_run_jobs_queue_name"), "run_jobs", ["queue_name"], unique=False)
    op.create_index(op.f("ix_run_jobs_locked_until"), "run_jobs", ["locked_until"], unique=False)
    op.create_index(op.f("ix_run_jobs_next_run_at"), "run_jobs", ["next_run_at"], unique=False)

    # 工具注册表只描述能力、输入结构和权限级别，不保存具体执行实现。
    op.create_table(
        "tool_registrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("permission_level", sa.String(length=20), nullable=False),
        sa.Column("input_schema_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_registrations_name"), "tool_registrations", ["name"], unique=True)

    # 工具调用账本仅保存输入输出摘要，避免敏感内容进入长期审计记录。
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("turn_id", sa.String(length=36), nullable=True),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("permission_level", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("input_summary_json", sa.JSON(), nullable=False),
        sa.Column("output_summary_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"]),
        sa.ForeignKeyConstraint(["turn_id"], ["loop_turns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_calls_project_id"), "tool_calls", ["project_id"], unique=False)
    op.create_index(op.f("ix_tool_calls_run_id"), "tool_calls", ["run_id"], unique=False)
    op.create_index(op.f("ix_tool_calls_turn_id"), "tool_calls", ["turn_id"], unique=False)
    op.create_index(op.f("ix_tool_calls_tool_name"), "tool_calls", ["tool_name"], unique=False)
    op.create_index(op.f("ix_tool_calls_status"), "tool_calls", ["status"], unique=False)

    # LLM 报告候选先独立保存，只有通过验证后才关联正式 ReportSnapshot。
    op.create_table(
        "llm_report_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=True),
        sa.Column("call_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("validation_result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"]),
        sa.ForeignKeyConstraint(["report_id"], ["report_snapshots.id"]),
        sa.ForeignKeyConstraint(["call_id"], ["llm_calls.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_report_artifacts_project_id"), "llm_report_artifacts", ["project_id"], unique=False)
    op.create_index(op.f("ix_llm_report_artifacts_run_id"), "llm_report_artifacts", ["run_id"], unique=False)
    op.create_index(op.f("ix_llm_report_artifacts_report_id"), "llm_report_artifacts", ["report_id"], unique=False)
    op.create_index(op.f("ix_llm_report_artifacts_call_id"), "llm_report_artifacts", ["call_id"], unique=False)
    op.create_index(op.f("ix_llm_report_artifacts_status"), "llm_report_artifacts", ["status"], unique=False)

    # 评估运行保存总体指标和逐用例结果，供回归对比与历史追踪。
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("case_results_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evaluation_runs_status"), "evaluation_runs", ["status"], unique=False)


def downgrade() -> None:
    # 按新增对象的依赖关系逆序删除，最后移除 run_jobs 的租约扩展字段。
    op.drop_index(op.f("ix_evaluation_runs_status"), table_name="evaluation_runs")
    op.drop_table("evaluation_runs")

    op.drop_index(op.f("ix_llm_report_artifacts_status"), table_name="llm_report_artifacts")
    op.drop_index(op.f("ix_llm_report_artifacts_call_id"), table_name="llm_report_artifacts")
    op.drop_index(op.f("ix_llm_report_artifacts_report_id"), table_name="llm_report_artifacts")
    op.drop_index(op.f("ix_llm_report_artifacts_run_id"), table_name="llm_report_artifacts")
    op.drop_index(op.f("ix_llm_report_artifacts_project_id"), table_name="llm_report_artifacts")
    op.drop_table("llm_report_artifacts")

    op.drop_index(op.f("ix_tool_calls_status"), table_name="tool_calls")
    op.drop_index(op.f("ix_tool_calls_tool_name"), table_name="tool_calls")
    op.drop_index(op.f("ix_tool_calls_turn_id"), table_name="tool_calls")
    op.drop_index(op.f("ix_tool_calls_run_id"), table_name="tool_calls")
    op.drop_index(op.f("ix_tool_calls_project_id"), table_name="tool_calls")
    op.drop_table("tool_calls")

    op.drop_index(op.f("ix_tool_registrations_name"), table_name="tool_registrations")
    op.drop_table("tool_registrations")

    op.drop_index(op.f("ix_run_jobs_next_run_at"), table_name="run_jobs")
    op.drop_index(op.f("ix_run_jobs_locked_until"), table_name="run_jobs")
    op.drop_index(op.f("ix_run_jobs_queue_name"), table_name="run_jobs")
    op.drop_column("run_jobs", "next_run_at")
    op.drop_column("run_jobs", "heartbeat_at")
    op.drop_column("run_jobs", "locked_until")
    op.drop_column("run_jobs", "queue_name")
