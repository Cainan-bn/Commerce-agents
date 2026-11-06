"""DTOs da ingestão e da recuperação de políticas."""

from pydantic import Field

from commerce_agents.application.dto.base import StrictModel


class Chunk(StrictModel):
    """Trecho de política pronto para indexar. Id e texto são determinísticos."""

    chunk_id: str = Field(description="`<documento>#<posicao>`; estável entre execuções")
    document: str = Field(description="Nome do arquivo sem extensão, ex.: `cancelamento`")
    title: str = Field(description="Título do documento (front matter)")
    section: str = Field(description="Título da seção `##` de origem")
    position: int = Field(ge=0, description="Ordem do chunk no documento")
    text: str = Field(min_length=1, description="Seção/parágrafos, sem o cabeçalho de contexto")
    content_hash: str = Field(description="sha256 de título+seção+texto")


class IngestionReport(StrictModel):
    corpus_version: str
    model_name: str
    chunks_total: int = Field(ge=0)
    chunks_added: int = Field(ge=0)
    chunks_updated: int = Field(ge=0)
    chunks_removed: int = Field(ge=0)
    chunks_unchanged: int = Field(ge=0)
    embeddings_computed: int = Field(ge=0)
