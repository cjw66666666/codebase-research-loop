"""Evaluation Harness 的运行与历史查询接口。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EvaluationRun
from app.db.session import get_session
from app.evaluations.runner import run_evaluations
from app.schemas.evaluation import EvaluationRunRead

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("/run", response_model=EvaluationRunRead, status_code=status.HTTP_201_CREATED)
def run_evaluation_harness(session: Session = Depends(get_session)) -> EvaluationRun:
    """同步执行全部回归用例，并返回本次评估摘要。

    该接口不是后台任务入口：请求会等待全部 fixture 扫描、profile benchmark、
    质量评分、verifier 和报告章节检查完成。``run_evaluations`` 内部负责提交
    ``EvaluationRun``，因此这里直接把持久化后的评估结果返回给调用方。
    """

    return run_evaluations(session)


@router.get("/latest", response_model=EvaluationRunRead)
def get_latest_evaluation(session: Session = Depends(get_session)) -> EvaluationRun:
    """返回最近一次评估；没有历史记录时返回 404。

    只读取 ``EvaluationRun`` 本身，不重新执行评估。前端刷新页面时依赖该接口
    展示最近一次摘要，因此排序必须稳定，不能只依赖可能重复的创建时间。
    """

    # created_at 相同的情况下用 id 兜底排序，保证接口结果稳定。
    evaluation = session.scalar(
        select(EvaluationRun).order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
    )
    if evaluation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found")
    return evaluation
