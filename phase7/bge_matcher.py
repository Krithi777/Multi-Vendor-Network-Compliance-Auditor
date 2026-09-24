"""Secondary BGE matcher. It is invoked only by the medium-confidence path."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Any
import math

@dataclass(frozen=True)
class VectorRecord:
    raw_line: str
    vendor: str
    canonical_field: str
    template_signature: str
    embedding: Any
    session_id: str | None = None
    source_metadata: dict | None = None

class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]): ...

class BGEEmbeddingProvider:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
    def embed(self, texts):
        self._load()
        return self._model.encode(texts, normalize_embeddings=True)

def cosine(a,b):
    dot = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
    return 0.0 if not na or not nb else dot/(na*nb)

class InMemoryVectorStore:
    """Test/dev store; production should use PostgreSQL + pgvector."""
    def __init__(self): self.records=[]
    def add(self, record): self.records.append(record)
    def query(self, embedding, vendor=None, limit=5):
        rows=[r for r in self.records if vendor is None or r.vendor == vendor]
        return sorted(((cosine(embedding,r.embedding),r) for r in rows), key=lambda x:x[0], reverse=True)[:limit]

class PgVectorStore:
    """Thin repository over the Phase 7 pgvector table."""
    def __init__(self, connection): self.connection=connection
    def add(self, record: VectorRecord):
        self.connection.execute(
            """INSERT INTO phase7_embedding_records
               (raw_line,vendor,canonical_field,template_signature,embedding,session_id,source_metadata)
               VALUES (:raw_line,:vendor,:field,:signature,:embedding,:session,:meta)""",
            {"raw_line":record.raw_line,"vendor":record.vendor,"field":record.canonical_field,
             "signature":record.template_signature,"embedding":list(record.embedding),
             "session":record.session_id,"meta":record.source_metadata or {}})
    def query(self, embedding, vendor=None, limit=5):
        sql="""SELECT raw_line,vendor,canonical_field,template_signature,embedding,session_id,source_metadata,
                      1 - (embedding <=> :embedding) AS score
               FROM phase7_embedding_records
               WHERE (:vendor IS NULL OR vendor=:vendor)
               ORDER BY embedding <=> :embedding LIMIT :limit"""
        rows=self.connection.execute(text(sql), {"embedding":list(embedding),"vendor":vendor,"limit":limit}).mappings()
        return [(float(r["score"]), VectorRecord(r["raw_line"],r["vendor"],r["canonical_field"],
                 r["template_signature"],r["embedding"],r["session_id"],r["source_metadata"])) for r in rows]

try:
    from sqlalchemy import text
except ImportError:
    text = None

class BGEMatcher:
    def __init__(self, provider: EmbeddingProvider, vector_store, threshold: float | None):
        self.provider=provider; self.vector_store=vector_store; self.threshold=threshold
    def match(self, raw_line: str, vendor: str):
        if self.threshold is None:
            raise ValueError("BGE threshold is not configured; calibrate it from validation data.")
        embedding=self.provider.embed([raw_line])[0]
        hits=self.vector_store.query(embedding, vendor=vendor, limit=5)
        if not hits:
            return None
        score, record=hits[0]
        return {"score":score, "record":record, "accepted":score >= self.threshold}
