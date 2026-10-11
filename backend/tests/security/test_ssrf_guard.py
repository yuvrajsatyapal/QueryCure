import asyncio
import base64
import os
from collections.abc import Sequence

import pytest

from querycure.connectors.ssrf_guard import TargetPolicy, resolve_target
from querycure.core.config import Profile, Settings
from querycure.core.errors import TargetBlockedError, TargetUnreachableError

PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"


def resolver_for(answers: dict[str, Sequence[str]]):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    async def resolve(host: str, port: int) -> list[str]:
        calls.append(host)
        if host not in answers:
            raise OSError("NXDOMAIN")
        return list(answers[host])

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def reason(info: pytest.ExceptionInfo[TargetBlockedError]) -> str:
    return str(info.value.details[0]["message"])


PUBLIC = TargetPolicy(allow_private=False)
LOCAL = TargetPolicy(allow_private=True)


async def guard(host: str, policy: TargetPolicy = PUBLIC, port: int = 5432, answers=None):  # type: ignore[no-untyped-def]
    resolver = resolver_for(answers if answers is not None else {host: [host]})
    return await resolve_target(host, port, policy=policy, resolver=resolver)


async def test_public_hostname_is_pinned_to_resolved_address() -> None:
    target = await guard("db.example.com", answers={"db.example.com": [PUBLIC_V4]})

    assert target.host == "db.example.com"
    assert target.hostaddr == PUBLIC_V4
    assert target.port == 5432


async def test_public_ipv6_literal_is_allowed() -> None:
    target = await guard(PUBLIC_V6)

    assert target.hostaddr == PUBLIC_V6


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "127.1.2.3", "10.0.0.5", "172.16.0.1", "192.168.1.1", "100.64.0.1",
        "169.254.169.254", "0.0.0.0", "224.0.0.1", "255.255.255.255", "198.18.0.1", "240.0.0.1",
        "::1", "::", "fc00::1", "fd12:3456::1", "fe80::1", "ff02::1",
        "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a00:1",
        "2002:7f00:1::", "2002:a00:1::",
    ],
)  # fmt: skip
async def test_non_public_addresses_are_blocked(address: str) -> None:
    with pytest.raises(TargetBlockedError):
        await guard("db.example.com", answers={"db.example.com": [address]})


async def test_any_blocked_address_in_answer_blocks_the_target() -> None:
    with pytest.raises(TargetBlockedError):
        await guard("db.example.com", answers={"db.example.com": [PUBLIC_V4, "10.0.0.1"]})


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
async def test_localhost_blocked_in_public_profile(host: str) -> None:
    with pytest.raises(TargetBlockedError):
        await guard(host, answers={host: ["127.0.0.1"] if host == "localhost" else [host]})


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "192.168.1.10", "::1"])
async def test_local_profile_allows_private_targets(address: str) -> None:
    target = await guard("db.local", policy=LOCAL, answers={"db.local": [address]})

    assert target.hostaddr == address


@pytest.mark.parametrize("address", ["169.254.169.254", "fe80::1", "0.0.0.0", "::", "224.0.0.1"])
async def test_metadata_and_unroutable_addresses_blocked_even_locally(address: str) -> None:
    with pytest.raises(TargetBlockedError):
        await guard("db.local", policy=LOCAL, answers={"db.local": [address]})


@pytest.mark.parametrize("host", ["2130706433", "0x7f000001", "0177.0.0.1", "127.1", "0x7f.1"])
async def test_ambiguous_numeric_hosts_are_rejected(host: str) -> None:
    with pytest.raises(TargetBlockedError) as info:
        await guard(host, policy=LOCAL)

    assert "numeric" in reason(info)


@pytest.mark.parametrize(
    "host",
    [
        "", " ", "db.example.com/x", "user@db.example.com", "postgresql://db.example.com",
        "db example.com", "db.example.com:5432", "-bad.example.com", "a" * 254, "db..example.com",
        "host=evil sslmode=disable",
    ],
)  # fmt: skip
async def test_malformed_hosts_are_rejected_before_resolution(host: str) -> None:
    resolver = resolver_for({})

    with pytest.raises(TargetBlockedError):
        await resolve_target(host, 5432, policy=PUBLIC, resolver=resolver)
    assert resolver.calls == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("port", [22, 80, 443, 6379, 0, 70000])
async def test_ports_outside_allowlist_are_rejected(port: int) -> None:
    with pytest.raises(TargetBlockedError) as info:
        await guard("db.example.com", port=port, answers={"db.example.com": [PUBLIC_V4]})

    assert reason(info) == f"port {port} is not allowed"


async def test_extra_ports_can_be_allowed_by_configuration() -> None:
    policy = TargetPolicy(allow_private=False, allowed_ports=frozenset({5432, 15432}))

    target = await guard(
        "db.example.com", policy=policy, port=15432, answers={"db.example.com": [PUBLIC_V4]}
    )

    assert target.port == 15432


async def test_dns_is_resolved_exactly_once_so_rebinding_cannot_swap_the_address() -> None:
    answers = iter([[PUBLIC_V4], ["127.0.0.1"]])
    calls = 0

    async def rebinding(host: str, port: int) -> list[str]:
        nonlocal calls
        calls += 1
        return next(answers)

    target = await resolve_target("rebind.example.com", 5432, policy=PUBLIC, resolver=rebinding)

    assert calls == 1
    assert target.hostaddr == PUBLIC_V4


async def test_resolution_failure_is_unreachable_not_blocked() -> None:
    with pytest.raises(TargetUnreachableError):
        await guard("nope.example.com", answers={})


async def test_resolution_timeout_is_unreachable() -> None:
    async def slow(host: str, port: int) -> list[str]:
        await asyncio.sleep(5)
        return [PUBLIC_V4]

    policy = TargetPolicy(allow_private=False, resolve_timeout_s=0.05)
    with pytest.raises(TargetUnreachableError):
        await resolve_target("slow.example.com", 5432, policy=policy, resolver=slow)


async def test_empty_answer_is_unreachable() -> None:
    with pytest.raises(TargetUnreachableError):
        await guard("empty.example.com", answers={"empty.example.com": []})


async def test_error_messages_do_not_echo_resolved_private_addresses() -> None:
    with pytest.raises(TargetBlockedError) as info:
        await guard("db.example.com", answers={"db.example.com": ["10.1.2.3"]})

    assert "10.1.2.3" not in str(info.value)
    assert "10.1.2.3" not in str(info.value.details)


async def test_system_resolver_path_resolves_localhost_for_local_profile() -> None:
    target = await resolve_target("localhost", 5432, policy=LOCAL)

    assert target.hostaddr in {"127.0.0.1", "::1"}


async def test_system_resolver_path_blocks_localhost_for_public_profile() -> None:
    with pytest.raises(TargetBlockedError):
        await resolve_target("localhost", 5432, policy=PUBLIC)


def test_policy_from_settings_follows_profile() -> None:
    demo = Settings(
        _env_file=None,
        profile=Profile.DEMO,
        allow_private_targets=False,
        master_key=base64.b64encode(os.urandom(32)).decode(),
    )

    assert TargetPolicy.from_settings(demo).allow_private is False
    assert TargetPolicy.from_settings(Settings(_env_file=None)).allow_private is True
