"""应用工厂和健康检查端点的冒烟测试。"""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_returns_api_status():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": "Codebase Research Loop API",
    }
