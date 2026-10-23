"""In-process counters for what the metadata database cannot record (OBSERVABILITY §0).

The rest of `/internal/metrics` is computed from tables, so it survives restarts and covers
every worker. Responses, unhandled errors and SSE stream outcomes exist only in the API
process, so they are counted here: per process, reset on restart (`qc_process_uptime_seconds`
lets an alert rule tell a reset from a drop). The demo runs one API process, so per-process is
the whole picture. Labels are fixed sets, never paths or IDs, to keep cardinality bounded.
"""

import time
from collections import Counter
from typing import Literal

StatusClass = Literal["1xx", "2xx", "3xx", "4xx", "5xx"]
# ended: the run reached a terminal status, or was gone; client_gone: the browser disconnected;
# error: a server-side failure after the response had started (logged as sse_stream_failed).
SseOutcome = Literal["ended", "client_gone", "error"]

STATUS_CLASSES: tuple[StatusClass, ...] = ("1xx", "2xx", "3xx", "4xx", "5xx")
SSE_OUTCOMES: tuple[SseOutcome, ...] = ("ended", "client_gone", "error")


class ProcessMetrics:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.responses: Counter[str] = Counter()
        self.unhandled_errors = 0
        self.sse_active = 0
        self.sse_closed_by: Counter[str] = Counter()

    def response(self, status: int) -> None:
        self.responses[f"{min(max(status // 100, 1), 5)}xx"] += 1

    def unhandled_error(self) -> None:
        self.unhandled_errors += 1

    def sse_opened(self) -> None:
        self.sse_active += 1

    def sse_closed(self, outcome: SseOutcome) -> None:
        self.sse_active -= 1
        self.sse_closed_by[outcome] += 1

    def render(self) -> list[str]:
        return [
            "# HELP qc_process_uptime_seconds Seconds since this API process started.",
            "# TYPE qc_process_uptime_seconds gauge",
            f"qc_process_uptime_seconds {time.monotonic() - self.started:.0f}",
            "# HELP qc_http_responses_total API responses by status class (this process).",
            "# TYPE qc_http_responses_total counter",
            *(
                f'qc_http_responses_total{{status_class="{c}"}} {self.responses[c]}'
                for c in STATUS_CLASSES
            ),
            "# HELP qc_http_unhandled_errors_total Unexpected exceptions answered with a 500.",
            "# TYPE qc_http_unhandled_errors_total counter",
            f"qc_http_unhandled_errors_total {self.unhandled_errors}",
            "# HELP qc_sse_streams_active Open run event streams.",
            "# TYPE qc_sse_streams_active gauge",
            f"qc_sse_streams_active {self.sse_active}",
            "# HELP qc_sse_streams_closed_total Closed run event streams by outcome.",
            "# TYPE qc_sse_streams_closed_total counter",
            *(
                f'qc_sse_streams_closed_total{{outcome="{o}"}} {self.sse_closed_by[o]}'
                for o in SSE_OUTCOMES
            ),
        ]
