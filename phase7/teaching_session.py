"""Non-blocking, stateful 3-4 example teaching workflow."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4
from .schemas import CLIExample, TeachingState, MatchResult
from .template_induction import induce_template
from .precedent import PrecedentStore
from .matcher import Phase7Matcher
from .bge_matcher import VectorRecord

@dataclass
class TeachingSession:
    session_id: str
    vendor: str
    unmatched_lines: list[str]
    state: TeachingState = TeachingState.WAITING_FOR_ADMIN
    confirmations: list[CLIExample] = field(default_factory=list)
    template: object | None = None
    results: list[MatchResult] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    unmatched_context_paths: list[str | None] = field(default_factory=list)
    unmatched_source_metadata: list[dict] = field(default_factory=list)

class TeachingSessionManager:
    def __init__(self, matcher: Phase7Matcher, repository=None, min_examples=3):
        self.matcher=matcher; self.repository=repository; self.min_examples=min_examples
        self.sessions={}
    def start(self, vendor, unmatched_lines, unmatched_context_paths=None, unmatched_source_metadata=None):
        if not unmatched_lines:
            return None
        sid=str(uuid4())
        lines=list(unmatched_lines)
        context_paths=list(unmatched_context_paths or [None] * len(lines))
        source_metadata=list(unmatched_source_metadata or [{} for _ in lines])
        if len(context_paths) != len(lines) or len(source_metadata) != len(lines):
            raise ValueError("Unmatched-line metadata must align with unmatched_lines")
        session=TeachingSession(
            session_id=sid, vendor=vendor, unmatched_lines=lines,
            unmatched_context_paths=context_paths,
            unmatched_source_metadata=source_metadata,
        )
        self.sessions[sid]=session
        if self.repository: self.repository.save(session)
        return session
    def confirm(self, session_id, raw_line, canonical_field, context_path=None, source_metadata=None):
        s=self._get(session_id)
        if raw_line not in s.unmatched_lines:
            raise ValueError("Line is not an unmatched line in this session")
        s.state=TeachingState.TEACHING
        if context_path is None:
            try:
                idx=s.unmatched_lines.index(raw_line)
                context_path=s.unmatched_context_paths[idx]
                if source_metadata is None:
                    source_metadata=s.unmatched_source_metadata[idx]
            except ValueError:
                pass
        ex=CLIExample(raw_line,s.vendor,canonical_field,context_path,session_id,source_metadata or {})
        s.confirmations.append(ex)
        self.matcher.precedent.add(s.vendor,canonical_field,"pending",1)
        if len(s.confirmations) >= self.min_examples:
            self._generalize(s)
        if self.repository: self.repository.save(s)
        return s
    def _generalize(self,s):
        s.state=TeachingState.GENERALIZING
        # Template induction requires 3-4 examples for a common pattern.
        s.template=induce_template([e.raw_line for e in s.confirmations])
        # Confirmed examples become durable precedent and, when BGE is configured,
        # the only records eligible for vector search.
        for e in s.confirmations:
            self.matcher.precedent.add(s.vendor,e.canonical_field,s.template.signature,1)
            if self.repository and hasattr(self.repository, "save_confirmation"):
                self.repository.save_confirmation(e, s.template.signature)
        if self.repository and hasattr(self.repository, "save_template"):
            self.repository.save_template(s)
        if self.matcher.bge is not None:
            try:
                provider = self.matcher.bge.provider
                store = self.matcher.bge.vector_store
                embeddings = provider.embed([e.raw_line for e in s.confirmations])
                for e, emb in zip(s.confirmations, embeddings):
                    store.add(VectorRecord(
                        raw_line=e.raw_line, vendor=e.vendor,
                        canonical_field=e.canonical_field,
                        template_signature=s.template.signature,
                        embedding=emb, session_id=s.session_id,
                        source_metadata=e.source_metadata))
            except Exception:
                # Model/vector-store failures must not block deterministic matching.
                pass
        s.results=[]
        confirmed_lines={e.raw_line for e in s.confirmations}
        for idx, line in enumerate(s.unmatched_lines):
            if line in confirmed_lines: continue
            context_path = s.unmatched_context_paths[idx] if idx < len(s.unmatched_context_paths) else None
            result=self.matcher.match(line,s.vendor,s.template,s.confirmations,context_path=context_path)
            s.results.append(result)
            if self.repository and hasattr(self.repository, "save_decision"):
                self.repository.save_decision(s.session_id, result)
            if result.final_mapping_status in {"auto_applied","bge_resolved"}:
                self.matcher.precedent.add(s.vendor,result.candidate_canonical_field,s.template.signature,1)
        s.state=TeachingState.COMPLETED
    def status(self,session_id):
        return self._get(session_id)
    def results(self,session_id):
        s=self._get(session_id)
        return {
            "auto_applied":[r.to_dict() for r in s.results if r.decision=="AUTO_APPLY"],
            "bge_resolved":[r.to_dict() for r in s.results if r.decision=="BGE_RESOLVED"],
            "admin_review":[r.to_dict() for r in s.results if r.decision=="ADMIN_REVIEW"],
            "unresolved":[r.original_line for r in s.results if r.final_mapping_status=="unresolved"],
        }
    def _get(self,sid):
        if sid in self.sessions:
            return self.sessions[sid]
        if self.repository is not None and hasattr(self.repository, "load"):
            session=self.repository.load(sid)
            self.sessions[sid]=session
            return session
        raise KeyError(f"Unknown teaching session: {sid}")

class InMemoryTeachingRepository:
    """Persistence seam used by tests; production can back it with phase7 DB tables."""
    def __init__(self): self.sessions={}
    def save(self,session): self.sessions[session.session_id]=session
    def load(self,sid): return self.sessions[sid]
