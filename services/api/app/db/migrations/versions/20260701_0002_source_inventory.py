"""source inventory schema（输入快照与代码库地图）

把一次性采集结果固化为可审计快照，并保存代码目录、依赖、测试和入口等
确定性扫描线索。后续分析只能引用这些已落库的事实。

Revision ID: 20260701_0002
Revises: 20260630_0001
Create Date: 2026-07-01 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260701_0002"
down_revision: Union[str, Sequence[str], None] = "20260630_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 源快照保存可读摘要、外部内容路径、跳过项和采集错误。
    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content_excerpt", sa.Text(), nullable=True),
        sa.Column("content_path", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("skipped_items_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_source_snapshots_project_id"),
        "source_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_snapshots_source_id"),
        "source_snapshots",
        ["source_id"],
        unique=False,
    )
    # 代码库地图按输入源保存目录树和各类关键文件清单。
    op.create_table(
        "codebase_maps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("root_label", sa.Text(), nullable=False),
        sa.Column("tech_stack_json", sa.JSON(), nullable=False),
        sa.Column("dependency_files_json", sa.JSON(), nullable=False),
        sa.Column("config_files_json", sa.JSON(), nullable=False),
        sa.Column("test_files_json", sa.JSON(), nullable=False),
        sa.Column("entrypoint_files_json", sa.JSON(), nullable=False),
        sa.Column("readme_excerpt", sa.Text(), nullable=True),
        sa.Column("file_tree_json", sa.JSON(), nullable=False),
        sa.Column("skipped_items_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_codebase_maps_project_id"),
        "codebase_maps",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_codebase_maps_source_id"),
        "codebase_maps",
        ["source_id"],
        unique=False,
    )


def downgrade() -> None:
    # 先删除索引和引用 sources 的扫描结果，保持降级顺序可重复执行。
    op.drop_index(op.f("ix_codebase_maps_source_id"), table_name="codebase_maps")
    op.drop_index(op.f("ix_codebase_maps_project_id"), table_name="codebase_maps")
    op.drop_table("codebase_maps")
    op.drop_index(op.f("ix_source_snapshots_source_id"), table_name="source_snapshots")
    op.drop_index(op.f("ix_source_snapshots_project_id"), table_name="source_snapshots")
    op.drop_table("source_snapshots")
