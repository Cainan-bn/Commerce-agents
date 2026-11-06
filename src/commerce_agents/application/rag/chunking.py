"""Chunking determinístico dos documentos de política (docs/architecture/rag.md)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from commerce_agents.application.dto.rag import Chunk

MAX_CHUNK_CHARS = 900
INTRO_SECTION = "Introdução"
_FRONT_MATTER_FENCE = "---"


def _split_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_FENCE:
        return {}, text
    metadata: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONT_MATTER_FENCE:
            return metadata, "\n".join(lines[index + 1 :])
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip()
    return metadata, text


def _sections(body: str) -> list[tuple[str, str]]:
    """Divide o corpo em ``(seção, texto)``; o texto antes da 1ª ``##`` é a introdução."""
    sections: list[tuple[str, list[str]]] = [(INTRO_SECTION, [])]
    for line in body.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif line.startswith("# ") and len(sections) == 1:
            continue  # título principal: não vira chunk
        else:
            sections[-1][1].append(line)
    return [(name, "\n".join(lines).strip()) for name, lines in sections]


def _split_long(text: str) -> list[str]:
    """Junta parágrafos até ``MAX_CHUNK_CHARS``; parágrafo maior que o limite fica sozinho."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        joined = size + len(paragraph) + (2 if current else 0)
        if current and joined > MAX_CHUNK_CHARS:
            pieces.append("\n\n".join(current))
            current, size = [], 0
            joined = len(paragraph)
        current.append(paragraph)
        size = joined
        if size > MAX_CHUNK_CHARS:
            pieces.append("\n\n".join(current))
            current, size = [], 0
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _content_hash(title: str, section: str, text: str) -> str:
    return hashlib.sha256(f"{title}\n{section}\n{text}".encode()).hexdigest()


def chunk_document(document: str, text: str) -> list[Chunk]:
    """Converte um documento Markdown com front matter em chunks estáveis."""
    metadata, body = _split_front_matter(text)
    title = metadata.get("title", "").strip()
    if not title:
        raise ValueError(f"Documento {document!r} sem `title` no front matter.")
    chunks: list[Chunk] = []
    for section, section_text in _sections(body):
        if not section_text:
            continue
        for piece in _split_long(section_text):
            position = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=f"{document}#{position}",
                    document=document,
                    title=title,
                    section=section,
                    position=position,
                    text=piece,
                    content_hash=_content_hash(title, section, piece),
                )
            )
    return chunks


def indexed_text(chunk: Chunk) -> str:
    """Texto embutido e indexado: contexto de título e seção sem alterar ``chunk.text``."""
    return f"{chunk.title} > {chunk.section}\n{chunk.text}"


def corpus_version(chunks: Sequence[Chunk]) -> str:
    """Versão do corpus: sha256 (12 hex) dos hashes ordenados por ``chunk_id``."""
    ordered = sorted(chunks, key=lambda chunk: chunk.chunk_id)
    digest = hashlib.sha256("\n".join(chunk.content_hash for chunk in ordered).encode())
    return digest.hexdigest()[:12]
