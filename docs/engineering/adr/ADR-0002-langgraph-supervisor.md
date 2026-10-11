# ADR-0002: LangGraph supervisor graph with deterministic nodes and bounded specialist agents

- Status: Accepted (2026-10-11)
- Area: Agents

## Context
The product must behave like a team of engineers (planning, parallel analysis, proposals, verification loops, human approval) while being debuggable, resumable, and safe.

## Alternatives
1. **Single ReAct agent with many tools** — least code; opaque control flow, hard to bound, hard to evaluate per role.
2. **Free-form multi-agent chat** (agents message each other) — expressive; nondeterministic, token-heavy, hard to test.
3. **Explicit LangGraph StateGraph**: deterministic nodes for computable work, LLM specialist nodes with typed outputs, supervisor for planning/synthesis, conditional routing, `Send` fan-out, Postgres checkpointing, `interrupt` for approval.
4. **Custom orchestrator** — full control; re-implements checkpointing and HITL.

## Decision
Option 3. LangChain only for model integration and structured output.

## Rationale & trade-offs
- + Control flow is code: testable routing functions, explicit termination.
- + Built-in checkpointing and interrupts match crash recovery and approvals.
- + Specialists have narrow tools → smaller attack surface and clearer evals.
- − LangGraph API churn; mitigated by pinning versions and isolating graph assembly in `agents/graph.py`.
- − More upfront design than a single agent.

## Consequences
Agents exchange Pydantic models via state; no agent-to-agent chat. Not every run invokes every agent.
