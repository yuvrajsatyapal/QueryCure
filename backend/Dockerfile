# One image for the API, the worker and the migration step (DEPLOYMENT §2, §7).
#   worker (default):  python -m querycure.worker
#   api:               uvicorn querycure.api.main:app --host 0.0.0.0 --port 8000
#   migrations:        alembic upgrade head   (owner role, run once before new app instances)
# Locally the worker joins sandbox_net so benchmark round trips stay inside the Docker network
# instead of crossing the host↔VM port forward (ADR-0018 evidence).
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv

ENV TZ=UTC PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock README.md* ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
# Readiness compares the database with the migration head; the release step runs Alembic.
COPY alembic.ini ./
COPY migrations ./migrations
# Prerecorded benchmark fixtures shown by the public demo gallery (labelled, never re-run).
COPY evals/fixtures/experiments ./evals/fixtures/experiments
RUN uv sync --locked --no-dev && useradd --system --uid 10001 qc
USER qc
# SIGTERM drains in-flight jobs for WORKER_SHUTDOWN_GRACE_SECONDS, then abandons them to lease
# expiry; give the platform's stop timeout a little more than that.
STOPSIGNAL SIGTERM
CMD ["python", "-m", "querycure.worker"]
