"""项目报告的生成、查询、导出、版本对比和人工评审接口。"""

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.models import Project, ReportSnapshot
from app.db.session import get_session
from app.reports.diff import build_report_package_snapshot, diff_report_snapshots
from app.reports.pdf import render_markdown_pdf
from app.schemas.report import (
    ReportCreate,
    ReportDiffRead,
    ReportMarkdownRead,
    ReportReviewCreate,
    ReportSnapshotRead,
)
from app.services.reports import (
    create_intelligent_report_snapshot,
    create_report_snapshot,
    get_latest_report,
    review_report_snapshot,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])


@router.post("/reports", response_model=ReportSnapshotRead, status_code=status.HTTP_201_CREATED)
def create_report(
    project_id: str,
    payload: ReportCreate | None = Body(default=None),
    session: Session = Depends(get_session),
) -> ReportSnapshot:
    """基于已结束运行生成确定性报告快照。"""

    project = get_project_or_404(session, project_id)
    try:
        report = create_report_snapshot(session, project, run_id=payload.run_id if payload else None)
    except LookupError as exc:
        # 目标运行或历史数据不存在属于资源缺失。
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # 运行尚未结束、不可评审等业务状态冲突返回 409。
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(report)
    return report


@router.post("/reports/intelligent", response_model=ReportSnapshotRead, status_code=status.HTTP_201_CREATED)
def create_intelligent_report(
    project_id: str,
    payload: ReportCreate | None = Body(default=None),
    session: Session = Depends(get_session),
) -> ReportSnapshot:
    """生成确定性报告，并尝试追加受证据约束的 LLM 解读。"""

    project = get_project_or_404(session, project_id)
    try:
        report = create_intelligent_report_snapshot(session, project, run_id=payload.run_id if payload else None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(report)
    return report


@router.get("/reports/latest", response_model=ReportSnapshotRead)
def get_latest_project_report(project_id: str, session: Session = Depends(get_session)) -> ReportSnapshot:
    """返回项目最近生成的报告快照。"""

    # 该静态路径声明在 /reports/{report_id} 之前，避免 latest 被当作报告 ID。
    project = get_project_or_404(session, project_id)
    report = get_latest_report(session, project)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/reports/{report_id}", response_model=ReportSnapshotRead)
def get_report(project_id: str, report_id: str, session: Session = Depends(get_session)) -> ReportSnapshot:
    """返回指定项目的单个报告快照。"""

    return get_report_or_404(session, project_id, report_id)


@router.get("/reports/{report_id}/markdown", response_model=ReportMarkdownRead)
def get_report_markdown(project_id: str, report_id: str, session: Session = Depends(get_session)) -> dict[str, str]:
    """返回报告已固化的 Markdown 原文。"""

    report = get_report_or_404(session, project_id, report_id)
    return {"markdown": report.markdown_content}


@router.get("/reports/{report_id}/export.pdf")
def export_report_pdf(project_id: str, report_id: str, session: Session = Depends(get_session)) -> Response:
    """把报告 Markdown 临时渲染为 PDF 下载响应。"""

    report = get_report_or_404(session, project_id, report_id)
    pdf_content = render_markdown_pdf(title=report.title, markdown=report.markdown_content)
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.id}.pdf"'},
    )


@router.get("/reports/{report_id}/export.md")
def export_report_markdown(project_id: str, report_id: str, session: Session = Depends(get_session)) -> Response:
    """以 UTF-8 Markdown 附件形式导出报告。"""

    report = get_report_or_404(session, project_id, report_id)
    return Response(
        content=report.markdown_content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report.id}.md"'},
    )


@router.get("/reports/{report_id}/diff", response_model=ReportDiffRead)
def get_report_diff(
    project_id: str,
    report_id: str,
    base_report_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """比较同一项目的两个报告版本及其对应分析包。"""

    get_project_or_404(session, project_id)
    target_report = get_report_or_404(session, project_id, report_id)
    base_report = get_report_or_404(session, project_id, base_report_id)
    # 按报告创建时间截断 run 产物，避免评审反馈等后写入数据污染历史版本 diff。
    base_package = build_report_package_snapshot(session, base_report)
    target_package = build_report_package_snapshot(session, target_report)
    return {
        "base_report_id": base_report.id,
        "target_report_id": target_report.id,
        "diff": diff_report_snapshots(base_package, target_package),
    }


@router.post("/reports/{report_id}/review", response_model=ReportSnapshotRead)
def review_report(
    project_id: str,
    report_id: str,
    payload: ReportReviewCreate,
    session: Session = Depends(get_session),
) -> ReportSnapshot:
    """写入人工评审结论，并持久化报告状态。"""

    project = get_project_or_404(session, project_id)
    report = get_report_or_404(session, project_id, report_id)
    try:
        # 评审服务负责状态转换、备注规范化和后续问题联动。
        review_report_snapshot(
            session,
            project,
            report,
            decision=payload.decision,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(report)
    return report


def get_project_or_404(session: Session, project_id: str) -> Project:
    """读取项目，缺失时统一转换为 HTTP 404。"""

    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_report_or_404(session: Session, project_id: str, report_id: str) -> ReportSnapshot:
    """读取报告并校验项目归属，防止跨项目访问。"""

    report = session.get(ReportSnapshot, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
