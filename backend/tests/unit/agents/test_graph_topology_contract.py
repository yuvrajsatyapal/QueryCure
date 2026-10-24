"""The web graph view draws the investigation graph from a JSON copy of its topology; this
keeps that copy identical to the compiled LangGraph (nodes, edges, conditional flags)."""

import json
from pathlib import Path

from querycure.agents.graph import compile_graph

TOPOLOGY = Path(__file__).resolve().parents[4] / "frontend/src/lib/trace/langgraph-topology.json"


def test_frontend_topology_matches_the_compiled_graph() -> None:
    graph = compile_graph().get_graph()
    recorded = json.loads(TOPOLOGY.read_text())

    assert recorded["nodes"] == sorted(graph.nodes)
    assert recorded["edges"] == [
        {"source": e.source, "target": e.target, "conditional": bool(e.conditional)}
        for e in sorted(graph.edges, key=lambda e: (e.source, e.target))
    ]
