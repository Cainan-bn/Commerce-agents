"""PolicyIngestor em Postgres: idempotência, reindexação seletiva e transação (ADR 0005)."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from tests.fakes.hashing_embedder import FailingEmbedder, HashingEmbedder

pytestmark = pytest.mark.integration

POLICIES_DIR = Path(__file__).resolve().parents[3] / "data" / "policies"


def _ingestor(factory: Any, embedder: Any) -> Any:
    from commerce_agents.infrastructure.rag.ingestion import PolicyIngestor

    return PolicyIngestor(factory, embedder)


def _expected_total(policies_dir: Path) -> int:
    from commerce_agents.application.rag.chunking import chunk_document

    return sum(
        len(chunk_document(policy.stem, policy.read_text(encoding="utf-8")))
        for policy in sorted(policies_dir.glob("*.md"))
    )


async def _rows(engine: Any) -> list[Any]:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT chunk_id, text, content_hash, model_name, corpus_version "
                "FROM policy_chunks ORDER BY chunk_id"
            )
        )
        return list(result.all())


def _copy_policies(tmp_path: Path) -> Path:
    destination = tmp_path / "policies"
    shutil.copytree(POLICIES_DIR, destination)
    return destination


async def test_primeira_ingestao_indexa_todos_os_chunks(rag_db):
    engine, factory = rag_db
    embedder = HashingEmbedder()
    total = _expected_total(POLICIES_DIR)

    report = await _ingestor(factory, embedder).ingest(POLICIES_DIR)

    assert report.chunks_total == total
    assert report.chunks_added == total
    assert report.embeddings_computed == total
    assert len(await _rows(engine)) == total
    assert embedder.calls_documents == total


async def test_segunda_execucao_nao_recalcula_embeddings(rag_db):
    _, factory = rag_db
    embedder = HashingEmbedder()
    ingestor = _ingestor(factory, embedder)
    total = _expected_total(POLICIES_DIR)
    await ingestor.ingest(POLICIES_DIR)
    calls_after_first = embedder.calls_documents

    report = await ingestor.ingest(POLICIES_DIR)

    assert report.chunks_added == 0
    assert report.chunks_updated == 0
    assert report.chunks_unchanged == total
    assert report.embeddings_computed == 0
    assert embedder.calls_documents == calls_after_first


async def test_alterar_um_trecho_reindexa_so_o_afetado(rag_db, tmp_path: Path):
    _, factory = rag_db
    embedder = HashingEmbedder()
    ingestor = _ingestor(factory, embedder)
    policies = _copy_policies(tmp_path)
    total = _expected_total(policies)
    await ingestor.ingest(policies)

    devolucao = policies / "devolucao.md"
    devolucao.write_text(
        devolucao.read_text(encoding="utf-8").replace(
            "em até 7 dias corridos", "em até 8 dias corridos", 1
        ),
        encoding="utf-8",
    )
    report = await ingestor.ingest(policies)

    assert 1 <= report.chunks_updated < total
    assert report.chunks_unchanged == total - report.chunks_updated
    assert report.embeddings_computed == report.chunks_updated
    assert report.chunks_added == 0


async def test_remover_secao_apaga_o_chunk(rag_db, tmp_path: Path):
    engine, factory = rag_db
    ingestor = _ingestor(factory, HashingEmbedder())
    policies = _copy_policies(tmp_path)
    await ingestor.ingest(policies)
    before = len(await _rows(engine))

    cancelamento = policies / "cancelamento.md"
    lines = cancelamento.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("## Pedido já pago via Pix"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    removed_paragraph = next(
        line.strip() for line in lines[start + 1 : end] if line.strip() and not line.startswith("#")
    )
    cancelamento.write_text("".join(lines[:start] + lines[end:]), encoding="utf-8")

    report = await ingestor.ingest(policies)

    after_rows = await _rows(engine)
    assert report.chunks_removed >= 1
    assert len(after_rows) == before - report.chunks_removed + report.chunks_added
    assert all(removed_paragraph not in row.text for row in after_rows)


async def test_trocar_model_name_reindexa_tudo(rag_db):
    engine, factory = rag_db
    await _ingestor(factory, HashingEmbedder(model_name="hashing-v1")).ingest(POLICIES_DIR)
    total = _expected_total(POLICIES_DIR)
    embedder = HashingEmbedder(model_name="hashing-v2")

    report = await _ingestor(factory, embedder).ingest(POLICIES_DIR)

    assert report.embeddings_computed == total
    assert report.chunks_unchanged == 0
    assert {row.model_name for row in await _rows(engine)} == {"hashing-v2"}


async def test_corpus_version_igual_em_todos_os_chunks_e_muda_com_o_corpus(rag_db, tmp_path: Path):
    engine, factory = rag_db
    ingestor = _ingestor(factory, HashingEmbedder())
    policies = _copy_policies(tmp_path)
    first = await ingestor.ingest(policies)
    assert {row.corpus_version for row in await _rows(engine)} == {first.corpus_version}

    troca = policies / "troca.md"
    troca.write_text(
        troca.read_text(encoding="utf-8").replace("7 dias corridos", "9 dias corridos", 1),
        encoding="utf-8",
    )
    second = await ingestor.ingest(policies)

    assert second.corpus_version != first.corpus_version
    assert {row.corpus_version for row in await _rows(engine)} == {second.corpus_version}


async def test_falha_do_embedder_nao_deixa_estado_parcial(rag_db):
    engine, factory = rag_db

    with pytest.raises(RuntimeError, match="falha injetada"):
        await _ingestor(factory, FailingEmbedder(fail_after=3)).ingest(POLICIES_DIR)

    assert await _rows(engine) == []


async def test_falha_em_reingestao_preserva_estado_anterior(rag_db, tmp_path: Path):
    engine, factory = rag_db
    policies = _copy_policies(tmp_path)
    await _ingestor(factory, HashingEmbedder()).ingest(policies)
    before = [(row.chunk_id, row.corpus_version) for row in await _rows(engine)]

    troca = policies / "troca.md"
    troca.write_text(
        troca.read_text(encoding="utf-8").replace("7 dias corridos", "9 dias corridos", 1),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="falha injetada"):
        await _ingestor(factory, FailingEmbedder(fail_after=2)).ingest(policies)

    assert [(row.chunk_id, row.corpus_version) for row in await _rows(engine)] == before
