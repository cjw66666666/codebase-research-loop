"""可复现的本地代码分析演示项目和演示运行辅助逻辑。"""

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


# 演示接口同步等待后台 run 完成，超时时间用于避免请求无限挂起。
DEMO_RUN_WAIT_SECONDS = 30.0
# 轮询间隔需要足够短以控制演示延迟，同时避免持续压满数据库。
DEMO_RUN_POLL_SECONDS = 0.5


def create_code_analysis_demo_project(session: Session, settings: Settings) -> Project:
    """创建一个可复现的本地代码分析演示项目。

    Demo 不伪造 Analysis Package，而是创建真实本地目录输入源，然后复用采集、
    Loop Runner 和报告快照链路。这样演示项目能暴露和普通项目一样的边界与证据。

    该函数完成演示链路的主体流程：

    1. 创建项目并写入第一条审计事件；
    2. 在 workspace 中生成固定的本地演示仓库；
    3. 通过正式输入源校验逻辑登记本地目录；
    4. 执行采集、入队并运行一个 job；
    5. 等待运行进入可评审状态并生成报告快照。

    为了让使用独立 Session 的 worker 能看到 queued job，函数会在入队前主动
    ``commit`` 一次，因此全流程不是单一原子事务。调用方仍负责最后的 ``commit``，
    用于持久化运行结束和报告快照产生的最终变更。若运行阶段失败，此前已提交的
    项目、输入源和采集结果会保留，调用方需要把这视为部分完成的演示数据。
    """

    # 项目先 flush 以获得数据库生成的 id，后续仓库路径和审计事件都依赖该 id。
    project = Project(
        name="Demo Code Analysis",
        topic="Demonstrate read-only codebase analysis with verifier-first report review.",
        analysis_goal="Evaluate whether this small service is ready to be used as a Codebase Research Loop demo.",
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

    # 演示仓库按项目 id 隔离，重复创建不同项目时不会互相覆盖。
    demo_repo = write_demo_repository(settings.workspace_root / project.id / "demo-repo")
    # 不绕过正式校验逻辑，确保 Demo 输入源与真实本地目录输入源的边界一致。
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

    # 采集会生成 SourceSnapshot/CodebaseMap，后续 LangGraph 只消费这些持久化事实。
    collect_project_sources(session, project, settings)
    # 先提交项目、输入源和采集结果，worker 使用独立 Session 才能看到并处理 job。
    run, _job = enqueue_run(session, project)
    session.commit()

    # 本地开发默认由当前进程消费一个 job；常驻 worker 也可能抢先领取该任务。
    run_one_job()
    # 因此不能只依赖 run_one_job 的返回值，需要轮询 AnalysisRun 的最终状态。
    wait_for_reviewable_run(session, run.id)

    # 报告快照基于真实运行产物生成，而不是在演示接口中直接拼装 Markdown。
    create_report_snapshot(session, project, run_id=run.id)
    # 返回前只 flush；最终 commit 仍由 API 路由统一控制。
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
        # rollback 会结束当前事务并清空 ORM 身份映射中的旧状态，使下一轮读取
        # 能看到 worker 在另一个 Session 中已经提交的状态变化。
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
    """写入固定的小型 Python 仓库，作为离线、可重复的演示输入。

    文件集合刻意保持很小，但覆盖 README、依赖声明、入口文件和测试文件，
    让代码扫描、证据提取和报告生成都能走真实路径。函数使用覆盖写而不是
    append，确保同一路径重复调用时内容完全一致。
    """

    repo_dir.mkdir(parents=True, exist_ok=True)
    # dict 中的键是相对仓库根目录的路径；写入前按父目录逐个创建目录。
    files = {
        "README.md": """# Demo Code Analysis Service

This tiny service exists so the Codebase Research Loop workbench can demonstrate
source collection, codebase mapping, evidence-backed findings, risk review and
Markdown report generation without relying on network access.
""",
        "pyproject.toml": """[project]
name = "demo-code-analysis-service"
version = "0.1.0"
description = "Small demo project for Codebase Research Loop analysis"
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
        # 支持 tests/test_app.py 这类嵌套路径，不要求调用方预先创建目录。
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return repo_dir
