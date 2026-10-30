"""项目输入资料采集与库存查询接口。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import Project
from app.db.session import get_session
from app.schemas.inventory import ProjectInventoryRead
from app.services.collection import collect_project_sources, list_inventory

router = APIRouter(prefix="/projects/{project_id}", tags=["inventory"])


@router.post("/collect", response_model=ProjectInventoryRead)
def collect_project(
    project_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """采集项目当前待处理的输入源，并返回最新库存快照。"""

    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    inventory = collect_project_sources(session, project, settings)
    # 采集服务可能写入多个源快照和代码库地图，由路由统一提交整个批次。
    session.commit()
    return inventory


@router.get("/inventory", response_model=ProjectInventoryRead)
def get_inventory(project_id: str, session: Session = Depends(get_session)) -> dict:
    """只读取项目已有的来源快照和代码库地图，不触发重新采集。"""

    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return list_inventory(session, project)
