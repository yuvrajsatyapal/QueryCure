"""Interleaved, seeded measurement schedule (BENCHMARK_ENGINE §4 step 3).

Blocks repeat until every arm has `measured_runs` samples per param set. Within a block each
arm runs `runs` consecutive times, in an order shuffled by a seed derived from
(experiment seed, param set, block), so slow drift cannot systematically favour one arm and
a resumed experiment re-derives the same order for its missing blocks.
"""

import hashlib
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


def derive_seed(seed: int, *parts: object) -> int:
    """A 64-bit seed for one sub-stream. SHA-256 keeps it stable across Python versions."""
    label = ":".join([str(seed), *(str(p) for p in parts)]).encode()
    return int.from_bytes(hashlib.sha256(label).digest()[:8], "big")


@dataclass(frozen=True)
class ScheduledBlock:
    param_set: str
    block: int
    runs: int  # samples per arm in this block
    arm_order: tuple[str, ...]


def build_schedule(
    arms: Sequence[str],
    param_sets: Sequence[str],
    *,
    measured_runs: int,
    block_size: int,
    seed: int,
) -> list[ScheduledBlock]:
    if measured_runs < 1:
        raise ValueError("measured_runs must be at least 1")
    if block_size < 1:
        raise ValueError("block_size must be at least 1")
    schedule: list[ScheduledBlock] = []
    for block in range(math.ceil(measured_runs / block_size)):
        runs = min(block_size, measured_runs - block * block_size)
        # Param sets alternate within a block index so drift hits them equally too.
        for param_set in param_sets:
            order = list(arms)
            # Seeded on purpose: replay must re-derive the same order (not a security use).
            rng = random.Random(derive_seed(seed, "schedule", param_set, block))  # noqa: S311
            rng.shuffle(order)
            schedule.append(
                ScheduledBlock(param_set=param_set, block=block, runs=runs, arm_order=tuple(order))
            )
    return schedule
