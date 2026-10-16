"""Postgres token-bucket rate limiting (T5.3; SECURITY §9, no Redis per ADR-0004).

Each limited endpoint declares `Depends(rate_limit("run_create"))`. Every limit configured
for that name and the active profile is charged: per user (`:user`) and per client address
(`:ip`, stored as a SHA-256, never the raw address). A bucket row is locked for the length of
one short transaction, so concurrent requests cannot both take the last token.

Behind a reverse proxy, set TRUSTED_PROXY_HOPS to the number of proxies that append to
X-Forwarded-For; otherwise the header is ignored, because a client can write anything there.
"""

import hashlib
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from querycure.api.deps import EngineDep, OptionalUser, SettingsDep
from querycure.core.config import Settings
from querycure.core.errors import RateLimitedError
from querycure.core.logging import get_logger
from querycure.domain.limits import LIMITS, RateLimit

log = get_logger(__name__)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


async def consume(engine: AsyncEngine, bucket_key: str, limit: RateLimit) -> Decision:
    """Take one token from `bucket_key`, refilling first. Atomic per bucket (row lock)."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO rate_limit_buckets (bucket_key, tokens) VALUES (:k, :cap) "
                "ON CONFLICT (bucket_key) DO NOTHING"
            ),
            {"k": bucket_key, "cap": float(limit.capacity)},
        )
        row = (
            await conn.execute(
                text(
                    "SELECT tokens, GREATEST(EXTRACT(EPOCH FROM now() - refilled_at), 0) "
                    "AS elapsed FROM rate_limit_buckets WHERE bucket_key = :k FOR UPDATE"
                ),
                {"k": bucket_key},
            )
        ).one()
        tokens = min(float(limit.capacity), row.tokens + float(row.elapsed) * limit.per_second)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        await conn.execute(
            text(
                "UPDATE rate_limit_buckets SET tokens = :t, refilled_at = now() "
                "WHERE bucket_key = :k"
            ),
            {"t": tokens, "k": bucket_key},
        )
    retry = 0 if allowed else math.ceil((1.0 - tokens) / limit.per_second)
    return Decision(allowed=allowed, remaining=int(tokens), retry_after_seconds=max(retry, 1))


def client_address(request: Request, settings: Settings) -> str:
    hops = settings.trusted_proxy_hops
    if hops > 0:
        forwarded = [
            p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()
        ]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.client.host if request.client else "unknown"


def _ip_subject(address: str) -> str:
    return hashlib.sha256(f"qc-ip:{address}".encode()).hexdigest()[:32]


async def enforce(
    name: str,
    *,
    request: Request,
    engine: AsyncEngine,
    settings: Settings,
    user_id: str | None,
    response: Response | None = None,
) -> None:
    """Charge every limit named `name` for this profile; 429 RATE_LIMITED when one is empty.

    Endpoints with Idempotency-Key call this only after the key lookup, so a retried request
    that returns the original answer is never charged twice."""
    limits = LIMITS[settings.profile]
    remaining: list[int] = []
    for subject_kind in ("user", "ip"):
        limit = limits.get(f"{name}:{subject_kind}")
        if limit is None:
            continue
        if subject_kind == "user":
            if user_id is None:
                continue  # anonymous requests are still covered by the ip limit
            subject = user_id
        else:
            subject = _ip_subject(client_address(request, settings))
        decision = await consume(engine, f"{name}:{subject_kind}:{subject}", limit)
        if not decision.allowed:
            log.info("rate_limited", security=True, limit=name, subject_kind=subject_kind)
            raise RateLimitedError(
                "Too many requests; try again shortly.",
                details=[{"limit": name, "retry_after_seconds": decision.retry_after_seconds}],
                headers={
                    "Retry-After": str(decision.retry_after_seconds),
                    "X-RateLimit-Remaining": "0",
                },
            )
        remaining.append(decision.remaining)
    if remaining and response is not None:
        response.headers["X-RateLimit-Remaining"] = str(min(remaining))


def rate_limit(name: str) -> Callable[..., Awaitable[None]]:
    async def dependency(
        request: Request,
        response: Response,
        engine: EngineDep,
        settings: SettingsDep,
        user: OptionalUser,
    ) -> None:
        await enforce(
            name,
            request=request,
            engine=engine,
            settings=settings,
            user_id=str(user.id) if user else None,
            response=response,
        )

    return dependency
