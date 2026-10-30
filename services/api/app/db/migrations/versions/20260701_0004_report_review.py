"""report review schema（报告快照与人工评审）

报告生成后保存完整 Markdown、验证器结果和评审字段，使历史报告不依赖后续
重新渲染，也让批准、驳回和补充材料成为可追踪事实。

Revision ID: 20260701_0004
Revises: 20260701_0003
Create Date: 2026-07-01 00:04:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260701_0004"
down_revision: Union[str, Sequence[str], None] = "20260701_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # markdown_content 保存生成时的完整快照；review_* 字段记录人工裁决。
    op.create_table(
        "report_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("markdown_content", sa.Text(), nullable=False),
        sa.Column("verifier_result_json", sa.JSON(), nullable=False),
        sa.Column("review_decision", sa.String(length=40), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_report_snapshots_project_id"), "report_snapshots", ["project_id"], unique=False)
    op.create_index(op.f("ix_report_snapshots_run_id"), "report_snapshots", ["run_id"], unique=False)
    op.create_index(op.f("ix_report_snapshots_status"), "report_snapshots", ["status"], unique=False)


def downgrade() -> None:
    # 报告快照依赖项目和运行，降级时直接移除整张报告表及其索引。
    op.drop_index(op.f("ix_report_snapshots_status"), table_name="report_snapshots")
    op.drop_index(op.f("ix_report_snapshots_run_id"), table_name="report_snapshots")
    op.drop_index(op.f("ix_report_snapshots_project_id"), table_name="report_snapshots")
    op.drop_table("report_snapshots")
