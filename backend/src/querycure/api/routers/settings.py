import uuid

from fastapi import APIRouter, Depends, Response, status

from querycure.api.deps import ConnDep, CurrentUser, SettingsDep
from querycure.api.rate_limit import rate_limit
from querycure.api.schemas.investigations import ModelsResponse
from querycure.api.schemas.settings import (
    AddLlmCredentialRequest,
    LlmCredentialList,
    LlmCredentialOut,
)
from querycure.core.config import Profile, is_free_model
from querycure.core.errors import FeatureDisabledError, NotFoundError, ValidationFailedError
from querycure.core.logging import get_logger
from querycure.db.repositories import llm_credentials as creds
from querycure.llm.credentials import allowed_byok_providers, secret_box, server_key

router = APIRouter(prefix="/settings", tags=["settings"])
log = get_logger(__name__)


@router.get("/models")
async def models(settings: SettingsDep, conn: ConnDep, user: CurrentUser) -> ModelsResponse:
    """Which provider/model runs use, and whether a key exists (the user's own, or the local
    profile's server key). Never the key."""
    own = await creds.get_active(conn, user_id=user.id, provider=settings.llm_provider)
    key = None if settings.llm_provider == "stub" else server_key(settings, settings.llm_provider)
    server = settings.profile is Profile.LOCAL and (
        settings.llm_provider == "stub" or (key is not None and bool(key.get_secret_value()))
    )
    return ModelsResponse(
        provider=settings.llm_provider,
        model=(own.default_model if own and own.default_model else settings.llm_model),
        fallback_model=None if own else settings.llm_fallback_model,
        configured=own is not None or server,
    )


@router.get("/llm-credentials")
async def list_llm_credentials(conn: ConnDep, user: CurrentUser) -> LlmCredentialList:
    items = await creds.list_credentials(conn, user.id)
    return LlmCredentialList(items=[LlmCredentialOut.model_validate(i.model_dump()) for i in items])


@router.post(
    "/llm-credentials",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("settings"))],
)
async def add_llm_credential(
    body: AddLlmCredentialRequest, conn: ConnDep, user: CurrentUser, settings: SettingsDep
) -> LlmCredentialOut:
    """Stores the user's own key encrypted (ADR-0012), replacing any earlier key for the same
    provider. The response, logs and errors show only the last 4 characters."""
    if body.provider not in allowed_byok_providers(settings):
        raise FeatureDisabledError("Only OpenRouter keys are accepted here (free models only).")
    free_only_violation = (
        settings.llm_free_only
        and body.default_model is not None
        and not is_free_model(body.default_model)
    )
    if free_only_violation:
        raise ValidationFailedError(
            "Only free models can be used (ADR-0016).",
            details=[{"field": "default_model", "message": "must end in ':free'"}],
        )
    box = secret_box(settings)  # 503 CONFIGURATION_ERROR without QC_MASTER_KEY
    saved = await creds.replace_credential(
        conn,
        box=box,
        user_id=user.id,
        provider=body.provider,
        api_key=body.api_key.get_secret_value(),
        default_model=body.default_model,
    )
    log.info("llm_credential_saved", security=True, provider=body.provider)
    return LlmCredentialOut.model_validate(saved.model_dump())


@router.delete(
    "/llm-credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("settings"))],
)
async def delete_llm_credential(
    credential_id: uuid.UUID, conn: ConnDep, user: CurrentUser
) -> Response:
    """Soft-deletes the row and wipes the ciphertext in the same statement. Runs that were
    started with it stop at their next resume with CONFIGURATION_ERROR."""
    if not await creds.wipe(conn, user_id=user.id, credential_id=credential_id):
        raise NotFoundError("Key not found.")
    log.info("llm_credential_deleted", security=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
