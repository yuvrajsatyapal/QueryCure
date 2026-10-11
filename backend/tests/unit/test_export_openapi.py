import json

import pytest

from querycure.api.export_openapi import main


def test_export_prints_openapi_with_health_route(capsys: pytest.CaptureFixture[str]) -> None:
    main()

    doc = json.loads(capsys.readouterr().out)
    assert doc["info"]["title"] == "QueryCure"
    assert "/api/v1/healthz" in doc["paths"]
