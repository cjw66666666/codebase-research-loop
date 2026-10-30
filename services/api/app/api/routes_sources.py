"""项目输入源的创建与查询接口。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import SourceValidationError, validate_source_input
from app.db.models import Project, Source
from app.db.session import get_session
from app.schemas.project import SourceCreate, SourceRead
from app.services.audit import record_event

router = APIRouter(prefix="/projects/{project_id}/sources", tags=["sources"])


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
def create_source(
    project_id: str,
    payload: SourceCreate,
    session: Session = Depends(get_session),
) -> Source:
    """校验并登记一个输入源，同时写入创建审计事件。"""

    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    try:
        # 在落库前统一规范化地址并提取来源元数据，非法输入直接返回 400。
        validated = validate_source_input(payload.source_type, payload.uri)
    except SourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    source = Source(
        project_id=project.id,
        source_type=payload.source_type,
        uri=payload.uri,
        normalized_uri=validated.normalized_uri,
        metadata_json=validated.metadata,
    )
    session.add(source)
    # flush 取得 source.id 后，审计事件的 payload 才能引用稳定主键。
    session.flush()
    record_event(
        session,
        event_type="source.created",
        message="Source created",
        project_id=project.id,
        payload={
            "source_id": source.id,
            "source_type": source.source_type,
            "normalized_uri": source.normalized_uri,
        },
    )
    session.commit()
    session.refresh(source)
    return source


@router.get("", response_model=list[SourceRead])
def list_sources(project_id: str, session: Session = Depends(get_session)) -> list[Source]:
    """按创建时间正序返回项目输入源，便于展示采集先后关系。"""

    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    statement = (
        select(Source)
        .where(Source.project_id == project.id)
        .order_by(Source.created_at.asc(), Source.id.asc())
    )
    return list(session.scalars(statement).all())
