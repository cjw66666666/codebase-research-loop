"""SQLAlchemy 声明式模型基类。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全部 ORM 模型的公共基类，集中注册表元数据供 Alembic 使用。"""

    pass
