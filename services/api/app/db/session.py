"""数据库引擎、Session 工厂及 FastAPI 请求级依赖。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# 配置在模块加载时读取一次；数据库地址变化需要重新创建进程才能生效。
settings = get_settings()
# pool_pre_ping 会在复用连接前探测失效连接，降低 MySQL 空闲断连带来的偶发失败。
engine = create_engine(settings.database_url, pool_pre_ping=True)
# autoflush=False 让业务代码显式控制 flush 时机；autocommit 已由 SQLAlchemy 2.x 的
# 事务上下文替代，这里保留 False 以明确禁止语句级自动提交。
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
# 默认让 worker 使用与 API 相同的数据库；测试环境可另行绑定到临时数据库。
WorkerSessionLocal = SessionLocal


def get_session() -> Generator[Session, None, None]:
    """为单次 FastAPI 请求提供 Session，并在请求结束时关闭连接。"""

    with SessionLocal() as session:
        yield session


def bind_worker_session_to(session: Session) -> None:
    """让本地 worker 复用当前运行环境的数据库 bind。

    生产环境默认使用 MySQL `SessionLocal`；测试和单进程开发环境会通过 FastAPI
    dependency override 注入内存库或临时库，enqueue 时同步 worker 的 session factory，
    避免 API 和 worker 看见两套数据库。
    """

    # 仅替换 worker 工厂，不修改 API 请求使用的 SessionLocal。
    global WorkerSessionLocal
    WorkerSessionLocal = sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False)


def get_worker_session_factory() -> sessionmaker[Session]:
    """返回当前生效的 worker Session 工厂，使测试绑定能够被后台入口读取。"""

    return WorkerSessionLocal
