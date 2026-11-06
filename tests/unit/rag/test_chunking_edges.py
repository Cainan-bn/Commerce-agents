"""Bordas do chunking: front matter incompleto, parágrafos vazios e parágrafo gigante no fim."""

import pytest

from commerce_agents.application.rag.chunking import chunk_document

pytestmark = pytest.mark.unit

FRONT = "---\nversion: 1\ntitle: T\n---\n\n# T\n\n"


def test_sem_front_matter_vira_value_error():
    with pytest.raises(ValueError):
        chunk_document("doc", "# Sem front matter\n\n## A\n\nTexto.\n")


def test_front_matter_nao_fechado_e_linha_sem_dois_pontos_sao_toleradas():
    chunks = chunk_document("doc", "---\nlinha solta\ntitle: T\n\n## A\n\nTexto.\n")

    assert {c.title for c in chunks} == {"T"}


def test_secao_sem_texto_nao_vira_chunk():
    chunks = chunk_document("doc", FRONT + "## Vazia\n\n## Cheia\n\nTexto.\n")

    assert [c.section for c in chunks] == ["Cheia"]
    assert chunks[0].position == 0


def test_paragrafos_vazios_entre_blocos_sao_ignorados_ao_dividir():
    blocks = ["a" * 500, "b" * 500]
    text = FRONT + "## S\n\n" + "\n\n\n\n".join(blocks) + "\n"

    chunks = chunk_document("doc", text)

    assert [c.text for c in chunks] == blocks


def test_paragrafo_gigante_no_fim_nao_deixa_chunk_vazio():
    text = FRONT + "## S\n\n" + "pequeno\n\n" + "g" * 1000 + "\n"

    chunks = chunk_document("doc", text)

    assert [len(c.text) for c in chunks] == [7, 1000]
