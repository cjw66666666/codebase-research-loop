"""资料包创建、条目采集结果和资料包详情的 API 数据模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# 资料包条目允许的输入类型；采集服务会按该值选择对应的规范化与读取逻辑。
SourceBundleInputType = Literal[
    "github_repo",
    "local_directory",
    "local_file",
    "web_page",
    "markdown_file",
    "pdf_file",
]


class SourceBundleItemCreate(BaseModel):
    """创建资料包时提交的一个原始输入条目。"""

    # input_type 指明来源类别，raw_value 保存用户填写或粘贴的原始地址。
    input_type: SourceBundleInputType
    raw_value: str = Field(min_length=1)


class SourceBundleCreate(BaseModel):
    """一次创建资料包时提交的名称和条目集合。"""

    # 资料包名称用于列表和报告展示。
    name: str = Field(default="初始项目资料包", min_length=1, max_length=160)
    # 单次提交限制条目数量，避免采集任务无界扩张。
    items: list[SourceBundleItemCreate] = Field(min_length=1, max_length=20)


class SourceBundleItemRead(BaseModel):
    """资料包条目的原始输入、规范化结果和采集状态。"""

    # 条目主键以及它所属的资料包和项目。
    id: str
    bundle_id: str
    project_id: str
    # 成功创建输入源后回填；解析失败时保持为空。
    source_id: str | None
    # 原始类型和值用于保留用户输入，normalized_uri 是实际采集地址。
    input_type: str
    raw_value: str
    normalized_uri: str | None
    # 条目采集状态和失败原因。
    status: str
    error_message: str | None
    # 规范化器或采集器附加的结构化信息。
    metadata_json: dict
    # 条目的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class SourceBundleRead(BaseModel):
    """资料包详情及其全部条目。"""

    # 资料包主键及其所属项目。
    id: str
    project_id: str
    name: str
    # 资料包整体状态和汇总元数据，不替代每个条目的独立状态。
    status: str
    metadata_json: dict
    # 资料包的创建、更新时间和条目明细。
    created_at: datetime
    updated_at: datetime
    items: list[SourceBundleItemRead]

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}
