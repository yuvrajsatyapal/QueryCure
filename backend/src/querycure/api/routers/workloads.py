from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from querycure.api.deps import SettingsDep
from querycure.core.config import Profile
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
    # A generated workload is picked by scale factor and seed; a fixed dataset has neither.
    scale_factors: list[float]
    default_seed: int | None
    # The full reference for a fixed dataset (`name@vN:data=<id>`); None for generated ones,
    # whose reference the client builds from a scale factor and seed.
    ref: str | None
    # The data is a file on the operator's machine, never in the repo or the container image.
    requires_local_data: bool
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
                scale_factors=[] if spec.fixed else SUGGESTED_SCALE_FACTORS,
                default_seed=None if spec.fixed else DEFAULT_SEED,
                ref=f"{spec.name}@v{spec.version}:data={spec.fixed.data_id}"
                if spec.fixed
                else None,
                requires_local_data=spec.fixed is not None,
                example_queries=spec.example_queries,
                availability=availability,
            )
            for spec in WORKLOADS.values()
            # The public demo has no local data directory: fixed datasets are not offered there.
            if spec.fixed is None or settings.profile is not Profile.DEMO
        ]
    )
