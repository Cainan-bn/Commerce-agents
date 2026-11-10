# syntax=docker/dockerfile:1

# Uma imagem para api, worker, mock-store, migrate e seed (ADR 0020); o serviço é o argumento
# do entrypoint (docker/app/entrypoint.sh).

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Modelo de embeddings (ADR 0012) numa camada própria: o container não precisa de rede na
# primeira conversa, e a camada só muda quando muda o modelo.
FROM builder AS embeddings

ENV FASTEMBED_CACHE_PATH=/opt/fastembed

RUN /app/.venv/bin/python -c "from fastembed import TextEmbedding; \
from commerce_agents.infrastructure.rag.embedder import DEFAULT_MODEL_NAME; \
TextEmbedding(model_name=DEFAULT_MODEL_NAME)"

FROM python:3.12-slim AS runtime

# Correções de segurança da base (Trivy no CI e no release).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /app app

WORKDIR /app

COPY --from=embeddings --chown=app:app /opt/fastembed /opt/fastembed
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src
COPY --chown=app:app mock_store ./mock_store
COPY --chown=app:app scripts/load_seed.py ./scripts/load_seed.py
COPY --chown=app:app data/seed ./data/seed
COPY --chown=app:app data/policies ./data/policies
COPY --chown=app:app data/demo ./data/demo
COPY --chown=app:app panel/index.html ./panel/index.html
COPY --chown=app:app panel/src ./panel/src
COPY --chown=app:app --chmod=0755 docker/app/entrypoint.sh /usr/local/bin/entrypoint

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    HF_HUB_OFFLINE=1

USER app

EXPOSE 8000 8001

# Vale para o serviço padrão (api); o compose desliga ou troca para os demais.
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

ENTRYPOINT ["entrypoint"]
CMD ["api"]
