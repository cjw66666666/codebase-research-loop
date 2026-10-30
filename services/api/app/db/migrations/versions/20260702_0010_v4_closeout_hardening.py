"""v4 closeout hardening（运行事件序号约束）

在并发写入前，把已有 run_events 按运行分组重新编号，再建立
``(run_id, sequence)`` 唯一约束，保证前端恢复事件流时游标稳定且唯一。

Revision ID: 20260702_0010
Revises: 20260701_0009
Create Date: 2026-07-02 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "20260702_0010"
down_revision: Union[str, Sequence[str], None] = "20260701_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def normalize_run_event_sequences() -> None:
    """按原时间顺序为每个运行重新分配从 1 开始的连续序号。"""

    connection = op.get_bind()
    # created_at 和 id 作为同时间戳下的稳定排序依据，降低重排结果漂移。
    rows = connection.execute(
        text(
            """
            SELECT id, run_id
            FROM run_events
            ORDER BY run_id ASC, sequence ASC, created_at ASC, id ASC
            """
        )
    ).mappings()

    current_run_id: str | None = None
    next_sequence = 0
    for row in rows:
        # 排序已保证同一 run 的记录连续；切换 run_id 时重新从 1 计数。
        if row["run_id"] != current_run_id:
            current_run_id = row["run_id"]
            next_sequence = 1
        else:
            next_sequence += 1

        connection.execute(
            text("UPDATE run_events SET sequence = :sequence WHERE id = :id"),
            {"sequence": next_sequence, "id": row["id"]},
        )


def upgrade() -> None:
    # 必须先修复重复序号，否则创建唯一约束会因历史数据冲突而失败。
    normalize_run_event_sequences()
    with op.batch_alter_table("run_events") as batch_op:
        batch_op.create_unique_constraint(
            "uq_run_events_run_sequence",
            ["run_id", "sequence"],
        )


def downgrade() -> None:
    # 降级只移除唯一约束；已重新分配的序列表述仍然有效，无需不可靠地还原旧值。
    with op.batch_alter_table("run_events") as batch_op:
        batch_op.drop_constraint(
            "uq_run_events_run_sequence",
            type_="unique",
        )
