# 0015. Provider LLM compatível com a API da OpenAI e cliente simulado por regra

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
