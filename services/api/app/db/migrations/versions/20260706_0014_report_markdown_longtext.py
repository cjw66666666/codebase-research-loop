"""report markdown longtext（扩展报告正文容量）

MySQL 的普通 TEXT 最大约 64 KiB，完整项目调研报告可能超过该限制。本迁移将
``report_snapshots.markdown_content`` 扩展为 LONGTEXT。

Revision ID: 20260706_0014
Revises: 20260702_0013
Create Date: 2026-07-06 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "20260706_0014"
down_revision: Union[str, Sequence[str], None] = "20260702_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table 让 SQLite 等需要重建表的数据库也能执行同一迁移。
    with op.batch_alter_table("report_snapshots") as batch_op:
        batch_op.alter_column(
            "markdown_content",
            existing_type=sa.Text(),
            type_=mysql.LONGTEXT(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # 回退到 TEXT 可能因已有报告过长而失败；执行前需确认最大 Markdown 长度。
    with op.batch_alter_table("report_snapshots") as batch_op:
        batch_op.alter_column(
            "markdown_content",
            existing_type=mysql.LONGTEXT(),
            type_=sa.Text(),
            existing_nullable=False,
        )
