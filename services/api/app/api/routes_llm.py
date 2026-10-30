"""LLM 供应商状态、配置档位、连通性检测和调用账本接口。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import LLMCall, LLMProfile
from app.db.session import get_session
from app.llm.openai_compatible import OpenAICompatibleClient
from app.llm.profiles import safe_profile_dict
from app.llm.router import LLMRouter
from app.schemas.llm import LLMCallRead, LLMProfileCreate, LLMProfileRead, LLMProfileUpdate

router = APIRouter(prefix="/llm", tags=["llm"])


class SmokeTestRequest(BaseModel):
    """全局 LLM 连通性检测使用的最小请求体。"""

    prompt: str = Field(default="Return one short sentence confirming the provider is reachable.")


def build_llm_client(settings: Settings) -> OpenAICompatibleClient:
    """用环境配置构造一个不带持久化状态的模型客户端。"""

    return OpenAICompatibleClient(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key_required=settings.llm_api_key_required,
        timeout_seconds=settings.llm_timeout_seconds,
    )


@router.get("/provider")
def get_provider_status(settings: Settings = Depends(get_settings)) -> dict:
    """返回环境级 LLM 配置是否完整，不暴露真实 API key。"""

    return build_llm_client(settings).status()


@router.get("/profiles", response_model=list[LLMProfileRead])
def list_llm_profiles(session: Session = Depends(get_session)) -> list[dict]:
    """按最近更新时间返回全部 LLM 配置档位。"""

    # 数据库实体先经过 safe_profile_dict，避免 API key 或内部字段直接下发。
    statement = select(LLMProfile).order_by(LLMProfile.updated_at.desc(), LLMProfile.id.desc())
    return [safe_profile_dict(profile) for profile in session.scalars(statement).all()]


@router.post("/profiles", response_model=LLMProfileRead, status_code=201)
def create_llm_profile(
    payload: LLMProfileCreate,
    session: Session = Depends(get_session),
) -> dict:
    """创建 LLM 配置档位；密钥本身仍由环境变量保存。"""

    profile = LLMProfile(**payload.model_dump())
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return safe_profile_dict(profile)


@router.patch("/profiles/{profile_id}", response_model=LLMProfileRead)
def update_llm_profile(
    profile_id: str,
    payload: LLMProfileUpdate,
    session: Session = Depends(get_session),
) -> dict:
    """部分更新配置档位，并拒绝把关键必填字段显式设为 null。"""

    profile = session.get(LLMProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="LLM profile not found")

    # exclude_unset 区分“未提交该字段”和“显式提交 null”；只有前者表示保持原值。
    updates = payload.model_dump(exclude_unset=True)
    non_nullable_fields = {
        "name",
        "provider",
        "base_url",
        "model",
        "api_key_required",
        "max_tokens",
        "temperature",
        "timeout_seconds",
        "enabled",
    }
    null_fields = sorted(field for field in non_nullable_fields if updates.get(field) is None and field in updates)
    if null_fields:
        # 请求结构允许 None 以支持 PATCH 语义，但业务上这些列不允许被清空。
        raise HTTPException(status_code=422, detail=f"{', '.join(null_fields)} cannot be null")

    for key, value in updates.items():
        setattr(profile, key, value)
    session.commit()
    session.refresh(profile)
    return safe_profile_dict(profile)


@router.post("/profiles/{profile_id}/smoke-test")
def smoke_test_llm_profile(
    profile_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """使用指定档位发起一次最小模型调用，并保留调用账本。"""

    profile = session.get(LLMProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="LLM profile not found")

    # required=False 让未配置或调用失败也返回可展示结果，同时把失败记录进 LLMCall。
    result = LLMRouter(session).chat(
        task_type=profile.task_type,
        profile_id=profile.id,
        messages=[
            {"role": "system", "content": "你是连通性检测助手，只用一句中文回复。"},
            {"role": "user", "content": "请回复一句话，确认当前 LLM 配置可访问。"},
        ],
        required=False,
    )
    session.commit()
    # 响应只截取短文本和错误片段，避免连通性检测返回大段模型输出。
    response = {
        "status": result["status"],
        "call_id": result["call_id"],
        "text_excerpt": result["text"][:240],
    }
    if result.get("error_message"):
        response["error_message"] = result["error_message"][:500]
    return response


@router.get("/calls", response_model=list[LLMCallRead])
def list_llm_calls(
    project_id: str | None = None,
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[LLMCall]:
    """按项目和运行可选过滤最近的 LLM 调用账本。"""

    statement = select(LLMCall)
    if project_id is not None:
        statement = statement.where(LLMCall.project_id == project_id)
    if run_id is not None:
        statement = statement.where(LLMCall.run_id == run_id)
    statement = statement.order_by(LLMCall.created_at.desc(), LLMCall.id.desc())
    return list(session.scalars(statement).all())


@router.post("/smoke-test")
def smoke_test(
    payload: SmokeTestRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    """使用环境配置执行一次不写入 profile 的模型连通性检测。"""

    client = build_llm_client(settings)
    if not client.status()["configured"]:
        raise HTTPException(status_code=503, detail="LLM provider is not configured")

    result = client.chat(
        messages=[
            {
                "role": "system",
                "content": "You are checking whether the Codebase Research Loop local runtime can reach its LLM provider.",
            },
            {"role": "user", "content": payload.prompt},
        ],
        # 检测目标只是验证网络与鉴权，限制输出长度以降低延迟和成本。
        max_tokens=128,
        temperature=0.2,
    )
    return {
        "provider": result["provider"],
        "model": result["model"],
        "status": "ok",
        "text_excerpt": result["text"][:240],
        "usage": result["usage"],
    }
