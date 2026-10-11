Fixed, parameterized catalog queries for the inspection gateway (SECURITY.md §4.1 L2).
Never format values into these files; pass them as psycopg `%(name)s` parameters.
Statistics redaction (T1.11): never select value-bearing columns from pg_stats
(`most_common_vals`, `most_common_elems`, `histogram_bounds`, `*_freqs`) — they hold real data.
`%%` is a literal percent sign because every template is executed with a parameter dict.
