# 0020. Distribuição sem servidor e modo demonstração

- Status: Accepted
- Data: 2026-11-10
- Refina: ADR 0014, 0015, 0016, 0019

## Contexto e problema

A Fase 10 entrega a versão 1.0.0. O projeto é um case de portfólio: não há orçamento para
servidor nem para chave de API de LLM, e quem avalia o repositório precisa conseguir ver o sistema
funcionando sem nenhum dos dois. Hoje:

- o único transporte de LLM usado é o cliente `opencode` autenticado na máquina do autor (ADR 0015),
  que não roda num servidor nem na máquina de outra pessoa;
- o canal web espera uma sessão assinada pelo site da loja (ADR 0014); não existe página de chat
  para o cliente;
- a imagem Docker não tem entrypoint; não há compose de produção nem publicação de imagens;
- o ADR 0019 deixou a escala por partições e réplicas para esta fase.

## Opções consideradas

1. Hospedar a stack completa num plano gratuito (PaaS ou VM gratuita): Postgres, Redpanda e o
   collector não cabem na memória desses planos, e o serviço hiberna ou cai quando alguém visita.
2. Publicar só as imagens (GHCR) e um modo demonstração que roda localmente ou no Codespaces de quem
   visita, sem chave de API.
3. Exigir que quem visita traga a própria chave de LLM.

## Decisão

Opção 2, com a 3 como alternativa opcional.

- Imagens: `ghcr.io/<dono>/commerce-agents` (API, worker e loja fake na mesma imagem, comando por
  serviço), publicadas por workflow na tag `v*`, com varredura Trivy (falha em CRITICAL corrigível).
  Imagem pública e gratuita.
- `docker-compose.prod.yml`: API (uvicorn com `API_WORKERS` processos), worker com
  `WORKER_REPLICAS` réplicas no mesmo grupo de consumo, job de migração antes da aplicação, job de
  criação dos tópicos com `KAFKA_PARTITIONS` partições (a chave `conversation_id` mantém a ordem
  por conversa; ADR 0019), loja fake, Postgres, Redpanda e stack de observabilidade.
  Healthchecks e `depends_on` com condição em todos.
- Modo demonstração (`DEMO_MODE=true`, desligado por padrão, nunca em produção real):
  - LLM gravado: provider `LLM_PROVIDER=recorded` em `infrastructure/llm/`, que lê um cassete de
    conversas de demonstração gravadas com o modelo real (`make demo-record`, só o autor, mesmo
    formato do ADR 0016). Chave ausente não é erro: devolve um texto fixo que diz que está em modo
    demonstração e sugere as mensagens gravadas. Diferente do `ReplayProvider` do eval, que falha
    em chave ausente de propósito. O RAG de políticas roda de verdade (embeddings locais).
  - Página `/demo` servida pela API só com `DEMO_MODE=true`: escolhe um cliente do seed, recebe
    uma sessão web assinada pelo próprio servidor e conversa pelo canal web real (webhook,
    Redpanda, worker, grafo, outbox, WebSocket). Mostra as mensagens sugeridas. Com
    `DEMO_MODE=false` a rota não existe (404) e nenhum endpoint emite sessão.
  - `make demo`: sobe o compose de produção com o modo demonstração, aplica migrações, carrega o
    seed e as políticas e imprime as URLs (demo, painel humano, Grafana, Jaeger).
  - Com `LLM_PROVIDER=openai-compatible` e uma chave da própria pessoa, o mesmo `make demo` usa
    um LLM real (opção 3).
- Codespaces: `.devcontainer/` com Docker-in-Docker e as portas encaminhadas, para rodar o
  `make demo` no navegador dentro da cota gratuita de quem visita.
- Smoke test no CI: sobe o compose de produção em modo demonstração, roda uma conversa gravada de
  ponta a ponta pelo canal web e confere a resposta, o handoff para o painel e o trace.
- Não há workflow de deploy para servidor; o "deploy" verificável é a imagem publicada mais o
  smoke test.

## Consequências

- Positivas: qualquer pessoa vê o sistema funcionando, sem custo para ninguém; o caminho de
  produção (imagens, migração como job, partições, réplicas) fica pronto e testado.
- Negativas: a demonstração só responde bem às mensagens gravadas; mudar prompt exige regravar
  também o cassete da demonstração; a rota `/demo` emite sessão para qualquer cliente do seed, e
  por isso só existe com a flag (teste garante 404 sem ela); não há ambiente público no ar.
