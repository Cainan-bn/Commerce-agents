#!/bin/sh
# Entrypoint único da imagem (ADR 0020): o mesmo artefato roda cada serviço do compose.
#   api         uvicorn com API_WORKERS processos (padrão 2) na porta API_PORT (8000)
#   worker      pipeline de mensagens (modo: all, inbound, relay, sender ou purge)
#   mock-store  loja fake na porta MOCK_STORE_PORT (8001)
#   migrate     alembic upgrade head
#   seed        carga idempotente de data/seed e indexação de data/policies
# Qualquer outro comando é executado como está (ex.: python -m ...).
set -eu

command=${1:-api}
[ "$#" -gt 0 ] && shift

case "$command" in
  api)
    exec uvicorn commerce_agents.interfaces.main:app --host 0.0.0.0 \
      --port "${API_PORT:-8000}" --workers "${API_WORKERS:-2}" --proxy-headers "$@"
    ;;
  worker)
    exec python -m commerce_agents.interfaces.worker "${1:-all}"
    ;;
  mock-store)
    exec uvicorn mock_store.main:app --host 0.0.0.0 --port "${MOCK_STORE_PORT:-8001}"
    ;;
  migrate)
    exec python -c "from commerce_agents.infrastructure.persistence.migrate import \
sync_url_from_env, upgrade_to_head; upgrade_to_head(sync_url_from_env())"
    ;;
  seed)
    python scripts/load_seed.py --data-dir data/seed
    exec python -m commerce_agents.infrastructure.rag ingest
    ;;
  *)
    exec "$command" "$@"
    ;;
esac
