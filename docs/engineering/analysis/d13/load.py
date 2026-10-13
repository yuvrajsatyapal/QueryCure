"""Intermittent competing load on the sandbox server: ~1.5 s busy, ~2.5 s idle, forever."""

import random
import time

import psycopg

URL = "postgresql://qc_sandbox_admin:qc_local_dev_only@127.0.0.1:55432/sandbox_admin"
rng = random.Random(7)
with psycopg.connect(URL, autocommit=True) as conn:
    while True:
        end = time.monotonic() + rng.uniform(1.0, 2.0)
        while time.monotonic() < end:
            conn.execute("SELECT count(*) FROM generate_series(1, 300000) g WHERE md5(g::text) LIKE 'a%'")
        time.sleep(rng.uniform(1.5, 3.5))
