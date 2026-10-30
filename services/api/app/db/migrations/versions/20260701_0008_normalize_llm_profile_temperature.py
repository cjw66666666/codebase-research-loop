"""normalize llm profile temperature values（归一化历史温度值）

0007 完成列类型转换后，把大于 2 的历史缩放值除以 100。有效温度上限为 2，
因此该条件可以区分旧的整数缩放表示和正常浮点值。

Revision ID: 20260701_0008
Revises: 20260701_0007
Create Date: 2026-07-01 17:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260701_0008"
down_revision: Union[str, Sequence[str], None] = "20260701_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 只处理超出 API 合法范围的值，避免把已经正常的 0.2 等温度再次缩小。
NORMALIZE_SCALED_TEMPERATURE_SQL = """
UPDATE llm_profiles
SET temperature = temperature / 100
WHERE temperature > 2
"""


def upgrade() -> None:
    # 幂等性依赖 temperature > 2 条件：重复执行不会再次修改已归一化的值。
    op.execute(NORMALIZE_SCALED_TEMPERATURE_SQL)


def downgrade() -> None:
    # 数据归一化不可安全反推：0.2 可能是原始值，也可能来自旧的 20 缩放值。
    pass
