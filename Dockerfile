FROM python:3.12-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
COPY grip/ grip/

RUN uv sync --no-dev

FROM python:3.12-slim

WORKDIR /app

COPY --from=base /app /app
COPY --from=base /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=base /usr/local/bin /usr/local/bin

ENV PATH="/app/.venv/bin:$PATH"

RUN mkdir -p /root/.grip

EXPOSE 18800

ENTRYPOINT ["grip", "gateway", "--host", "0.0.0.0"]
