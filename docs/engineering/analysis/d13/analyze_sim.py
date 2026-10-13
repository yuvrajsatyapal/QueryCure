"""Tabulate sim.json: P(verified) per noise model x schedule x effect, for bench@2 and each
safeguard (applied on top of a clean bench@2 `verified`). Also P(any verification) including
the ADR-0019 noise-warning path. Output: markdown tables."""

import collections
import json
import sys

RULES = ["bench2", "all_blocks>=1.0", "all_blocks>=min", "sign_test", "paired_t>=1.0", "paired_t>=min",
         "blockboot>=1.0", "blockboot>=min"]


def rate(rows, rule):
    k = 0
    for r in rows:
        if r["v"] == "verified":
            keep = r["keep"]
            name = rule if rule in keep else rule
            if rule.endswith("@pool5") and rule not in keep:
                name = rule[: -len("@pool5")]
            k += bool(keep[name])
    return k / len(rows)


def main() -> None:
    cells = json.load(open(sys.argv[1]))
    by = collections.defaultdict(dict)
    for c in cells:
        by[(c["noise"], c["schedule"])][c["effect"]] = c["rows"]
    effects = sorted({c["effect"] for c in cells})
    noises = list(dict.fromkeys(c["noise"] for c in cells))
    scheds = list(dict.fromkeys(c["schedule"] for c in cells))
    n = cells[0]["n"]
    print(f"n = {n} simulated experiments per cell; values are % verified (clean path)\n")
    for nz in noises:
        print(f"### {nz}\n")
        print("| schedule | rule | " + " | ".join(f"{e:g}x" for e in effects) + " |")
        print("|---|---|" + "---|" * len(effects))
        for sc in scheds:
            rules = RULES if sc.startswith("bs5") else RULES + [r + "@pool5" for r in RULES[1:]]
            for rule in rules:
                vals = [100 * rate(by[(nz, sc)][e], rule) for e in effects]
                print(f"| {sc} | {rule} | " + " | ".join(f"{v:.1f}" for v in vals) + " |")
            nw = [100 * sum(1 for r in by[(nz, sc)][e] if r.get("noise_warning")) / n for e in effects]
            print(f"| {sc} | (+noise_warning path, bench2) | " + " | ".join(f"{v:.1f}" for v in nw) + " |")
        print()


if __name__ == "__main__":
    main()
