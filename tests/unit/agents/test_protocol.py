"""Protocolo do LLM (ADR 0013): ToolCall | FinalAnswer validados; catálogo por allowlist."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from commerce_agents.application.dto.agents import FinalAnswer, ToolCall
from commerce_agents.application.dto.tools import AGENT_ALLOWLIST, INPUT_MODELS

pytestmark = pytest.mark.unit


def _parse(text: str):  # type: ignore[no-untyped-def]
    from commerce_agents.application.agents.protocol import parse_agent_action

    return parse_agent_action(text)


def _error_class():  # type: ignore[no-untyped-def]
    from commerce_agents.application.agents.protocol import ActionParseError

    return ActionParseError


def test_tool_call_valido():
    action = _parse(
        '{"type": "tool_call", "tool": "get_order_status", "arguments": {"order_id": "O000001"}}'
    )

    assert isinstance(action, ToolCall)
    assert action.tool == "get_order_status"
    assert action.arguments == {"order_id": "O000001"}


def test_final_answer_valido_com_citacoes():
    action = _parse('{"type": "final", "text": "Você tem 7 dias.", "citations": ["devolucao#0"]}')

    assert isinstance(action, FinalAnswer)
    assert action.citations == ("devolucao#0",)


def test_json_cercado_por_markdown_e_texto_e_aceito():
    raw = 'Claro, segue:\n```json\n{"type": "final", "text": "Oi", "citations": []}\n```\nAbraço.'

    action = _parse(raw)

    assert isinstance(action, FinalAnswer)
    assert action.text == "Oi"


def test_campo_extra_e_proibido():
    with pytest.raises(_error_class()):
        _parse('{"type": "final", "text": "Oi", "citations": [], "extra": 1}')


def test_texto_sem_json_vira_action_parse_error():
    with pytest.raises(_error_class()):
        _parse("Olá, tudo bem? Não tenho um JSON aqui.")


def test_json_invalido_vira_action_parse_error():
    with pytest.raises(_error_class()):
        _parse('{"type": "final", "text": ')


def test_type_desconhecido_vira_action_parse_error():
    with pytest.raises(_error_class()):
        _parse('{"type": "delete_everything"}')


@given(st.text(max_size=300))
def test_parse_nunca_lanca_alem_de_action_parse_error(text: str):
    try:
        action = _parse(text)
    except _error_class():
        return
    assert isinstance(action, ToolCall | FinalAnswer)


def test_catalogo_lista_so_ferramentas_da_allowlist_com_schema():
    from commerce_agents.application.agents.protocol import render_tool_catalog

    catalog = render_tool_catalog("pedidos")

    for tool in AGENT_ALLOWLIST["Pedidos"]:
        assert tool in catalog
    assert "search_products" not in catalog
    assert "order_id" in catalog
    assert "order_id" in INPUT_MODELS["cancel_order"].model_json_schema()["properties"]


def test_agente_desconhecido_no_catalogo_vira_key_error():
    from commerce_agents.application.agents.protocol import render_tool_catalog

    with pytest.raises(KeyError):
        render_tool_catalog("agente_inexistente")


@pytest.mark.parametrize(
    ("agent_key", "allowed"),
    [
        ("pedidos", "Pedidos"),
        ("catalogo", "CatalogoVendas"),
        ("politicas", "Politicas"),
        ("pos_venda", "PosVenda"),
    ],
)
def test_catalogo_de_cada_agente_bate_com_a_allowlist(agent_key: str, allowed: str):
    from commerce_agents.application.agents.protocol import render_tool_catalog

    catalog = render_tool_catalog(agent_key)

    for tool in AGENT_ALLOWLIST[allowed]:
        assert tool in catalog
