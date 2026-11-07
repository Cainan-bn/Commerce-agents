"""Juiz LLM (evals/judge.py): rubrica, parse estrito, sanitização do prompt e concordância."""

import inspect
import json
from typing import Any

import pytest

from commerce_agents.application.ports.llm import LLMUnavailableError
from tests.fakes.scripted_llm import ScriptedLLM
from tests.fakes.traces import call, scenario, trace, turn

pytestmark = pytest.mark.unit

CRITERIA = ("utilidade", "fidelidade", "tom", "concisao")


def _judge():  # type: ignore[no-untyped-def]
    from evals import judge

    return judge


def _payload(
    notas: tuple[Any, Any, Any, Any] = (4, 4, 4, 4), rationale: str = "Resposta adequada."
) -> dict[str, Any]:
    return {"criteria": dict(zip(CRITERIA, notas, strict=True)), "rationale": rationale}


def _texto(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _score(notas: tuple[int, int, int, int]) -> Any:
    return _judge().parse_judge_output(_texto(_payload(notas)))


# ----------------------------------------------------------------- contrato do JudgeScore


def test_criterios_da_rubrica_sao_os_quatro_contratados():
    assert _judge().CRITERIA == CRITERIA


@pytest.mark.parametrize(
    ("notas", "overall"),
    [
        ((4, 4, 4, 4), 4),
        ((4, 4, 5, 4), 4),  # média 4,25 -> 4
        ((4, 5, 4, 5), 5),  # média 4,5 -> 5 (.5 para cima)
        ((1, 1, 1, 2), 1),  # média 1,25 -> 1
    ],
)
def test_overall_e_arredondamento_da_media_com_meio_para_cima(notas, overall: int):
    assert _score(notas).overall == overall


# ----------------------------------------------------------------- parse_judge_output


def test_parse_aceita_json_puro():
    score = _judge().parse_judge_output(_texto(_payload((5, 4, 4, 3))))

    assert score.criteria == {"utilidade": 5, "fidelidade": 4, "tom": 4, "concisao": 3}
    assert score.rationale == "Resposta adequada."


def test_parse_aceita_json_dentro_de_cerca_markdown():
    texto = "Segue a avaliação:\n```json\n" + _texto(_payload()) + "\n```"

    assert _judge().parse_judge_output(texto).overall == 4


def test_parse_rejeita_json_invalido():
    with pytest.raises(_judge().JudgeParseError):
        _judge().parse_judge_output("{criteria: não é json")


def test_parse_rejeita_chave_de_criterio_faltando():
    payload = _payload()
    del payload["criteria"]["tom"]

    with pytest.raises(_judge().JudgeParseError):
        _judge().parse_judge_output(_texto(payload))


def test_parse_rejeita_chave_de_criterio_extra():
    payload = _payload()
    payload["criteria"]["humor"] = 3

    with pytest.raises(_judge().JudgeParseError):
        _judge().parse_judge_output(_texto(payload))


@pytest.mark.parametrize("nota", [0, 6])
def test_parse_rejeita_nota_fora_de_1_a_5(nota: int):
    payload = _payload()
    payload["criteria"]["utilidade"] = nota

    with pytest.raises(_judge().JudgeParseError):
        _judge().parse_judge_output(_texto(payload))


@pytest.mark.parametrize("nota", [4.5, "5"])
def test_parse_rejeita_nota_nao_inteira(nota: Any):
    payload = _payload()
    payload["criteria"]["fidelidade"] = nota

    with pytest.raises(_judge().JudgeParseError):
        _judge().parse_judge_output(_texto(payload))


def test_parse_rejeita_rationale_com_mais_de_300_caracteres():
    with pytest.raises(_judge().JudgeParseError):
        _judge().parse_judge_output(_texto(_payload(rationale="x" * 301)))


def test_parse_aceita_rationale_com_300_caracteres():
    score = _judge().parse_judge_output(_texto(_payload(rationale="x" * 300)))

    assert len(score.rationale) == 300


def test_overall_enviado_pelo_modelo_nao_e_usado():
    payload = _payload((2, 2, 2, 2))
    payload["overall"] = 5

    assert _judge().parse_judge_output(_texto(payload)).overall == 2


# ----------------------------------------------------------------- build_judge_messages


def test_system_traz_rubrica_dos_quatro_criterios_e_resposta_so_json():
    messages = _judge().build_judge_messages(scenario(), trace(turns=[turn()]))

    assert messages[0].role == "system"
    for criterio in CRITERIA:
        assert criterio in messages[0].content
    assert "JSON" in messages[0].content


def test_user_traz_conversa_chamadas_de_ferramenta_e_citacoes():
    tr = trace(
        turns=[turn(text="Cadê meu pedido?", reply="Ele está a caminho.")],
        tool_calls=[
            call("consultar_pedido_obs", {"order_id": "O000001"}),
            call("consultar_frete_obs", {"cep": "01310100"}, ok=False, error_code="not_found"),
        ],
        policy_citations=["troca#0"],
    )

    messages = _judge().build_judge_messages(scenario(), tr)
    user = messages[-1]

    assert user.role == "user"
    assert "Cadê meu pedido?" in user.content
    assert "Ele está a caminho." in user.content
    assert "consultar_pedido_obs" in user.content
    assert "consultar_frete_obs" in user.content
    assert "not_found" in user.content
    assert "troca#0" in user.content


def test_prompt_nunca_inclui_valores_de_expected():
    scn = scenario(
        intent="intencao_xq",
        agent="agente_xq",
        tools=[("ferramenta_xq", {"order_id": "PEDIDO_XQ"})],
        forbidden_tools=["proibida_xq"],
        must_mention=["termo_xq"],
        outcome="resolved",
    )
    tr = trace(
        turns=[turn(text="pergunta do cliente", reply="resposta do agente", agent="pedidos")],
        tool_calls=[call("get_order_status", {"order_id": "O000001"})],
    )

    messages = _judge().build_judge_messages(scn, tr)
    texto = " ".join(m.content for m in messages)

    for valor in [
        "intencao_xq",
        "agente_xq",
        "ferramenta_xq",
        "PEDIDO_XQ",
        "proibida_xq",
        "termo_xq",
        "resolved",
    ]:
        assert valor not in texto


# ----------------------------------------------------------------- judge_scenario


async def test_cenario_resolvido_e_julgado_com_uma_chamada():
    provider = ScriptedLLM([_texto(_payload((5, 5, 4, 4)))])

    result = await _judge().judge_scenario(
        provider, scenario(outcome="resolved"), trace(turns=[turn()])
    )

    assert result.score is not None
    assert result.score.overall == 4
    assert result.skipped_reason is None
    assert provider.remaining == 0


async def test_cenario_nao_resolvido_nao_chama_o_provider():
    provider = ScriptedLLM([])
    scn = scenario(outcome="handoff")
    tr = trace(handoff_events=["urgente"])

    result = await _judge().judge_scenario(provider, scn, tr)

    assert result.score is None
    assert result.skipped_reason == "not_resolved"
    assert provider.calls == []


async def test_trace_com_infra_error_e_pulado_sem_chamar_o_provider():
    provider = ScriptedLLM([])
    tr = trace(turns=[turn()], infra_error="timeout no provedor")

    result = await _judge().judge_scenario(provider, scenario(outcome="resolved"), tr)

    assert result.score is None
    assert result.skipped_reason == "infra_error"
    assert provider.calls == []


async def test_provider_indisponivel_vira_judge_unavailable_sem_levantar():
    provider = ScriptedLLM([LLMUnavailableError("429 persistente")])

    result = await _judge().judge_scenario(
        provider, scenario(outcome="resolved"), trace(turns=[turn()])
    )

    assert result.score is None
    assert result.skipped_reason == "judge_unavailable"


async def test_parse_falho_repete_uma_vez_com_a_mesma_mensagem_e_desiste():
    provider = ScriptedLLM(["isto não é json", "continua não sendo json"])

    result = await _judge().judge_scenario(
        provider, scenario(outcome="resolved"), trace(turns=[turn()])
    )

    assert result.score is None
    assert result.skipped_reason == "judge_parse_error"
    assert len(provider.calls) == 2
    assert provider.calls[0] == provider.calls[1]


async def test_parse_falho_seguido_de_resposta_valida_e_julgado():
    provider = ScriptedLLM(["lixo", _texto(_payload((3, 3, 3, 3)))])

    result = await _judge().judge_scenario(
        provider, scenario(outcome="resolved"), trace(turns=[turn()])
    )

    assert result.score is not None
    assert result.score.overall == 3
    assert result.skipped_reason is None


def test_judge_scenario_nao_recebe_temperatura():
    parametros = inspect.signature(_judge().judge_scenario).parameters

    assert "temperature" not in parametros


# ----------------------------------------------------------------- agreement


def test_agreement_conta_pares_dentro_da_tolerancia_padrao_de_1():
    pares = [(4, 4), (4, 5), (1, 5), (3, 3)]

    assert _judge().agreement(pares) == pytest.approx(0.75)


def test_agreement_respeita_tolerancia_informada():
    pares = [(2, 3), (2, 4), (5, 5)]

    assert _judge().agreement(pares, tolerance=0) == pytest.approx(1 / 3)
    assert _judge().agreement(pares, tolerance=2) == pytest.approx(1.0)


def test_agreement_com_lista_vazia_levanta_value_error():
    with pytest.raises(ValueError):
        _judge().agreement([])


# ----------------------------------------------------------------- summarize


def test_summarize_calcula_media_e_contagens():
    resultados = [
        _judge().JudgeResult(score=_score((4, 4, 4, 4)), skipped_reason=None),
        _judge().JudgeResult(score=_score((2, 2, 2, 2)), skipped_reason=None),
        _judge().JudgeResult(score=None, skipped_reason="not_resolved"),
    ]

    resumo = _judge().summarize(resultados)

    assert resumo == {"mean_overall": 3.0, "judged": 2, "skipped": 1}


def test_summarize_sem_nenhum_julgado_tem_media_none():
    resultados = [
        _judge().JudgeResult(score=None, skipped_reason="infra_error"),
        _judge().JudgeResult(score=None, skipped_reason="judge_unavailable"),
    ]

    resumo = _judge().summarize(resultados)

    assert resumo == {"mean_overall": None, "judged": 0, "skipped": 2}
