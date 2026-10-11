# Canonicalization golden vectors (REPLAY_ENGINE §2.4)

These files freeze the output of each canonicalization profile. **Never edit an existing vector**: a
changed output means a new profile ID (`qd-json-v2`, …), not a fix.

- `rfc8785_numbers.json` — RFC 8785 Appendix B number serialization table.
- `qd_json_v1.json`, `qd_text_v1.json`, `qd_raw_v1.json` — `canonical` strings written by hand from
  the spec; `digest` values computed with plain `hashlib` over `profile + LF + canonical`, independent
  of the implementation under test.
