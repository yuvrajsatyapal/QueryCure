"""In-process counters for what the database cannot record: API responses by status class,
unhandled errors and SSE stream outcomes (OBSERVABILITY §0)."""

import httpx2 as httpx

from querycure.api.main import create_app
from querycure.api.process_metrics import ProcessMetrics
from querycure.core.config import Settings


def test_render_reports_every_series_with_zero_defaults() -> None:
    m = ProcessMetrics()
    text = "\n".join(m.render())
    assert 'qc_http_responses_total{status_class="5xx"} 0' in text
    assert "qc_http_unhandled_errors_total 0" in text
    assert "qc_sse_streams_active 0" in text
    assert 'qc_sse_streams_closed_total{outcome="error"} 0' in text
    assert "qc_process_uptime_seconds" in text


def test_sse_bookkeeping() -> None:
    m = ProcessMetrics()
    m.sse_opened()
    m.sse_opened()
    m.sse_closed("client_gone")
    text = "\n".join(m.render())
    assert "qc_sse_streams_active 1" in text
    assert 'qc_sse_streams_closed_total{outcome="client_gone"} 1' in text


async def test_responses_are_counted_by_status_class() -> None:
    app = create_app(Settings(_env_file=None), engine=None)
    metrics: ProcessMetrics = app.state.process_metrics
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/v1/healthz")).status_code == 200
        assert (await c.get("/api/v1/no-such-route")).status_code == 404
    assert metrics.responses["2xx"] == 1
    assert metrics.responses["4xx"] == 1
