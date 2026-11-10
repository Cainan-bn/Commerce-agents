# 0019. Resultados de carga e caos da Fase 09 e decisões sobre os gargalos

- Status: Accepted
- Data: 2026-11-10
- Refina: ADR 0017, 0018

## Contexto e problema

A Fase 09 tinha quatro metas (`docs/architecture/quality-targets.md`): p95 sem LLM < 150 ms,
primeira resposta com LLM < 4 s no p95, queda do provider não derruba o atendimento e 100% das
conversas com trace. A medição está em `load/reports/20261110-fase09.md` (commit medido `79b45d7`,
máquina de 2 núcleos e 3,9 GB, k6 na mesma máquina, LLM simulado a ~800 ms).

| Meta | Medido | Situação |
|---|---|---|
| Webhook p95 < 150 ms | 24,5 ms a 38 req/s; 89,6 ms a 88 req/s; 201,7 ms a 148 req/s | cumpre até ~88 req/s com um processo |
| Primeira resposta p95 < 4 s | 3,10 s (k6); turno p95 2,96 s (Prometheus) | cumpre |
| Queda do provider | 0 mensagens sem resposta e 0 respostas 5xx; 23 handoffs sem secundário; 90 respostas pelo secundário com fallback | cumpre |
| Trace por conversa | um trace com os 8 saltos, do webhook ao `channel.send` | cumpre |

Custo por conversa: o LLM simulado não tem preço. O último eval completo com o modelo real
(`reports/eval/20261110-003445-h3-frete.md`, `opencode-go/claude-haiku-5-5`, custo informado pelo
próprio provider) custou US$ 0,411 para 54 conversas, cerca de **US$ 0,0076 por conversa**
(roteador + especialista; inclui uma reexecução por erro de infraestrutura).

Durante a queda do primário, a cauda de latência foi alta: p95 15,2 s sem secundário e 30,9 s com
secundário. Três gargalos explicam os números:

1. Cada chamada ao primário caído só falha depois das novas tentativas do adaptador
   (`max_retries=3` com backoff, ~8 s). O breaker conta uma falha por chamada, então abre só após
   ~40 s, e cada sonda do meio-aberto custa de novo ~8 s. Com secundário, toda chamada paga esses
   ~8 s antes de passar ao secundário; por isso a cauda com fallback é pior que sem.
2. O worker processa uma mensagem por vez, e o tópico `inbound.messages` tem uma partição: uma
   chamada lenta atrasa todas as conversas que estão na fila.
3. A API roda num único processo; acima de ~90 req/s, a CPU de um núcleo satura.

## Opções consideradas

Para o gargalo 1:

1. Manter as novas tentativas; aceitar ~40 s até abrir o circuito.
2. Contar no breaker cada tentativa, não cada chamada.
3. Tentar de novo só no último provider da cadeia: com secundário configurado, o primário não
   repete a chamada e falha na hora para o secundário; o secundário (ou o único provider) mantém
   as novas tentativas.

Para os gargalos 2 e 3: concorrência dentro do worker (exige controle de ordem por conversa no
código) ou escala horizontal por configuração (partições por `conversation_id`, já usado como
chave, e réplicas de worker e de API).

## Decisão

- Gargalo 1: opção 3. `build_resilient_llm` monta o primário com zero novas tentativas quando há
  secundário; o número de tentativas e o timeout por chamada passam a ser configuráveis por ambiente
  (`LLM_MAX_RETRIES`, `LLM_TIMEOUT_S`). A opção 2 misturaria a política de repetição com a do
  breaker; a 3 deixa cada decorador com uma responsabilidade. Card 09-08, com nova medição do caos
  com fallback.
- Gargalos 2 e 3: escala horizontal, na Fase 10 (deploy). Tópicos com N partições criados
  explicitamente, N réplicas do worker no mesmo grupo de consumo (a ordem por conversa continua
  garantida pela chave) e API com vários workers do uvicorn. Sem concorrência dentro do processo
  do worker: ela exigiria fila por conversa no código para manter a ordem, e a escala por partição
  resolve o mesmo problema sem código novo.
- Os números acima são o baseline de desempenho. A meta do webhook vale por processo da API; a
  vazão total cresce com réplicas.

## Consequências

- Positivas: com secundário, a queda do primário deixa de custar ~8 s por chamada; caminho de
  escala sem mudar o código de mensageria; custo por conversa com número medido.
- Negativas: sem secundário, o circuito continua levando ~40 s para abrir (as novas tentativas
  continuam valendo a pena quando não há alternativa); o custo por conversa vem do eval, não de
  tráfego real, e depende do preço informado pelo provider; a medição foi feita numa máquina
  pequena, com o gerador de carga dividindo CPU com a aplicação.

## Adendo (2026-11-10): remedição após o card 09-08

Caos com secundário, mesmos parâmetros, código `32f256b` (seção 6 de
`load/reports/20261110-fase09.md`): p95 30,85 s → 7,32 s; p99 37,11 s → 10,08 s; máximo
38,56 s → 11,03 s; circuito do primário abre 41,4 s → 7,3 s após a queda; requisições ao primário
caído 28 → 8; handoffs, mensagens sem resposta e respostas 5xx continuam em 0. Durante a queda o
p95 ainda passa de 4 s porque o worker processa uma mensagem por vez (gargalo 2, Fase 10).
