"""Request rate limits per profile (T5.3, SECURITY T13). Token buckets: `capacity` requests
in a burst, refilled continuously at `per_hour` per hour. The public demo is much stricter:
its users are anonymous, and every run spends the user's own free model quota anyway."""

from dataclasses import dataclass

from querycure.core.config import Profile


@dataclass(frozen=True)
class RateLimit:
    capacity: int
    per_hour: float

    @property
    def per_second(self) -> float:
        return self.per_hour / 3600.0


# Subject: "ip" limits apply to a hash of the client address, "user" limits to the user.
LIMITS: dict[Profile, dict[str, RateLimit]] = {
    # Local profile: one developer on localhost. Only a backstop against a runaway client or
    # script; the demo limits below are the real policy (and what the security tests check).
    Profile.LOCAL: {
        name: RateLimit(capacity=10_000, per_hour=100_000)
        for name in (
            "session_create:ip",
            "run_create:user",
            "experiment_replay:user",
            "report_replay:user",
            "inspect:user",
            "connection:user",
            "settings:user",
        )
    },
    Profile.DEMO: {
        "session_create:ip": RateLimit(capacity=10, per_hour=30),
        "run_create:user": RateLimit(capacity=3, per_hour=10),
        "run_create:ip": RateLimit(capacity=5, per_hour=20),
        "experiment_replay:user": RateLimit(capacity=2, per_hour=6),
        "report_replay:user": RateLimit(capacity=10, per_hour=60),
        "inspect:user": RateLimit(capacity=20, per_hour=120),
        "connection:user": RateLimit(capacity=5, per_hour=30),
        "settings:user": RateLimit(capacity=10, per_hour=30),
    },
}
