import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import validate_source_input
from app.db.models import AnalysisRun, Project, Source
from app.engine.runner import enqueue_run
from app.services.audit import record_event
from app.services.collection import collect_project_sources
from app.services.reports import REVIEWABLE_RUN_STATUSES, create_report_snapshot
from app.workers.run_worker import run_one_job


DEMO_RUN_WAIT_SECONDS = 30.0
DEMO_RUN_POLL_SECONDS = 0.5


def create_code_analysis_demo_project(session: Session, settings: Settings) -> Project:
    """创建一个可复现的本地代码分析演示项目。

    Demo 不伪造 Analysis Package，而是创建真实本地目录输入源，然后复用采集、
    Loop Runner 和报告快照链路。这样演示项目能暴露和普通项目一样的边界与证据。
    """

    project = Project(
        name="Demo Code Analysis",
        topic="Demonstrate read-only codebase analysis with verifier-first report review.",
        analysis_goal="Evaluate whether this small service is ready to be used as a Loop Engineering demo.",
        max_turns=6,
    )
    session.add(project)
    session.flush()
    record_event(
        session,
        event_type="project.created",
        message="Demo project created",
        project_id=project.id,
        payload={"name": project.name, "demo_type": "code_analysis"},
    )

    demo_repo = write_demo_repository(settings.workspace_root / project.id / "demo-repo")
    validated = validate_source_input("local_directory", str(demo_repo))
    source = Source(
        project_id=project.id,
        source_type="local_directory",
        uri=str(demo_repo),
        normalized_uri=validated.normalized_uri,
        metadata_json={**validated.metadata, "demo": "code_analysis"},
    )
    session.add(source)
    session.flush()
    record_event(
        session,
        event_type="source.created",
        message="Demo source created",
        project_id=project.id,
        payload={"source_id": source.id, "source_type": source.source_type},
    )

    collect_project_sources(session, project, settings)
    run, _job = enqueue_run(session, project)
    session.commit()
    run_one_job()
    wait_for_reviewable_run(session, run.id)
    create_report_snapshot(session, project, run_id=run.id)
    session.flush()
    return project


def wait_for_reviewable_run(
    session: Session,
    run_id: str,
    timeout_seconds: float = DEMO_RUN_WAIT_SECONDS,
) -> AnalysisRun:
    """等待一次运行进入可评审状态。

    任务可能由本请求自己处理，也可能先被常驻 worker 领取，因此不能假设
    `run_one_job()` 返回时运行已经结束。每轮先结束事务再读，避免在
    REPEATABLE READ 下反复读到同一个旧快照。
    """

    deadline = time.monotonic() + timeout_seconds
    while True:
        session.rollback()
        run = session.get(AnalysisRun, run_id)
        if run is not None and run.status in REVIEWABLE_RUN_STATUSES:
            return run
        if run is not None and run.status == "failed":
            raise RuntimeError(f"Demo run failed: {run.stop_reason}")
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Demo run did not finish within {timeout_seconds:.0f}s "
                f"(last status: {run.status if run else 'missing'})."
            )
        time.sleep(DEMO_RUN_POLL_SECONDS)


def write_demo_repository(repo_dir: Path) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "README.md": """# Demo Code Analysis Service

This tiny service exists so the Loop Engineering workbench can demonstrate
source collection, codebase mapping, evidence-backed findings, risk review and
Markdown report generation without relying on network access.
""",
        "pyproject.toml": """[project]
name = "demo-code-analysis-service"
version = "0.1.0"
description = "Small demo project for Loop Engineering analysis"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
        "app.py": '''def summarize_items(items: list[str]) -> dict[str, int]:
    """Return a simple count summary for demonstration inputs."""

    return {"total": len(items), "unique": len(set(items))}


if __name__ == "__main__":
    print(summarize_items(["source", "loop", "source"]))
''',
        "tests/test_app.py": """from app import summarize_items


def test_summarize_items_counts_total_and_unique_values():
    assert summarize_items(["source", "loop", "source"]) == {"total": 3, "unique": 2}
""",
    }
    for relative_path, content in files.items():
        path = repo_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return repo_dir
