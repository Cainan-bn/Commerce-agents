# 0001. Registrar decisões arquiteturais com ADRs (MADR)

- Status: Accepted
- Data: 2026-11-05

## Contexto e problema

O projeto é um case de portfólio. A rastreabilidade das decisões é um entregável, e três agentes autônomos trabalham em paralelo. Sem registro, decisões se perdem e contratos mudam sem revisão.

## Direcionadores

- Rastreabilidade para revisores externos.
- Mudança de contrato deve passar pelo Líder.
- Baixo custo de manutenção.

## Opções consideradas

1. ADRs em Markdown no repositório (formato MADR).
2. Wiki externa.
3. Sem registro formal.

## Decisão

Opção 1. ADRs ficam em `docs/adr/NNNN-titulo.md`, numerados em sequência, com status `Proposed | Accepted | Superseded by NNNN`. ADR vem **antes** da implementação que justifica (commit anterior no `git log`). Mudança de contrato exige ADR novo ou revisão do existente.

## Consequências

- Positivas: história de decisões versionada junto ao código; revisão via PR.
- Negativas: custo de escrita. Mitigado com ADRs curtos.
