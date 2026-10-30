"""调研档位注册表的只读接口。"""

from fastapi import APIRouter, HTTPException, status

from app.research.profiles import get_research_profile, list_research_profiles, research_profile_exists
from app.schemas.research_profile import ResearchProfileRead

router = APIRouter(prefix="/research-profiles", tags=["research-profiles"])


@router.get("", response_model=list[ResearchProfileRead])
def list_profiles() -> list:
    """列出全部内置调研档位。"""

    return list_research_profiles()


@router.get("/{profile_key}", response_model=ResearchProfileRead)
def get_profile(profile_key: str):
    """按稳定 key 返回单个调研档位。"""

    if not research_profile_exists(profile_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research profile not found")
    return get_research_profile(profile_key)
