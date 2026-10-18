"""Black-box check of a running restricted demo deployment (DEPLOYMENT §3, 2026-10-18).

    uv run python -m querycure.ops.demo_probe --base-url http://127.0.0.1:8300 \
        --web-origin http://localhost:3300

It asserts the demo's restrictions through HTTP only, the way a public visitor meets them,
instead of trusting environment variable names: features off in `/me`, live inspection and
sandbox refused, no shared model key (no paid or server fallback), metrics and docs hidden,
another visitor's investigation invisible, strict CORS, security headers, and error envelopes
without internals. It creates two anonymous sessions and nothing else (every investigation
request it sends is refused before a row is written); it never needs or prints a secret.

Exit status 0 means every check passed. Run it against local or staging deployments you own.
"""

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

API = "/api/v1"
QUERY = "SELECT id FROM orders WHERE customer_id = 7"


@dataclass
class Probe:
    base_url: str
    web_origin: str
    results: list[tuple[str, bool, str]] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, ok, detail))


def _session(base_url: str, web_origin: str) -> httpx.Client:
    """An anonymous visitor. Demo cookies are `Secure`; over plain-HTTP localhost the probe
    carries them by hand, as a browser does for http://localhost."""
    client = httpx.Client(base_url=base_url, headers={"Origin": web_origin}, timeout=15)
    r = client.post(f"{API}/session")
    if r.status_code not in (200, 201):
        raise SystemExit(f"cannot create a session: {r.status_code} {r.text[:200]}")
    # httpx never returns `Secure` cookies over http://, so they always travel explicitly.
    jar: dict[str, str] = {}
    for header in r.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        jar[name.strip()] = rest.split(";", 1)[0]
    client.cookies.clear()
    client.headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
    client.headers["X-CSRF-Token"] = jar.get("qc_csrf", "")
    return client


def _code(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", {}).get("code", ""))
    except ValueError:
        return ""


def run(probe: Probe) -> None:
    p, base = probe, probe.base_url
    anon = httpx.Client(base_url=base, timeout=15)
    ready = anon.get(f"{API}/readyz")
    p.check("readyz is ok", ready.status_code == 200, ready.text[:120])

    alice = _session(base, probe.web_origin)
    created = alice.post(f"{API}/session")  # second call reuses the session
    cookie_header = " ".join(created.headers.get_list("set-cookie"))
    first = httpx.Client(base_url=base).post(f"{API}/session")
    set_cookie = " ".join(first.headers.get_list("set-cookie")).lower()
    p.check("session cookie is Secure, HttpOnly, SameSite=Lax",
            all(x in set_cookie for x in ("secure", "httponly", "samesite=lax")),
            set_cookie[:160] or cookie_header[:160])  # fmt: skip

    me = alice.get(f"{API}/me")
    body = me.json() if me.status_code == 200 else {}
    features = body.get("features", {})
    p.check("profile is demo", body.get("profile") == "demo", str(body.get("profile")))
    p.check("sandbox feature is off", features.get("sandbox") is False, str(features))
    p.check("live inspection is off", features.get("live_inspection") is False, str(features))

    conn = alice.post(
        f"{API}/connections",
        json={"name": "x", "host": "10.0.0.5", "port": 5432, "dbname": "d", "username": "u",
              "password": "not-a-real-password", "sslmode": "require",
              "environment": "development", "purpose": "inspection"},
    )  # fmt: skip
    p.check("creating a live connection is refused", conn.status_code in (403, 404, 422)
            and _code(conn) in ("FEATURE_DISABLED", "VALIDATION_ERROR", "NOT_FOUND"),
            f"{conn.status_code} {_code(conn)}")  # fmt: skip

    sandbox = alice.post(
        f"{API}/investigations",
        json={"title": "t", "objective": "o", "modes": ["sandbox_benchmark"], "query": QUERY,
              "workload_id": "orders_ecommerce@v1:sf=0.1:seed=42"},
    )  # fmt: skip
    p.check("a sandbox investigation is refused", sandbox.status_code >= 400
            and _code(sandbox) not in ("CSRF_FAILED", "UNAUTHENTICATED"),
            f"{sandbox.status_code} {_code(sandbox)}")  # fmt: skip

    offline = alice.post(
        f"{API}/investigations",
        json={"title": "t", "objective": "why slow", "modes": ["offline"], "query": QUERY},
    )
    p.check(
        "no shared model key: an LLM run needs the visitor's own key",
        offline.status_code >= 400 and "own" in offline.text.lower(),
        f"{offline.status_code} {_code(offline)} {offline.text[:120]}",
    )

    metrics = anon.get(f"{API}/internal/metrics")
    p.check("metrics are hidden without the token", metrics.status_code == 404,
            str(metrics.status_code))  # fmt: skip
    docs = anon.get(f"{API}/docs")
    p.check("interactive docs are not served", docs.status_code == 404, str(docs.status_code))

    mallory = _session(base, probe.web_origin)
    listing = mallory.get(f"{API}/investigations")
    items = listing.json().get("items", []) if listing.status_code == 200 else []
    p.check("another visitor sees no investigations of others", listing.status_code == 200
            and not items, f"{listing.status_code} {len(items)}")  # fmt: skip
    foreign = mallory.get(f"{API}/investigations/00000000-0000-4000-8000-000000000000")
    p.check("an unknown or foreign investigation is 404", foreign.status_code == 404,
            str(foreign.status_code))  # fmt: skip

    evil = anon.options(
        f"{API}/me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    good = anon.options(
        f"{API}/me",
        headers={"Origin": probe.web_origin, "Access-Control-Request-Method": "GET"},
    )
    p.check(
        "CORS refuses other origins",
        evil.headers.get("access-control-allow-origin") is None,
        str(evil.headers.get("access-control-allow-origin")),
    )
    p.check("CORS allows the web origin with credentials",
            good.headers.get("access-control-allow-origin") == probe.web_origin
            and good.headers.get("access-control-allow-credentials") == "true",
            str(good.headers.get("access-control-allow-origin")))  # fmt: skip

    headers = me.headers
    p.check("security headers are set",
            headers.get("x-content-type-options") == "nosniff"
            and headers.get("x-frame-options") == "DENY"
            and "max-age=" in headers.get("strict-transport-security", ""),
            "")  # fmt: skip

    no_csrf = httpx.Client(base_url=base, headers={"Cookie": alice.headers.get("Cookie", "")})
    forged = no_csrf.post(f"{API}/auth/logout")
    p.check("a mutation without the CSRF token is refused", forged.status_code == 403,
            f"{forged.status_code} {_code(forged)}")  # fmt: skip

    bad = alice.get(f"{API}/investigations/not-a-uuid")
    leak = any(word in bad.text for word in ("Traceback", 'File "', "sqlalchemy", "psycopg"))
    p.check("errors use the envelope and leak no internals",
            bad.status_code == 422 and _code(bad) != "" and not leak,
            f"{bad.status_code} {_code(bad)}")  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m querycure.ops.demo_probe")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--web-origin", required=True)
    args = parser.parse_args(argv)
    probe = Probe(base_url=args.base_url.rstrip("/"), web_origin=args.web_origin)
    run(probe)
    width = max(len(n) for n, _, _ in probe.results)
    show: Callable[[str], None] = print
    for name, ok, detail in probe.results:
        show(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail if not ok else ''}")
    failed = sum(not ok for _, ok, _ in probe.results)
    show(f"\n{len(probe.results) - failed}/{len(probe.results)} demo restrictions verified")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
