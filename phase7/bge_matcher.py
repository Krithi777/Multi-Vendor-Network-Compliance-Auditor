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
        from sqlalchemy import text
        import json
        sql = text("""INSERT INTO phase7_embedding_records
               (raw_line,vendor,canonical_field,template_signature,embedding,session_id,source_metadata)
               VALUES (:raw_line,:vendor,:field,:signature,CAST(:embedding AS vector),CAST(:session AS uuid),CAST(:meta AS jsonb))""")
        params = {
            "raw_line": record.raw_line, "vendor": record.vendor, "field": record.canonical_field,
            "signature": record.template_signature, "embedding": str([float(x) for x in record.embedding]),
            "session": record.session_id, "meta": json.dumps(record.source_metadata or {})
        }
        if hasattr(self.connection, "begin"):
            with self.connection.begin() as conn:
                conn.execute(sql, params)
        else:
            self.connection.execute(sql, params)

    def query(self, embedding, vendor=None, limit=5):
        from sqlalchemy import text
        import json
        sql = text("""SELECT raw_line,vendor,canonical_field,template_signature,embedding,session_id,source_metadata,
                      1 - (embedding <=> CAST(:embedding AS vector)) AS score
               FROM phase7_embedding_records
               WHERE (:vendor IS NULL OR vendor=:vendor)
               ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT :limit""")
        params = {"embedding": str([float(x) for x in embedding]), "vendor": vendor, "limit": limit}
        if hasattr(self.connection, "connect"):
            with self.connection.connect() as conn:
                rows = conn.execute(sql, params).mappings().all()
        else:
            rows = self.connection.execute(sql, params).mappings().all()
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
