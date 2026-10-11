# Plan fixtures

`synthetic_*.json` files are **hand-written** in PostgreSQL's `EXPLAIN (FORMAT JSON)` shape with round
numbers, so expected metrics can be computed by hand in the tests. They are not measurements of any
database and must never be presented as such.

Real captures (`pg17_*.json`, …) are added from the local Docker PostgreSQL once it is available.
