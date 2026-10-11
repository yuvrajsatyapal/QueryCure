# Canonicalization golden vectors (REPLAY_ENGINE §2.4)

These files freeze the output of each canonicalization profile. **Never edit an existing vector**: a
changed output means a new profile ID (`qc-json-v2`, …), not a fix.

- `rfc8785_numbers.json` — RFC 8785 Appendix B number serialization table.
- `qc_json_v1.json`, `qc_text_v1.json`, `qc_raw_v1.json` — `canonical` strings written by hand from
  the spec; `digest` values computed with plain `hashlib` over `profile + LF + canonical`, independent
  of the implementation under test.
