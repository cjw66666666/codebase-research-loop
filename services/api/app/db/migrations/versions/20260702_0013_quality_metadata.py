"""quality metadata（质量评分扩展字段）

为质量评分增加 JSON 元数据，用于保存调研档位、验证器和评分上下文等可扩展
信息，不把易变化的附加数据固化成大量独立列。

Revision ID: 20260702_0013
Revises: 20260702_0012
Create Date: 2026-07-02 20:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260702_0013"
down_revision: Union[str, Sequence[str], None] = "20260702_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先以可空列新增，回填历史行后再收紧为非空，兼容已有 quality_scores 数据。
    op.add_column("quality_scores", sa.Column("metadata_json", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE quality_scores SET metadata_json = '{}' WHERE metadata_json IS NULL"))
    with op.batch_alter_table("quality_scores") as batch_op:
        batch_op.alter_column("metadata_json", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    # 元数据包含无法映射回固定列的扩展信息，降级会直接丢弃该字段。
    with op.batch_alter_table("quality_scores") as batch_op:
        batch_op.drop_column("metadata_json")
