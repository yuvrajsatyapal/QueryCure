"""Compatibility goldens for the workload reference format (Part B, M1).

Captured from the implementation BEFORE the fixed-dataset reference format was added, and never
edited to follow a change: a stored `workload_id`, a template name and a generated data set are
frozen strings (replay of old reports and experiments parses them; templates are keyed by them).
If one of these fails, the change broke compatibility, not the test.
"""

import hashlib

import pytest

from querycure.core.errors import ValidationFailedError
from querycure.sandbox.provisioner import template_name
from querycure.workloads.registry import WORKLOADS, WorkloadRef, build_statements

# (input, str(ref), template_name(ref), first 16 hex of sha256 over the generated statements)
GOLDEN = [
    (
        "orders_ecommerce@v1:sf=0.1:seed=42",
        "orders_ecommerce@v1:sf=0.1:seed=42",
        "qc_tpl_9aa62da8b2a436b5",
        "eb2a8a885443ff43",
    ),
    (
        "orders_ecommerce@v1:sf=1:seed=42",
        "orders_ecommerce@v1:sf=1:seed=42",
        "qc_tpl_6f50df897e2e5e66",
        "53c003fa4fac5902",
    ),
    (
        "orders_ecommerce@v1:sf=0.01:seed=7",
        "orders_ecommerce@v1:sf=0.01:seed=7",
        "qc_tpl_22a77fa8f2b11736",
        "227e9ee6c0480c9e",
    ),
    (
        "rewrite_trap@v1:sf=0.1:seed=42",
        "rewrite_trap@v1:sf=0.1:seed=42",
        "qc_tpl_0fda33b636948d7a",
        "19e07b38f92684d5",
    ),
    (
        "rewrite_trap@v1:sf=1:seed=42",
        "rewrite_trap@v1:sf=1:seed=42",
        "qc_tpl_94e19ecbb3151d09",
        "71d96670cc78c6e1",
    ),
    (
        "rewrite_trap@v1:sf=0.01:seed=7",
        "rewrite_trap@v1:sf=0.01:seed=7",
        "qc_tpl_d3579c66aef60d53",
        "9c9db5734e05552d",
    ),
    (
        "no_benefit@v1:sf=0.1:seed=42",
        "no_benefit@v1:sf=0.1:seed=42",
        "qc_tpl_91284e9e6748d681",
        "8309ea73006ef4e6",
    ),
    (
        "no_benefit@v1:sf=1:seed=42",
        "no_benefit@v1:sf=1:seed=42",
        "qc_tpl_bc76267462f15335",
        "4a81821bccb73a70",
    ),
    (
        "no_benefit@v1:sf=0.01:seed=7",
        "no_benefit@v1:sf=0.01:seed=7",
        "qc_tpl_16176d4343b75112",
        "bf1f58a448b87f30",
    ),
    (
        "join_fanout@v1:sf=0.1:seed=42",
        "join_fanout@v1:sf=0.1:seed=42",
        "qc_tpl_6711f847b9da05aa",
        "6a8ef6cf8750f350",
    ),
    (
        "join_fanout@v1:sf=1:seed=42",
        "join_fanout@v1:sf=1:seed=42",
        "qc_tpl_e03aa1ca1dd0c83b",
        "e657d4382b8b32e3",
    ),
    (
        "join_fanout@v1:sf=0.01:seed=7",
        "join_fanout@v1:sf=0.01:seed=7",
        "qc_tpl_d9ac6d3e4a1e05fe",
        "2533671478d8ba71",
    ),
    (
        "stale_stats@v1:sf=0.1:seed=42",
        "stale_stats@v1:sf=0.1:seed=42",
        "qc_tpl_9a3d7194129c7e46",
        "cf0f5879204d982d",
    ),
    (
        "stale_stats@v1:sf=1:seed=42",
        "stale_stats@v1:sf=1:seed=42",
        "qc_tpl_af9441b7b0002c4f",
        "a434a6ce9ad44b7e",
    ),
    (
        "stale_stats@v1:sf=0.01:seed=7",
        "stale_stats@v1:sf=0.01:seed=7",
        "qc_tpl_a1589a7aa8d8b5e5",
        "f3d9a8bf1a0d7a2f",
    ),
    (
        "index_regression@v1:sf=0.1:seed=42",
        "index_regression@v1:sf=0.1:seed=42",
        "qc_tpl_db721da709ee5990",
        "cb23e646bf87da02",
    ),
    (
        "index_regression@v1:sf=1:seed=42",
        "index_regression@v1:sf=1:seed=42",
        "qc_tpl_35845bc867209309",
        "4e05acd35e4cff07",
    ),
    (
        "index_regression@v1:sf=0.01:seed=7",
        "index_regression@v1:sf=0.01:seed=7",
        "qc_tpl_21c5cc06ce438c65",
        "101da7acac4aa298",
    ),
    (
        "no_benefit@v1:sf=0.2:seed=42",
        "no_benefit@v1:sf=0.2:seed=42",
        "qc_tpl_53a8cb2a3a433ee9",
        "8309ea73006ef4e6",
    ),
    (
        "orders_ecommerce@v1:sf=10:seed=999999999",
        "orders_ecommerce@v1:sf=10:seed=999999999",
        "qc_tpl_f0f3ea1f85601460",
        "3b660092b1dd9e53",
    ),
    (
        "orders_ecommerce@v1:sf=0.05:seed=0",
        "orders_ecommerce@v1:sf=0.05:seed=0",
        "qc_tpl_53fa30c8ca08beb1",
        "1f6b5d4988fb2cf8",
    ),
    (
        "orders_ecommerce@v1:sf=1.50:seed=1",
        "orders_ecommerce@v1:sf=1.5:seed=1",
        "qc_tpl_24b8a19144a2147a",
        "afb8a57d107c49d7",
    ),
]

