"""Schemas de entrada e saída do contrato de ferramentas (application/dto/tools.py)."""

import json

import pytest
from pydantic import ValidationError

from commerce_agents.application.dto.tools import (
    INPUT_MODELS,
    OUTPUT_MODELS,
    RETRYABLE_ERRORS,
    TOOL_SPECS,
    ToolErrorCode,
)
from tests.fakes.tools import SAMPLE_ARGUMENTS

pytestmark = pytest.mark.unit


def test_toda_ferramenta_tem_entrada_e_saida():
    assert set(INPUT_MODELS) == set(TOOL_SPECS) == set(OUTPUT_MODELS)


@pytest.mark.parametrize("tool_name", sorted(SAMPLE_ARGUMENTS))
def test_argumentos_de_exemplo_validam_no_schema_json(tool_name: str):
    payload = json.dumps(SAMPLE_ARGUMENTS[tool_name])

    INPUT_MODELS[tool_name].model_validate_json(payload)


@pytest.mark.parametrize("tool_name", sorted(SAMPLE_ARGUMENTS))
def test_schema_rejeita_campo_extra(tool_name: str):
    payload = json.dumps({**SAMPLE_ARGUMENTS[tool_name], "campo_extra": "x"})

    with pytest.raises(ValidationError):
        INPUT_MODELS[tool_name].model_validate_json(payload)


@pytest.mark.parametrize("tool_name", sorted(TOOL_SPECS))
def test_campos_de_acao_existem_na_entrada(tool_name: str):
    spec = TOOL_SPECS[tool_name]

    assert set(spec.action_fields) <= set(INPUT_MODELS[tool_name].model_fields)


def test_irreversiveis_tem_no_maximo_um_retry():
    irreversible = [spec for spec in TOOL_SPECS.values() if spec.irreversible]

    assert {spec.name for spec in irreversible} == {"cancel_order", "open_return"}
    assert all(spec.max_retries <= 1 for spec in irreversible)


def test_somente_timeout_e_indisponibilidade_sao_retryable():
    assert RETRYABLE_ERRORS == {ToolErrorCode.UPSTREAM_TIMEOUT, ToolErrorCode.UPSTREAM_UNAVAILABLE}
