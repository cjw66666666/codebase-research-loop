"""FastAPI 应用入口和路由组装根节点。

``create_app()`` 负责创建应用实例、添加中间件并挂载各业务路由；各
``routes_*.py`` 只维护自己的 ``APIRouter`` 和端点，避免入口文件承载具体业务。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_demo,
    routes_evaluations,
    routes_events,
    routes_inventory,
    routes_llm,
    routes_projects,
    routes_research_profiles,
    routes_reports,
    routes_runs,
    routes_source_bundles,
    routes_sources,
    routes_tools,
)
from app.core.config import get_settings


def create_app() -> FastAPI:
    """创建并配置一个 FastAPI 应用实例。

    使用应用工厂而不是只在模块顶层初始化，测试可以为每个用例创建独立应用；
    模块底部的 ``app`` 则供 uvicorn 等服务器直接导入。
    """

    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    # 当前只允许本地前端开发地址跨域访问，并允许浏览器携带凭据。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 路由注册集中在这里：每个模块导出一个 APIRouter，入口只负责组合，
    # 不重复声明路径、请求模型和响应模型。
    app.include_router(routes_demo.router)
    app.include_router(routes_evaluations.router)
    app.include_router(routes_projects.router)
    app.include_router(routes_research_profiles.router)
    app.include_router(routes_source_bundles.router)
    app.include_router(routes_sources.router)
    app.include_router(routes_inventory.router)
    app.include_router(routes_events.router)
    app.include_router(routes_llm.router)
    app.include_router(routes_runs.router)
    app.include_router(routes_reports.router)
    app.include_router(routes_tools.router)

    # 健康检查不依赖数据库，用于进程存活探针和本地启动确认。
    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "app": settings.app_name,
        }

    return app


# ASGI 服务器按约定从 ``app.main:app`` 导入该实例。
app = create_app()
