"""项目输入资料及其扫描结果的只读响应模型。"""

from datetime import datetime

from pydantic import BaseModel


class SourceSnapshotRead(BaseModel):
    """单个输入源在一次采集后的可审计快照。"""

    # 快照主键及其所属项目和输入源。
    id: str
    project_id: str
    source_id: str
    # 采集时记录来源类型，避免后续源记录变化影响历史快照语义。
    source_type: str
    # 采集状态；失败原因由 error_message 补充。
    status: str
    # 便于页面展示的标题和正文短摘要。
    title: str | None
    content_excerpt: str | None
    # 大内容通常落盘，这里保存可回查的内容位置。
    content_path: str | None
    # 采集器附加的来源信息，例如分支、commit 或本地路径。
    metadata_json: dict
    # 记录被策略跳过或无法采集的条目，确保“未发现”和“已排除”可区分。
    skipped_items_json: list
    error_message: str | None
    # 快照的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class CodebaseMapRead(BaseModel):
    """代码库确定性扫描结果，是后续分析代码覆盖度的证据来源。"""

    # 扫描结果主键及其所属项目和输入源。
    id: str
    project_id: str
    source_id: str
    # 展示给用户的项目根目录标签。
    root_label: str
    # 以下清单共同描述技术栈、依赖、配置、测试和入口线索。
    tech_stack_json: list
    dependency_files_json: list
    config_files_json: list
    test_files_json: list
    entrypoint_files_json: list
    # README 的可读摘要；没有 README 时为空。
    readme_excerpt: str | None
    # 扫描得到的目录快照，供后续选择阅读路径和生成报告使用。
    file_tree_json: list
    # 被扫描策略排除的路径及原因。
    skipped_items_json: list
    # 扫描器附加的元数据，例如文件数量限制或扫描参数。
    metadata_json: dict
    # 扫描结果的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class ProjectInventoryRead(BaseModel):
    """一个项目当前可用的输入快照与代码库地图集合。"""

    # 项目标识，用于把下面的资料统一关联到同一业务上下文。
    project_id: str
    snapshots: list[SourceSnapshotRead]
    codebase_maps: list[CodebaseMapRead]
