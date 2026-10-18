"""Record-mode guards (2026-10-18).

Free model requests are scarce (about 45 a day, ADR-0016). A Mode C recording spends 10-15 of
them and measures in the sandbox while it waits for the model, so a contended host turns a
recording into an inconclusive benchmark and a wasted day. On 2026-10-18 a recording ran while
other projects held the host at load 15: the in-network `SELECT 1` floor rose from 60-70 us to
138-470 us, every round was inconclusive, and 13 requests were spent.

- `quiet_host` checks the sandbox round-trip floor before any request is made.
- `should_save` keeps an existing recording when the new one fails its checks, unless the
  failure is a declared known failure for this model or the caller insists.
"""

import statistics
from collections.abc import Sequence

# Twice the quiet medians measured on the development host (BENCHMARK_ENGINE §12): in-network
# 60-70 us, relay 307-457 us.
QUIET_FLOOR_NS = {"docker-network": 150_000, "docker-relay": 900_000}
MAX_FLOOR_ROBUST_CV = 0.5
FLOOR_SAMPLES = 50


def quiet_host(samples_ns: Sequence[int], *, path: str) -> tuple[bool, str]:
    if len(samples_ns) < 4:
        return False, "too few round trips to judge the host"
    median = statistics.median(samples_ns)
    q1, _, q3 = statistics.quantiles(samples_ns, n=4, method="inclusive")
    rcv = (q3 - q1) / (1.349 * median) if median > 0 else float("inf")
    limit = QUIET_FLOOR_NS.get(path, QUIET_FLOOR_NS["docker-relay"])
    detail = (
        f"sandbox round trip median {median / 1e3:.0f} us (limit {limit / 1e3:.0f} us on {path}), "
        f"robust CV {rcv:.2f} (limit {MAX_FLOOR_ROBUST_CV})"
    )
    if median > limit or rcv > MAX_FLOOR_ROBUST_CV:
        return False, f"host looks contended: {detail}"
    return True, detail


def should_save(*, passed: bool, expected_failure: str | None, keep_failing: bool) -> bool:
    return passed or expected_failure is not None or keep_failing
