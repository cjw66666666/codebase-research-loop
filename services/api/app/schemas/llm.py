"""LLM 配置档位和调用账本的 API 数据模型。"""

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# 当前只允许三类模型用途，分别对应分析、校验和报告生成。
TASK_TYPE_PATTERN = r"^(analyzer|verifier|report)$"
# 环境变量名只接受大写字母、数字和下划线，且不能以数字开头。
ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def normalize_api_key_env_name(value: str | None) -> str | None:
    """去除环境变量名首尾空白，并校验其符合 POSIX 环境变量命名规则。"""

    if value is None:
        return None
    stripped = value.strip()
    if not ENV_VAR_NAME_PATTERN.fullmatch(stripped):
        raise ValueError("api_key_env_name must be an environment variable name")
    return stripped


class LLMProfileRead(BaseModel):
    """可安全返回给客户端的 LLM 配置档位。"""

    # 配置档位主键和展示名称。
    id: str
    name: str
    # task_type 决定该档位由哪类 LLM 请求选用。
    task_type: str
    # OpenAI-compatible 服务地址、模型标识和供应商名称。
    provider: str
    base_url: str
    model: str
    # 只返回 API key 的环境变量名，绝不返回密钥值本身。
    api_key_env_name: str | None
    # 标记调用是否必须提供 API key；本地兼容服务可关闭该要求。
    api_key_required: bool
    # 单次调用使用的生成和连接参数。
    max_tokens: int
    temperature: float
    timeout_seconds: int
    # 单日预算上限，单位为分；为空表示不设置额外限制。
    daily_budget_cents: int | None
    # enabled 控制档位是否参与任务选择。
    enabled: bool
    # configured 是运行时计算值，表示地址、模型和所需密钥是否已就绪。
    configured: bool
    # 配置档位的创建和最后更新时间。
    created_at: datetime
    updated_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}


class LLMProfileCreate(BaseModel):
    """创建 LLM 配置档位时提交的参数。"""

    # 名称和任务类型用于管理界面展示与路由选择。
    name: str = Field(min_length=1, max_length=120)
    task_type: str = Field(pattern=TASK_TYPE_PATTERN)
    # provider 仅用于标识供应商，实际请求由 base_url 和 model 决定。
    provider: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1, max_length=160)
    # 通过环境变量名间接引用 API key，避免敏感值写入数据库。
    api_key_env_name: str | None = Field(default=None, max_length=120)
    api_key_required: bool = True
    # 对生成参数设置服务端边界，防止单个配置消耗失控。
    max_tokens: int = Field(default=1200, ge=64, le=16000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    timeout_seconds: int = Field(default=30, ge=1, le=180)
    # 为空表示不限制每日预算，非空值以“分”为单位。
    daily_budget_cents: int | None = Field(default=None, ge=0)
    enabled: bool = True

    @field_validator("api_key_env_name")
    @classmethod
    def validate_api_key_env_name(cls, value: str | None) -> str | None:
        """在模型入口统一执行环境变量名规范化。"""

        return normalize_api_key_env_name(value)


class LLMProfileUpdate(BaseModel):
    """部分更新 LLM 配置档位；未提交的字段保持原值。

    不提供 task_type 字段，避免已有运行和账本记录引用的任务用途发生漂移。
    """

    # 以下可空类型用于表达“本次未提交”，路由通过 exclude_unset 区分省略与显式赋值。
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1, max_length=160)
    api_key_env_name: str | None = Field(default=None, max_length=120)
    api_key_required: bool | None = None
    max_tokens: int | None = Field(default=None, ge=64, le=16000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    timeout_seconds: int | None = Field(default=None, ge=1, le=180)
    daily_budget_cents: int | None = Field(default=None, ge=0)
    enabled: bool | None = None

    @field_validator("api_key_env_name")
    @classmethod
    def validate_api_key_env_name(cls, value: str | None) -> str | None:
        """在部分更新入口同样执行环境变量名规范化。"""

        return normalize_api_key_env_name(value)


class LLMCallRead(BaseModel):
    """单次 LLM 调用的可审计账本记录。"""

    # 调用主键及可选的业务关联；不同调用可能只关联项目、运行或报告之一。
    id: str
    project_id: str | None
    run_id: str | None
    report_id: str | None
    # 实际使用的任务用途、供应商和模型。
    task_type: str
    provider: str
    model: str
    # 仅保存提示词哈希，避免账本重复保存完整输入文本。
    prompt_hash: str
    # 输入引用、输出位置和 token 用量，用于证据追踪及成本统计。
    input_refs_json: list[str]
    output_ref: str | None
    usage_json: dict[str, Any]
    # 调用耗时、最终状态和失败原因。
    latency_ms: int | None
    status: str
    error_message: str | None
    # 调用记录创建时间。
    created_at: datetime

    # 允许直接从 SQLAlchemy ORM 实例构造响应模型。
    model_config = {"from_attributes": True}
