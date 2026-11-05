## Objetivo
Entregar o ambiente de desenvolvimento reproduzível em WSL2: bootstrap, Makefile, projeto Python com lint/tipos/import-linter, stack Docker local e CI.

## Task Cards cobertos
- TASK-01-01 bootstrap WSL2, Makefile, editorconfig, pre-commit (OPS)
- TASK-01-02 pyproject, ruff, mypy --strict, pytest, import-linter (OPS)
- TASK-01-03 docker-compose da stack local (OPS)
- TASK-01-04 CI no GitHub Actions e Dockerfile mínimo (OPS)

## ADRs criados
Nenhum (fase de infraestrutura; decisões já cobertas pelos ADRs 0002, 0005 e 0006).

## Como verificar
```bash
bash scripts/bootstrap_wsl2.sh && make doctor
make setup && make lint && make test
make up   # requer Docker com integração WSL2
```

## Métricas
- `make lint`: ruff, format, `mypy --strict` e 3 contratos import-linter verdes (enforcement provado com import proibido temporário).
- `make test`: 14 testes, cobertura de branch 100% da suíte de fumaça.

## Desvios e riscos
- Langfuse v3 exige ClickHouse, S3 e worker; foram adicionados como serviços extras, mantendo os seis nomes contratados.
- `make up` e `docker build` ainda não foram executados em máquina com Docker; validação pendente do Líder antes do merge.
- Alvos `seed`, `migrate`, `test-e2e`, `eval`, `load` e `run` são stubs até as fases correspondentes.
