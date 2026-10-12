from fastapi import APIRouter

from querycure.api.deps import CurrentUser, SettingsDep
from querycure.api.schemas.investigations import ModelsResponse
from querycure.core.config import Profile

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/models")
async def models(settings: SettingsDep, _user: CurrentUser) -> ModelsResponse:
    """Which provider/model runs use, and whether a key is configured. Never the key."""
    key = (
        settings.gemini_api_key
        if settings.llm_provider == "gemini"
        else settings.openrouter_api_key
    )
    configured = settings.profile is Profile.LOCAL and (
        settings.llm_provider == "stub" or (key is not None and bool(key.get_secret_value()))
    )
    return ModelsResponse(
        provider=settings.llm_provider,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
        configured=configured,
    )
