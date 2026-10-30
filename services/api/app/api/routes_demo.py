"""可复现演示项目的创建接口。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import Project
from app.db.session import get_session
from app.schemas.project import ProjectRead
from app.services.demo import create_code_analysis_demo_project

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/projects/code-analysis", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_demo_project(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Project:
    """创建一个带示例输入、真实采集结果和报告快照的完整演示项目。

    此接口会同步执行采集和一次 Loop run，因此响应时间明显长于普通项目创建。
    服务层为了让独立 worker Session 看到 job，会在入队前先提交一次基础数据；
    因此整条链路不是单一原子事务。服务返回后，路由层再提交运行和报告快照的最终
    变更并 refresh 项目，以读出数据库生成或更新的字段。若运行阶段失败，基础项目
    和输入源可能已经持久化，但接口不会返回一个“完整可用”的演示项目。
    """

    project = create_code_analysis_demo_project(session, settings)
    # 服务内部已提交过基础数据；这里提交运行结束和报告快照产生的最终变更。
    session.commit()
    session.refresh(project)
    return project
