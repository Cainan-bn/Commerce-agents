"""OpenAICompatibleProvider (ADR 0015): protocolo /chat/completions, retry, erros e segredo."""

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from commerce_agents.application.dto.views import LLMMessage, LLMResult

pytestmark = pytest.mark.unit

API_KEY = "sk-chave-secreta-de-teste-123"  # pragma: allowlist secret
BASE_URL = "https://provedor.example/v1"
MESSAGES = [
    LLMMessage(role="system", content="Você é um atendente."),
    LLMMessage(role="user", content="oi"),
]


def _ok_body(content: str = "Olá!", model: str | None = "modelo-servidor") -> dict[str, Any]:
    body: dict[str, Any] = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 4},
    }
    if model is not None:
        body["model"] = model
    return body


def _provider(
    handler: Callable[[httpx.Request], httpx.Response], sleeps: list[float], **options: Any
):  # type: ignore[no-untyped-def]
    from commerce_agents.infrastructure.llm.openai_compatible import OpenAICompatibleProvider

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        BASE_URL,
        API_KEY,
        options.pop("model", "modelo-configurado"),
        client=client,
        sleep=record_sleep,
        **options,
    )


def _calls_counter(
    responses: list[httpx.Response | Exception],
) -> tuple[Callable[[httpx.Request], httpx.Response], list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


async def test_monta_a_requisicao_no_protocolo_chat_completions():
    handler, seen = _calls_counter([httpx.Response(200, json=_ok_body())])
    provider = _provider(handler, [], temperature=0.2)

    await provider.complete(MESSAGES, max_tokens=256)

    request = seen[0]
    assert str(request.url) == f"{BASE_URL}/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    body = json.loads(request.content)
    assert body["model"] == "modelo-configurado"
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 256
    assert body["messages"] == [
        {"role": "system", "content": "Você é um atendente."},
        {"role": "user", "content": "oi"},
    ]


async def test_parseia_conteudo_e_usage_e_prefere_o_modelo_do_servidor():
    handler, _ = _calls_counter([httpx.Response(200, json=_ok_body("Resposta", "modelo-real"))])

    result = await _provider(handler, []).complete(MESSAGES, max_tokens=64)

    assert isinstance(result, LLMResult)
    assert result.content == "Resposta"
    assert result.model == "modelo-real"
    assert (result.input_tokens, result.output_tokens) == (11, 4)


async def test_sem_modelo_no_servidor_usa_o_configurado():
    handler, _ = _calls_counter([httpx.Response(200, json=_ok_body(model=None))])

    result = await _provider(handler, []).complete(MESSAGES, max_tokens=64)

    assert result.model == "modelo-configurado"


async def test_429_repete_com_backoff_e_depois_sucede():
    sleeps: list[float] = []
    handler, seen = _calls_counter(
        [httpx.Response(429, json={}), httpx.Response(200, json=_ok_body())]
    )

    result = await _provider(handler, sleeps, max_retries=2).complete(MESSAGES, max_tokens=64)

    assert result.content == "Olá!"
    assert len(seen) == 2
    assert len(sleeps) == 1
    assert sleeps[0] > 0


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_repete_ate_o_limite_e_levanta_indisponivel(status: int):
    from commerce_agents.infrastructure.llm.openai_compatible import LLMUnavailableError

    sleeps: list[float] = []
    handler, seen = _calls_counter([httpx.Response(status, json={})])

    with pytest.raises(LLMUnavailableError):
        await _provider(handler, sleeps, max_retries=2).complete(MESSAGES, max_tokens=64)

    assert len(seen) == 3  # 1 tentativa + max_retries=2
    assert len(sleeps) == 2


async def test_timeout_repete_e_levanta_indisponivel():
    from commerce_agents.infrastructure.llm.openai_compatible import LLMUnavailableError

    sleeps: list[float] = []
    handler, seen = _calls_counter(
        [httpx.ReadTimeout("demorou demais", request=httpx.Request("POST", BASE_URL))]
    )

    with pytest.raises(LLMUnavailableError):
        await _provider(handler, sleeps, max_retries=1).complete(MESSAGES, max_tokens=64)

    assert len(seen) == 2


async def test_retry_after_e_respeitado():
    sleeps: list[float] = []
    handler, _ = _calls_counter(
        [
            httpx.Response(429, headers={"Retry-After": "7"}, json={}),
            httpx.Response(200, json=_ok_body()),
        ]
    )

    await _provider(handler, sleeps, max_retries=2).complete(MESSAGES, max_tokens=64)

    assert sleeps == [7.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_4xx_nao_repete_e_levanta_bad_request(status: int):
    from commerce_agents.infrastructure.llm.openai_compatible import LLMBadRequestError

    sleeps: list[float] = []
    handler, seen = _calls_counter([httpx.Response(status, json={"error": "ruim"})])

    with pytest.raises(LLMBadRequestError):
        await _provider(handler, sleeps, max_retries=2).complete(MESSAGES, max_tokens=64)

    assert len(seen) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"sem": "choices"}),
        httpx.Response(200, content=b"nao e json {"),
    ],
)
async def test_corpo_malformado_vira_indisponivel(response: httpx.Response):
    # Decisão documentada: resposta 200 sem conteúdo utilizável é falha do provedor (retryable),
    # não erro de requisição do cliente.
    from commerce_agents.infrastructure.llm.openai_compatible import LLMUnavailableError

    handler, _ = _calls_counter([response])

    with pytest.raises(LLMUnavailableError):
        await _provider(handler, [], max_retries=0).complete(MESSAGES, max_tokens=64)


def test_api_key_vazia_e_erro_no_construtor():
    from commerce_agents.infrastructure.llm.openai_compatible import OpenAICompatibleProvider

    with pytest.raises(ValueError):
        OpenAICompatibleProvider(BASE_URL, "", "modelo")


async def test_chave_nunca_aparece_em_erro_repr_ou_logs(caplog: pytest.LogCaptureFixture):
    from commerce_agents.infrastructure.llm.openai_compatible import LLMBadRequestError

    caplog.set_level(logging.DEBUG)
    handler, _ = _calls_counter([httpx.Response(401, json={"error": "chave inválida"})])
    provider = _provider(handler, [])

    with pytest.raises(LLMBadRequestError) as raised:
        await provider.complete(MESSAGES, max_tokens=64)

    assert API_KEY not in str(raised.value)
    assert API_KEY not in repr(raised.value)
    assert API_KEY not in repr(provider)
    assert API_KEY not in caplog.text


def test_build_provider_from_env_usa_padroes_e_exige_chave_e_modelo():
    from commerce_agents.infrastructure.llm.openai_compatible import build_provider_from_env

    provider = build_provider_from_env({"LLM_API_KEY": API_KEY, "LLM_MODEL": "modelo-agente"})

    assert provider is not None
    with pytest.raises((ValueError, RuntimeError)) as no_key:
        build_provider_from_env({"LLM_MODEL": "modelo-agente"})
    assert "LLM_API_KEY" in str(no_key.value)
    with pytest.raises((ValueError, RuntimeError)) as no_model:
        build_provider_from_env({"LLM_API_KEY": API_KEY})
    assert "LLM_MODEL" in str(no_model.value)


def test_build_judge_provider_usa_llm_judge_model():
    from commerce_agents.infrastructure.llm.openai_compatible import build_judge_provider_from_env

    judge = build_judge_provider_from_env(
        {"LLM_API_KEY": API_KEY, "LLM_MODEL": "agente", "LLM_JUDGE_MODEL": "juiz-outra-familia"}
    )

    assert judge.model == "juiz-outra-familia"
