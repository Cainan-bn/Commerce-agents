## Objetivo
Entregar a versão 1.0.0 sem servidor e sem chave de API: imagem de produção publicada no GHCR com varredura Trivy, compose de produção com migração e tópicos como jobs, partições e réplicas, modo demonstração com respostas reais gravadas, devcontainer para Codespaces, smoke test de ponta a ponta no CI e README como case.

## Task Cards cobertos
- Líder: ADR 0020 (+ adendo), roteiro `data/demo/conversations.yaml`, gravação e verificação do cassete da demonstração, README final.
- TASK-10-01 modo demonstração: provider `recorded`, rotas `/demo` só com `DEMO_MODE`, página de demonstração (OPS red / CORE green).
- TASK-10-02 imagem com entrypoint por serviço e modelo de embeddings embutido; `docker-compose.prod.yml` (migrate, topics, seed como jobs; 3 partições; 2 workers; API com 2 processos); `release.yml` com Trivy e push no GHCR na tag; Trivy no CI.
- TASK-10-03 gravador do LLM (`LLM_RECORD_TO`), driver de conversas, `make demo-record`/`demo-verify`/`demo`/`demo-down`/`demo-reset`, `.devcontainer/`, job de smoke no CI.
- TASK-10-07 token de sessão mascarado nos logs de acesso.
- TASK-10-08 GIFs e capturas (respostas reais gravadas).
- TASK-10-09 chamada fora do roteiro visível (aviso, sem handoff) e verificação pelo contador no Prometheus; teste de regressão com o cassete real.

## ADRs
- 0020 Distribuição sem servidor e modo demonstração (+ adendo).

## Como verificar
```bash
make lint && make test-unit && make test-integration && make eval-ci
make demo            # http://localhost:8000/demo, painel, Grafana, Jaeger
make demo-down
make demo-verify     # stack de produção, 5 conversas, falha se houver chamada fora do cassete
```

## Métricas
- Demonstração na stack de produção: 5 conversas, 7 mensagens, 0 chamadas fora do cassete; prova negativa (repetir sem reiniciar a loja) falha pelo contador (0 → 2), como esperado.
- Imagem: 1,2 GB (venv 419 MB + modelo de embeddings 252 MB); funciona sem rede; usuário sem privilégios; Trivy sem CRITICAL/HIGH corrigível.
- Compose de produção: tópico com 3 partições dividido entre 2 workers; API com 2 processos; trace único de 21 spans do webhook ao envio.
- 1237 testes unitários; mypy --strict e contratos import-linter verdes; eval-ci com os cassetes inalterados.

## Defeitos achados na revisão
1. `fastapi`, `uvicorn` e `pyyaml` declarados só como dependências de desenvolvimento: a imagem de produção não subiria.
2. Token da sessão web inteiro no log de acesso do uvicorn.
3. Chamada fora do cassete virava handoff `saida_invalida_do_llm` e passava pela verificação.
4. `demo-verify` reaproveitava volumes de execuções anteriores (senha diferente, migração falhando).
5. `demo-record` não subia a loja fake.
6. Cache do mypy do hook de pre-commit conflitando com o do `make lint`.

## Riscos / pendências
- Demonstração só responde bem ao roteiro gravado; mudar prompt ou ferramenta exige regravar o cassete da demonstração (e ajustar o teste de regressão que o usa).
- Sem ambiente público no ar (decisão do ADR 0020).
- Pós-v1: lacunas do agente vistas no holdout, contrato AMB, oferta de "preparar o pedido" sem ferramenta, provider de LLM de produção, escala medida com mais de uma máquina.
