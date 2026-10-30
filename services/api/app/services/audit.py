"""项目审计事件的写入与序号分配。

审计事件使用项目内单调递增的 ``sequence`` 组成可增量读取的时间线。并发写入
可能算出相同序号，因此这里通过数据库唯一约束检测冲突，并在嵌套事务中重试。
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AuditEvent

# 并发撞号时最多重新分配五次，避免持续冲突导致请求无限等待。
AUDIT_EVENT_SEQUENCE_RETRIES = 5


def record_event(
    session: Session,
    *,
    event_type: str,
    message: str,
    project_id: str | None = None,
    payload: dict | None = None,
    actor_id: str = "local-user",
) -> AuditEvent:
    """写入一条审计事件，并返回已经 flush 的 ORM 实例。

    该函数不主动提交外层事务，事件会与调用方的业务修改一起提交或回滚。
    序号冲突会触发有限次重试；其他完整性约束错误会立即抛给调用方。
    """

    # 保留最后一次序号冲突，重试耗尽时作为根异常链返回，便于定位数据库问题。
    last_conflict: IntegrityError | None = None
    # 每次都重新读取当前最大序号，避免沿用已经发生并发冲突的旧值。
    for _ in range(AUDIT_EVENT_SEQUENCE_RETRIES):
        event = AuditEvent(
            project_id=project_id,
            sequence=next_project_event_sequence(session, project_id),
            event_type=event_type,
            message=message,
            actor_id=actor_id,
            # 没有附加载荷时使用空字典，保证 JSON 列始终得到可序列化值。
            payload_json=payload or {},
        )
        try:
            # 使用 savepoint 隔离本次插入：撞号时只回滚这条事件，不让整个外层事务失效。
            with session.begin_nested():
                session.add(event)
                session.flush()
            return event
        except IntegrityError as exc:
            # 失败实例仍可能留在 Session 的待处理状态，移出后才能用新序号重新插入。
            if event in session:
                session.expunge(event)
            # 外键缺失等非序号冲突不能靠重试解决，应保留原始数据库异常。
            if not is_audit_event_sequence_conflict(exc):
                raise
            last_conflict = exc

    # 重试次数耗尽说明并发争用持续存在或唯一约束配置异常，不返回可能重复的序号。
    raise RuntimeError("Failed to allocate a unique audit event sequence") from last_conflict


def is_audit_event_sequence_conflict(exc: IntegrityError) -> bool:
    """判断完整性错误是否来自项目内审计序号唯一约束。"""

    message = str(getattr(exc, "orig", exc)).lower()
    # MySQL 通常返回约束名；SQLite 等驱动可能只返回 UNIQUE 表名和列名。
    return "uq_audit_events_project_sequence" in message or (
        "unique" in message and "audit_events" in message and "sequence" in message
    )


def next_project_event_sequence(session: Session, project_id: str | None) -> int:
    """生成项目内可用的下一个审计序号。

    时间戳和 UUID 都不保证反映业务发生顺序，因此项目事件按该整数序号排序。
    这里只计算候选值，真正的唯一性仍由数据库约束和调用方重试保证。
    """

    # 无项目的系统级事件不参与项目时间线，统一使用 1；唯一约束不限制 NULL 组合。
    if project_id is None:
        return 1
    # 先 flush 调用方尚未写入的事件，确保最大序号查询能看到同一事务中的待插入记录。
    session.flush()
    # 查询当前项目最大序号；没有历史事件时从 1 开始。
    latest_sequence = session.scalar(
        select(func.max(AuditEvent.sequence)).where(AuditEvent.project_id == project_id)
    )
    return int(latest_sequence or 0) + 1
