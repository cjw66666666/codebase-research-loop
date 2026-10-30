"""项目审计事件时间线查询接口。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Project
from app.db.session import get_session
from app.schemas.project import AuditEventRead

router = APIRouter(prefix="/projects/{project_id}/events", tags=["events"])


@router.get("", response_model=list[AuditEventRead])
def list_project_events(project_id: str, session: Session = Depends(get_session)) -> list[AuditEvent]:
    """按项目内序号返回审计事件时间线。"""

    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    statement = (
        select(AuditEvent)
        .where(AuditEvent.project_id == project.id)
        # sequence 是业务顺序；时间戳和 id 只在历史异常数据中作为兜底。
        .order_by(AuditEvent.sequence.asc(), AuditEvent.created_at.asc(), AuditEvent.id.asc())
    )
    return list(session.scalars(statement).all())
