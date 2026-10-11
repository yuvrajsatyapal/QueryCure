# ADR-0012: BYOK keys and connection passwords encrypted with AES-256-GCM under an environment master key

- Status: Accepted (2026-10-11)
- Area: Security

## Context
Users bring their own LLM keys and database passwords. Investigations run asynchronously in the worker (minutes later, possibly after a restart), so secrets must be retrievable server-side.

## Alternatives
1. Keep keys only in the browser and send per request — the async worker can't use them after the request ends.
2. Store plaintext — unacceptable.
3. **Encrypt at rest with AES-256-GCM, master key from env/secret store, per-row random nonce, associated data binding the ciphertext to its row and user, `key_version` for rotation.**
4. Cloud KMS envelope encryption — best practice for production; adds a cloud dependency and cost.

## Decision
Option 3 for MVP; option 4 noted as the production upgrade path.

## Rationale & trade-offs
- + Works with async workers; stolen DB dump alone doesn't reveal secrets.
- − Master key compromise exposes all secrets; mitigate with host secret store, rotation job, and minimal plaintext lifetime.

## Consequences
Secrets never enter graph state, events, logs, or responses; only `key_hint` is displayed. Deleting a key nulls ciphertext immediately (hard delete of the secret material).
