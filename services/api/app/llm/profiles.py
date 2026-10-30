"""LLM 配置档位的查询、可用性判断和安全序列化。"""

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import LLMProfile


def profile_is_configured(profile: LLMProfile, api_key: str | None = None) -> bool:
    """判断配置档位是否具备发起模型请求的最低条件。

    数据库中的 profile 只保存 API key 的环境变量名，因此默认通过检查该环境变量
    是否有值来判断；调用方也可以传入已经解析好的 api_key 做即时判断。
    """

    # 地址和模型名缺一不可，仅配置了 API key 仍不足以调用模型。
    has_endpoint = bool(profile.base_url and profile.model)
    if not has_endpoint:
        return False
    # 本地兼容服务可能不需要鉴权，此时只要端点信息完整即可视为可用。
    if not bool(profile.api_key_required):
        return True
    # 显式传入密钥时使用调用方提供的值，避免再次读取环境变量。
    if api_key is not None:
        return bool(api_key)
    # 数据库配置只保存变量名；变量不存在或为空都视为尚未配置。
    return bool(profile.api_key_env_name and os.getenv(profile.api_key_env_name))


def safe_profile_dict(profile: LLMProfile) -> dict:
    """返回可安全下发到 API 的 profile 形状，不包含任何 API key 值。"""

    # 该字典是 API 读取 profile 的唯一出口：只暴露环境变量名和配置状态。
    return {
        "id": profile.id,
        "name": profile.name,
        "task_type": profile.task_type,
        "provider": profile.provider,
        "base_url": profile.base_url,
        "model": profile.model,
        "api_key_env_name": profile.api_key_env_name,
        "api_key_required": bool(profile.api_key_required),
        "max_tokens": profile.max_tokens,
        "temperature": profile.temperature,
        "timeout_seconds": profile.timeout_seconds,
        "daily_budget_cents": profile.daily_budget_cents,
        "enabled": bool(profile.enabled),
        "configured": profile_is_configured(profile),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def get_enabled_profile(session: Session, task_type: str) -> LLMProfile | None:
    """按任务类型选择最近更新的启用档位。"""

    # 同一任务可能存在多个档位；updated_at 保证显式更新过的配置优先，
    # id 作为更新时间相同时的稳定兜底排序。
    statement = (
        select(LLMProfile)
        .where(LLMProfile.task_type == task_type, LLMProfile.enabled == True)  # noqa: E712
        .order_by(LLMProfile.updated_at.desc(), LLMProfile.id.desc())
    )
    return session.scalars(statement).first()


def default_profile_from_settings(settings: Settings, task_type: str) -> LLMProfile | None:
    """把环境配置转换为内存中的默认 LLMProfile，不写入数据库。

    当 provider 地址或模型名缺失时返回 None，由上层决定是否禁用 LLM 能力。
    """

    # 没有端点和模型就无法发起请求，不构造一个表面可用的空配置。
    if not settings.llm_base_url or not settings.llm_model:
        return None

    # 默认档位使用固定环境变量 LLM_API_KEY；实际密钥仍由请求适配器读取。
    return LLMProfile(
        name=f"Default {task_type}",
        task_type=task_type,
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key_env_name="LLM_API_KEY",
        api_key_required=settings.llm_api_key_required,
        # 分析任务需要较长的结构化输出，校验和报告任务使用较小的默认预算。
        max_tokens=1200 if task_type == "analyzer" else 800,
        temperature=0.2,
        timeout_seconds=int(settings.llm_timeout_seconds),
        daily_budget_cents=None,
        enabled=True,
    )
