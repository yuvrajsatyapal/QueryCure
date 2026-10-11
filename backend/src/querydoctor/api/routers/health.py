from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/healthz")
async def healthz() -> HealthResponse:
    # Liveness only. /readyz (metadata DB + migrations) arrives with the DB layer in T1.4/T1.5.
    return HealthResponse(status="ok")
