from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from querycure.api.deps import SettingsDep
from querycure.workloads.registry import WORKLOADS, ExampleQuery

router = APIRouter(prefix="/workloads", tags=["workloads"])
SUGGESTED_SCALE_FACTORS = [0.01, 0.1, 1.0]
DEFAULT_SEED = 42


class WorkloadInfo(BaseModel):
    id: str
    name: str
    version: int
    description: str
    injected_problem: str
    tables: list[str]
    scale_factors: list[float]
    default_seed: int
    example_queries: list[ExampleQuery]
    # Public demo has no live sandbox: benchmark evidence there is prerecorded (DEPLOYMENT §1).
    availability: Literal["live", "prerecorded"]


class WorkloadCatalog(BaseModel):
    items: list[WorkloadInfo]


@router.get("")
async def list_workloads(settings: SettingsDep) -> WorkloadCatalog:
    availability: Literal["live", "prerecorded"] = (
        "live" if settings.feature_sandbox else "prerecorded"
    )
    return WorkloadCatalog(
        items=[
            WorkloadInfo(
                id=f"{spec.name}@v{spec.version}",
                name=spec.name,
                version=spec.version,
                description=spec.description,
                injected_problem=spec.injected_problem,
                tables=spec.tables,
                scale_factors=SUGGESTED_SCALE_FACTORS,
                default_seed=DEFAULT_SEED,
                example_queries=spec.example_queries,
                availability=availability,
            )
            for spec in WORKLOADS.values()
        ]
    )
