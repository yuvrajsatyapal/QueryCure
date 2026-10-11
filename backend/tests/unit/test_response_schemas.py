"""Response models must never expose secret fields (API_DESIGN §5)."""

import re

from querycure.api.main import create_app
from querycure.core.config import Settings

FORBIDDEN = re.compile(r"password|secret|token|api_key|ciphertext|nonce|master_key", re.IGNORECASE)
# Exact names that match the pattern but are not secrets: a flag and LLM token *counts*.
ALLOWED = {"has_password", "total_tokens", "input_tokens", "output_tokens"}


def test_no_response_schema_has_secret_fields() -> None:
    doc = create_app(Settings(_env_file=None), engine=None).openapi()
    response_schemas = {
        name: schema
        for name, schema in doc["components"]["schemas"].items()
        if not name.endswith("Request") and name not in {"HTTPValidationError", "ValidationError"}
    }

    offenders = [
        f"{name}.{field}"
        for name, schema in response_schemas.items()
        for field in schema.get("properties", {})
        if FORBIDDEN.search(field) and field not in ALLOWED
    ]

    assert response_schemas, "expected some response schemas"
    assert offenders == []
