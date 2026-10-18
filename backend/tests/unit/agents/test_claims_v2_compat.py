"""claims@2 keeps every claims@1 guarantee: each claims@1 regression test (the real run-2 texts
of the 2026-10-17 audit among them) runs again with claims@2's filter on an unattributed
context, which is what claims@1 contexts become under claims@2."""

import dataclasses
import inspect
from collections.abc import Callable

import pytest

from querycure.agents import claims as v1
from querycure.agents import claims_v2 as v2
from tests.unit.agents import test_claims

CASES = [
    (name, fn)
    for name, fn in inspect.getmembers(test_claims, inspect.isfunction)
    if name.startswith("test_") and fn.__module__ == test_claims.__name__
]


def _upgrade(ctx: v1.ClaimContext) -> v2.ClaimContext:
    return v2.ClaimContext(**{f.name: getattr(ctx, f.name) for f in dataclasses.fields(ctx)})


@pytest.mark.parametrize(("name", "case"), CASES, ids=[n for n, _ in CASES])
def test_claims_v1_case_holds_under_v2(
    name: str, case: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        test_claims, "filter_text",
        lambda text, ctx, mode="fact": v2.filter_text(text, _upgrade(ctx), mode=mode),
    )  # fmt: skip
    params = inspect.signature(case).parameters
    if params:
        pytest.skip("parametrized claims@1 case; covered by its own module")
    case()
