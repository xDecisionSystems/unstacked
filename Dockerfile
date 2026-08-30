# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

# Pinned to match .github/workflows/ci.yml so the image being deployed was
# built with the same resolver used to verify it.
RUN pip install --disable-pip-version-check --no-cache-dir 'uv==0.10.11'

WORKDIR /app
# README.md is required here, not just for docs: pyproject.toml declares
# readme = "README.md", so hatchling (the build backend) fails to build the
# project's own metadata without it, once the project itself is installed
# below.
COPY pyproject.toml uv.lock README.md ./
# Dependencies only, in their own layer, so an app-code-only change doesn't
# reinstall the whole environment.
RUN uv sync --locked --no-install-project --no-dev

COPY app ./app
RUN uv sync --locked --no-dev


FROM python:3.12-slim AS runtime

# GitPython shells out to the real `git` binary at import time; python-slim
# does not include it, so every request would fail immediately without this.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system unstacked && useradd --system --gid unstacked --create-home unstacked

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app
# The commit this image was built from, for GET /version -- lets an operator
# confirm a redeploy actually picked up a given push instead of assuming it.
# `.git` is excluded from the build context entirely (see .dockerignore) and
# isn't needed here: Coolify supplies the real commit itself as the
# SOURCE_COMMIT build arg (off by default there, to preserve layer caching --
# enable "Include Source Commit in Build" under the app's Advanced settings).
# A plain `docker build` without that arg just gets "unknown", same as
# running the app outside Docker entirely.
ARG SOURCE_COMMIT=unknown
RUN echo "${SOURCE_COMMIT}" > /app/GIT_COMMIT
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    UNSTACKED_CONTENT_REPO_PATH=/app/content \
    UNSTACKED_DB_PATH=/app/data/app.db \
    UNSTACKED_CONTENT_LOCK_PATH=/app/data/content.lock \
    UNSTACKED_API_TOKEN_SECRET_PATH=/app/data/api_token_secret \
    UNSTACKED_STATIC_EXPORT_PATH=/app/data/static-export

# The content/ (Git-backed wiki) and data/ (SQLite + lock file + generated
# secret) directories are the only application state and must be mounted as
# persistent volumes. Pre-creating them here, owned by the runtime user,
# means Docker seeds a fresh named volume with correct ownership on first
# start instead of leaving it root-owned.
RUN mkdir -p /app/content /app/data && chown -R unstacked:unstacked /app/content /app/data
VOLUME ["/app/content", "/app/data"]

USER unstacked
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1

# A single worker matches the project's concurrency model: one file lock
# serializes Git mutations, and running more than one worker would call the
# startup migration/bootstrap logic in create_app() more than once.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
