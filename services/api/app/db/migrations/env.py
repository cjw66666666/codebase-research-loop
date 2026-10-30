"""Alembic 迁移运行环境。

该入口把应用配置中的数据库地址和 ORM 元数据交给 Alembic，使命令行迁移和应用
运行时始终指向同一套配置。离线模式只生成 SQL，在线模式会实际连接数据库执行。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
# 导入 models 是为了让所有表声明注册到 Base.metadata，供 autogenerate 比较。
from app.db import models  # noqa: F401
from app.db.base import Base

config = context.config
fileConfig(config.config_file_name)

# 应用配置优先于 alembic.ini，避免环境变量和迁移命令使用不同的数据库地址。
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
# 迁移比较的目标结构来自 ORM 模型，而不是手工维护的第二份表定义。
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """在不建立数据库连接的情况下输出带字面量参数的迁移 SQL。"""

    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """建立一次性数据库连接并在线执行迁移。"""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        # 迁移命令执行完即退出，不需要保留连接池。
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
