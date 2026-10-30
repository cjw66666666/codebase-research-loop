"""只读工具注册信息和运行工具调用审计接口。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisRun, Project, ToolCall
from app.db.session import get_session
from app.schemas.tooling import ToolCallRead, ToolRegistrationRead
from app.tools.gateway import list_default_tools

router = APIRouter(tags=["tools"])


@router.get("/tools", response_model=list[ToolRegistrationRead])
def list_tools() -> list:
    """返回内存中的默认只读工具注册表，不依赖数据库 seed。"""

    return list_default_tools()


@router.get("/projects/{project_id}/runs/{run_id}/tool-calls", response_model=list[ToolCallRead])
def list_run_tool_calls(
    project_id: str,
    run_id: str,
    session: Session = Depends(get_session),
) -> list[ToolCall]:
    """返回指定运行产生的工具调用记录。"""

    # 先校验项目，再校验 run 的项目归属，避免通过 run_id 跨项目读取审计记录。
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    run = session.get(AnalysisRun, run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # 调用账本按发生顺序返回，前端可据此还原 Agent 的工具使用轨迹。
    return list(
        session.scalars(
            select(ToolCall)
            .where(ToolCall.project_id == project.id, ToolCall.run_id == run.id)
            .order_by(ToolCall.created_at.asc(), ToolCall.id.asc())
        ).all()
    )
