"""本地演示项目创建和演示运行链路的回归测试。"""

from pathlib import Path

from app.core.config import Settings, get_settings
from tests.test_runs_api import build_client


def test_create_code_analysis_demo_project_builds_reviewable_package(tmp_path: Path):
    # 显式注入 workspace_root，避免依赖仓库 .env 是否配置过。
    workspace_root = tmp_path / "workspace" / "projects"
    workspace_root.mkdir(parents=True, exist_ok=True)
    client = build_client()
    client.app.dependency_overrides[get_settings] = lambda: Settings(workspace_root=workspace_root)

    response = client.post("/demo/projects/code-analysis")

    assert response.status_code == 201
    project = response.json()
    assert project["name"].startswith("Demo Code Analysis")
    assert project["status"] in {"ready_for_review", "ready_for_review_with_risks"}

    sources_response = client.get(f"/projects/{project['id']}/sources")
    inventory_response = client.get(f"/projects/{project['id']}/inventory")
    runs_response = client.get(f"/projects/{project['id']}/runs")
    latest_report_response = client.get(f"/projects/{project['id']}/reports/latest")

    assert sources_response.status_code == 200
    assert len(sources_response.json()) == 1
    assert sources_response.json()[0]["source_type"] == "local_directory"
    normalized_uri = sources_response.json()[0]["normalized_uri"].replace("\\", "/")
    assert str(workspace_root).replace("\\", "/") in normalized_uri
    assert "/services/api/workspace/" not in normalized_uri

    assert inventory_response.status_code == 200
    inventory = inventory_response.json()
    assert len(inventory["snapshots"]) == 1
    assert len(inventory["codebase_maps"]) == 1
    assert inventory["codebase_maps"][0]["test_files_json"]

    assert runs_response.status_code == 200
    assert len(runs_response.json()) == 1

    assert latest_report_response.status_code == 200
    report = latest_report_response.json()
    assert report["verifier_result_json"]["checks"]
    assert "# Demo Code Analysis 项目调研报告" in report["markdown_content"]
