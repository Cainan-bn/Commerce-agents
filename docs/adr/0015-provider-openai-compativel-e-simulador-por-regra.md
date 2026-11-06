# 0015. Providers de LLM (OpenAI-compatível e opencode CLI) e cliente simulado por regra

- Status: Accepted
- Data: 2026-11-06
- Refina: ADR 0007, 0009

## Contexto e problema

A Fase 08 precisa de um LLM real para o agente, o roteador e o juiz. O usuário escolheu "OpenAI ou outro via API" sem fixar um fornecedor. O ADR 0009 prevê um simulador de cliente por LLM, mas os 54 cenários já trazem as falas do cliente; o único comportamento dinâmico é confirmar uma ação irreversível quando o agente pedir.

## Opções consideradas

1. Adaptador específico por fornecedor (OpenAI, Anthropic, DeepSeek...).
2. Um adaptador para o protocolo `POST {base_url}/chat/completions` (OpenAI e compatíveis: DeepSeek, OpenRouter, Together, vLLM, Ollama).
3. Simulador de cliente por LLM para todos os turnos.

## Decisão

Opção 2 atrás do port `LLMProvider`: `OpenAICompatibleProvider(base_url, api_key, model, *, temperature=0, timeout, client)`. Configuração só por ambiente: `LLM_BASE_URL` (padrão `https://api.openai.com/v1`), `LLM_API_KEY`, `LLM_MODEL` (agente e roteador), `LLM_JUDGE_MODEL` (juiz; deve ser de outra família ou ao menos maior que o do agente, para reduzir viés de autoavaliação). A chave nunca vai ao repositório, a logs nem a traces. Erros HTTP viram erros tipados (`LLMUnavailableError` para 429/5xx/timeout após retry com backoff e jitter; `LLMBadRequestError` para 4xx). Custo por token vem de `evals/pricing.yaml` (por modelo); modelo ausente → custo `null`, nunca inventado.

Cliente simulado **por regra**, sem LLM: os turnos do cenário são enviados em ordem; se a resposta do agente pede confirmação (`awaiting_confirmation`) e o cenário espera uma ferramenta irreversível em `expected.tools`, o simulador responde "sim"; se a ferramenta está em `forbidden_tools`, não confirma e encerra. Mais barato, determinístico e reproduzível; um simulador por LLM pode ser acrescentado depois para cenários abertos.

## Consequências

- Positivas: trocar de fornecedor é só mudar variáveis de ambiente; eval reproduzível e barato; juiz separável do agente.
- Negativas: fornecedores "compatíveis" divergem em detalhes (limites, erros); o suporte a saída estruturada nativa não é usado (protocolo JSON próprio do ADR 0013).

## Adendo (2026-11-06): transporte pelo cliente `opencode`

O usuário definiu que a Fase 08 usa o opencode: `opencode-go/claude-haiku-5-5` como modelo menor (agente e roteador) e `opencode-go/gpt-6-luna` como juiz. A API HTTP do plano OpenCode Go é restrita ao cliente oficial (a chamada direta é barrada por proteção anti-bot e exige cabeçalhos do cliente), então NÃO a chamamos diretamente nem contornamos o bloqueio.

Decisão: `OpenCodeCliProvider(model, *, workdir, agent="plain", timeout=180, max_concurrency=4, runner=...)` implementa `LLMProvider` executando `opencode run --dir <workdir> -m <model> --agent plain --format json <mensagem>` como subprocesso.
- `workdir = evals/opencode/` contém só o agente `plain` (`.opencode/agent/plain.md`: sem ferramentas, `temperature: 0`, permissões negadas), logo o modelo não lê o repositório nem o holdout.
- As mensagens (system/user/assistant) são serializadas em um único texto com papéis explícitos; a resposta é a concatenação dos eventos `text`; tokens e custo vêm do evento `step_finish` (`tokens.input + cache`, `tokens.output`, `cost`); o custo reportado pelo opencode substitui a tabela de preços quando presente.
- Erros: processo com código != 0, timeout, ausência de evento `text` ou evento `error` → `LLMUnavailableError` (com retry/backoff); nunca expõe stderr bruto com possíveis segredos.
- Medido em 2026-11-06: ~16 s por chamada (arranque do processo) e ~7,7 mil tokens de entrada de sistema em cache por chamada; por isso a concorrência é limitada por semáforo e o relatório reporta custo e latência separadamente. O modo `--attach` a um servidor local não produziu saída nos testes e fica como otimização futura.
- Variáveis: `LLM_PROVIDER=opencode-cli|openai-compatible`, `LLM_MODEL`, `LLM_JUDGE_MODEL`. O adaptador compatível com OpenAI permanece para quem tiver chave de API própria.