EXISTING = {
    "orders_ecommerce": ["customers", "orders"],
    "rewrite_trap": ["accounts", "closed_regions"],
    "no_benefit": ["app_settings"],
    "join_fanout": ["authors", "posts"],
    "stale_stats": ["accounts", "events"],
    "index_regression": ["tickets"],
}


def generated_digest(ref: WorkloadRef) -> str:
    text = "\n".join(s.as_string(None) for s in build_statements(ref))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@pytest.mark.parametrize(("text", "rendered", "template", "data"), GOLDEN)
def test_existing_refs_keep_their_string_template_name_and_data(
    text: str, rendered: str, template: str, data: str
) -> None:
    ref = WorkloadRef.parse(text)

    assert str(ref) == rendered
    assert template_name(ref) == template
    assert generated_digest(ref) == data
    assert WorkloadRef.parse(str(ref)) == ref  # the rendered form parses back to the same ref


@pytest.mark.parametrize(("text", "rendered", "template", "data"), GOLDEN)
def test_existing_refs_carry_scale_factor_and_seed_and_no_data_id(
    text: str, rendered: str, template: str, data: str
) -> None:
    ref = WorkloadRef.parse(text)
    name, rest = rendered.split("@v1:sf=")
    scale, seed = rest.split(":seed=")

    assert (ref.name, ref.version) == (name, 1)
    assert (ref.scale_factor, ref.seed) == (float(scale), int(seed))


def test_the_six_existing_workloads_keep_their_names_versions_and_tables() -> None:
    for name, tables in EXISTING.items():
        assert WORKLOADS[name].version == 1
        assert WORKLOADS[name].tables == tables


@pytest.mark.parametrize(
    "bad",
    [
        "orders_ecommerce",
        "orders_ecommerce@v1",
        "orders_ecommerce@v1:sf=1",
        "orders_ecommerce@v1:seed=42",
        "orders_ecommerce@v9:sf=1:seed=42",
        "nope@v1:sf=1:seed=42",
        "orders_ecommerce@v1:sf=0:seed=42",
        "orders_ecommerce@v1:sf=0.009:seed=42",
        "orders_ecommerce@v1:sf=10.01:seed=42",
        "orders_ecommerce@v1:sf=11:seed=42",
        "orders_ecommerce@v1:sf=1:seed=-1",
        "orders_ecommerce@v1:sf=1:seed=1234567890",
        "orders_ecommerce@v1:sf=1;DROP:seed=1",
        " orders_ecommerce@v1:sf=1:seed=1",
    ],
)
def test_existing_workloads_still_reject_malformed_refs(bad: str) -> None:
    with pytest.raises(ValidationFailedError):
        WorkloadRef.parse(bad)
