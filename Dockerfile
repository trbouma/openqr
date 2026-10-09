FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv

WORKDIR /build
COPY pyproject.toml poetry.lock README.md /build/
RUN pip install poetry \
    && poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi \
    && /opt/venv/bin/gunicorn --version

FROM python:3.11-slim-bookworm AS runtime

ARG OPENQR_GIT_COMMIT=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    OPENQR_GIT_COMMIT=${OPENQR_GIT_COMMIT}

RUN groupadd --gid 10001 openqr \
    && useradd --uid 10001 --gid 10001 --no-create-home openqr

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app /app/app

RUN /opt/venv/bin/gunicorn --check-config app.main:app -k uvicorn.workers.UvicornWorker

USER openqr
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import json, urllib.request; response = json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); assert response.get('status') == 'ok'"

CMD ["/opt/venv/bin/gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--worker-tmp-dir", "/tmp"]
