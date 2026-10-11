"""SSRF guard for user-supplied database targets (SECURITY.md §5.1).

Resolve once, check every address, then connect with libpq `hostaddr=<pinned ip>` and
`host=<original name>` so TLS still verifies the name while DNS rebinding cannot swap the IP.
"""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from querycure.core.config import Settings
from querycure.core.errors import TargetBlockedError, TargetUnreachableError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]

_LABEL = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?$")
# inet_aton-style forms ("127.1", "2130706433", "0x7f.1", "0177.0.0.1") resolve to IPs in libc.
_NUMERIC_LABEL = re.compile(r"^(?:0x[0-9a-f]*|[0-9]+)$", re.IGNORECASE)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class TargetPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    allow_private: bool
    allowed_ports: frozenset[int] = frozenset({5432, 6543})
    resolve_timeout_s: float = 5.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "TargetPolicy":
        return cls(allow_private=bool(settings.allow_private_targets))


class ResolvedTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str  # original name, used for TLS verification
    hostaddr: str  # pinned address the connection must use
    port: int


def _blocked(reason: str) -> TargetBlockedError:
    # Never echo resolved addresses: they would leak internal network layout.
    return TargetBlockedError(
        "Target address is not allowed on this deployment.",
        details=[{"field": "host", "message": reason}],
    )


def _validate_host(host: str) -> IPAddress | None:
    if not host or host != host.strip() or len(host) > 253:
        raise _blocked("invalid host")
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    labels = host.split(".")
    if all(_NUMERIC_LABEL.match(label) for label in labels):
        raise _blocked("ambiguous numeric host; use a canonical IP address")
    if not all(_LABEL.match(label) for label in labels):
        raise _blocked("invalid host")
    return None


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _block_reason(ip: IPAddress, allow_private: bool) -> str | None:
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            return _block_reason(embedded, allow_private)
    # Unroutable or metadata-style addresses are refused in every profile.
    if ip.is_unspecified:
        return "unspecified address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_loopback:
        # Checked before is_reserved: Python reports ::1 as reserved (it sits in ::/8).
        return None if allow_private else "loopback address"
    if ip.is_reserved:
        return "reserved address"
    if not ip.is_global and not allow_private:
        return "private or non-public address"
    return None


async def _system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


async def resolve_target(
    host: str, port: int, *, policy: TargetPolicy, resolver: Resolver | None = None
) -> ResolvedTarget:
    if port not in policy.allowed_ports:
        raise _blocked(f"port {port} is not allowed")
    literal = _validate_host(host)
    if literal is not None:
        addresses = [literal]
    else:
        try:
            async with asyncio.timeout(policy.resolve_timeout_s):
                answers = await (resolver or _system_resolver)(host, port)
        except (OSError, TimeoutError) as exc:
            raise TargetUnreachableError("Could not resolve the database host.") from exc
        if not answers:
            raise TargetUnreachableError("Could not resolve the database host.")
        try:
            addresses = [ipaddress.ip_address(a.split("%", 1)[0]) for a in answers]
        except ValueError as exc:
            raise _blocked("resolver returned an invalid address") from exc
    for address in addresses:
        reason = _block_reason(address, policy.allow_private)
        if reason is not None:
            raise _blocked(reason)
    return ResolvedTarget(host=host, hostaddr=str(addresses[0]), port=port)
