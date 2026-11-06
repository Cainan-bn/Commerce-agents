"""chunk_document e corpus_version: chunking puro, determinístico e cobertura do corpus real."""

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

POLICIES_DIR = Path(__file__).resolve().parents[3] / "data" / "policies"
FRONT = "---\nversion: 1\ntitle: Política de Teste\n---\n\n# Política de Teste\n\n"


def _chunk(document: str, text: str) -> list[Any]:
    from commerce_agents.application.rag.chunking import chunk_document

    return chunk_document(document, text)


def _corpus_version(chunks: list[Any]) -> str:
    from commerce_agents.application.rag.chunking import corpus_version

    return corpus_version(chunks)


def _paragraph(size: int, marker: str) -> str:
    base = f"{marker} " + "palavra " * (size // 8 + 1)
    return base[:size].rstrip()


def test_front_matter_e_identificadores_do_chunk():
    chunks = _chunk("troca", FRONT + "## Prazo\n\nTexto do prazo.\n")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.document == "troca"
    assert chunk.title == "Política de Teste"
    assert chunk.section == "Prazo"
    assert chunk.position == 0
    assert chunk.chunk_id == "troca#0"
    assert chunk.text == "Texto do prazo."


def test_cada_secao_vira_chunk_e_titulo_principal_nao_vira_chunk():
    text = FRONT + "## Prazo\n\nUm.\n\n## Estorno\n\nDois.\n"

    chunks = _chunk("doc", text)

    assert [chunk.section for chunk in chunks] == ["Prazo", "Estorno"]
    assert all(not chunk.text.startswith("#") for chunk in chunks)
    assert all("Política de Teste" != chunk.section for chunk in chunks)


def test_titulo_ausente_vira_value_error():
    with pytest.raises(ValueError):
        _chunk("doc", "---\nversion: 1\n---\n\n# Sem título\n\n## Seção\n\nTexto.\n")


def test_secao_longa_e_dividida_por_paragrafos_ate_900_caracteres():
    paragraphs = [_paragraph(400, f"p{i}") for i in range(4)]
    text = FRONT + "## Longa\n\n" + "\n\n".join(paragraphs) + "\n"

    chunks = _chunk("doc", text)

    assert len(chunks) >= 2
    assert all(len(chunk.text) <= 900 for chunk in chunks)
    assert "\n\n".join(chunk.text for chunk in chunks) == "\n\n".join(paragraphs)


def test_paragrafo_maior_que_900_fica_sozinho():
    small_a = _paragraph(100, "alfa")
    giant = _paragraph(1200, "gigante")
    small_c = _paragraph(100, "charlie")
    text = FRONT + "## Gigante\n\n" + "\n\n".join([small_a, giant, small_c]) + "\n"

    chunks = _chunk("doc", text)

    texts = [chunk.text for chunk in chunks]
    assert giant in texts
    assert texts[texts.index(giant)] == giant
    assert all(giant not in t for t in texts if t != giant)


def test_ids_unicos_posicoes_sequenciais_e_sem_chunk_vazio():
    text = FRONT + "## A\n\nUm.\n\n## B\n\nDois.\n\n## C\n\nTrês.\n"

    chunks = _chunk("doc", text)

    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert all(chunk.text.strip() for chunk in chunks)


def test_content_hash_muda_so_no_chunk_alterado():
    original = _chunk("doc", FRONT + "## A\n\nUm.\n\n## B\n\nDois.\n")
    changed = _chunk("doc", FRONT + "## A\n\nUm.\n\n## B\n\nDois mudou.\n")

    assert original[0].content_hash == changed[0].content_hash
    assert original[1].content_hash != changed[1].content_hash


def test_determinismo_byte_a_byte():
    text = FRONT + "## A\n\nUm.\n\n## B\n\nDois.\n"

    first = _chunk("doc", text)
    second = _chunk("doc", text)

    assert [c.model_dump_json() for c in first] == [c.model_dump_json() for c in second]


@pytest.mark.parametrize("policy", sorted(POLICIES_DIR.glob("*.md")), ids=lambda p: p.stem)
def test_corpus_real_tem_um_chunk_por_secao_sem_vazios(policy: Path):
    text = policy.read_text(encoding="utf-8")
    sections = [line for line in text.splitlines() if line.startswith("## ")]

    chunks = _chunk(policy.stem, text)

    assert len({chunk.section for chunk in chunks}) == len(sections)
    assert all(chunk.text.strip() for chunk in chunks)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


@pytest.mark.parametrize("policy", sorted(POLICIES_DIR.glob("*.md")), ids=lambda p: p.stem)
def test_corpus_real_cobre_todo_o_corpo(policy: Path):
    text = policy.read_text(encoding="utf-8")
    body = text.split("---", 2)[2]
    paragraphs = [
        p.strip() for p in body.split("\n\n") if p.strip() and not p.lstrip().startswith("#")
    ]

    chunks = _chunk(policy.stem, text)
    indexed = "\n".join(chunk.text for chunk in chunks)

    missing = [p for p in paragraphs if p not in indexed]
    assert missing == []


def test_corpus_version_independe_da_ordem_de_entrada():
    chunks = _chunk("doc", FRONT + "## A\n\nUm.\n\n## B\n\nDois.\n")

    assert _corpus_version(chunks) == _corpus_version(list(reversed(chunks)))


def test_corpus_version_muda_se_qualquer_chunk_muda():
    chunks = _chunk("doc", FRONT + "## A\n\nUm.\n\n## B\n\nDois.\n")
    alterado = [chunks[0], chunks[1].model_copy(update={"content_hash": "0" * 64})]

    assert _corpus_version(chunks) != _corpus_version(alterado)


def test_corpus_version_tem_12_caracteres_hex():
    chunks = _chunk("doc", FRONT + "## A\n\nUm.\n")

    version = _corpus_version(chunks)

    assert len(version) == 12
    assert all(ch in "0123456789abcdef" for ch in version)
