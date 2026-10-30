"""fix llm profile temperature type（温度字段类型修正）

把 ``llm_profiles.temperature`` 从早期整数列改为浮点列。该迁移只调整列类型，
历史缩放值由紧接其后的 0008 迁移负责归一化。

Revision ID: 20260701_0007
Revises: 20260701_0006
Create Date: 2026-07-01 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260701_0007"
down_revision: Union[str, Sequence[str], None] = "20260701_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 目标形态是模型 API 直接使用的浮点值；已有整数缩放值由 0008 继续修正。
    op.alter_column(
        "llm_profiles",
        "temperature",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # 当前 0006 migration 已经以 Float 为目标形态，回退到 0006 时保持该形态即可。
    pass
