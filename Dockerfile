FROM python:3.12-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY grip/ grip/

RUN uv sync --no-dev

FROM python:3.12-slim

WORKDIR /app

# Install Node.js (required by Claude Agent SDK for the underlying CLI)
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=base /app /app
COPY --from=base /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=base /usr/local/bin /usr/local/bin

ENV PATH="/app/.venv/bin:$PATH"

RUN groupadd --gid 1000 grip \
    && useradd --uid 1000 --gid grip --create-home grip \
    && mkdir -p /home/grip/.grip \
    && chown -R grip:grip /home/grip/.grip /app

USER grip

EXPOSE 18800

ENTRYPOINT ["grip", "gateway", "--host", "127.0.0.1"]
