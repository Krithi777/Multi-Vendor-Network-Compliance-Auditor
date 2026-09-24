"""PostgreSQL persistence for Phase 7 state. Reuses the repository's DATABASE_URL."""
from __future__ import annotations
import json
from dataclasses import asdict
from .teaching_session import TeachingSession
from .schemas import CLIExample, TeachingState
from .template_induction import SyntaxTemplate

class PostgresTeachingRepository:
    def __init__(self, engine):
        self.engine=engine
    def save(self, session: TeachingSession):
        from sqlalchemy import text
        payload={
            "session_id":session.session_id,"vendor":session.vendor,"state":session.state.value,
            "unmatched_lines":json.dumps(session.unmatched_lines),
            "unmatched_context_paths":json.dumps(session.unmatched_context_paths),
            "unmatched_source_metadata":json.dumps(session.unmatched_source_metadata),
            "confirmations":json.dumps([asdict(x) for x in session.confirmations]),
            "template":session.template.signature if session.template else None,
        }
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO phase7_teaching_sessions
                  (session_id,vendor,state,unmatched_lines,unmatched_context_paths,unmatched_source_metadata,confirmations,learned_template)
                VALUES (:session_id,:vendor,:state,CAST(:unmatched_lines AS jsonb),CAST(:unmatched_context_paths AS jsonb),CAST(:unmatched_source_metadata AS jsonb),CAST(:confirmations AS jsonb),:template)
                ON CONFLICT (session_id) DO UPDATE SET
                  state=EXCLUDED.state, unmatched_lines=EXCLUDED.unmatched_lines,
                  unmatched_context_paths=EXCLUDED.unmatched_context_paths,
                  unmatched_source_metadata=EXCLUDED.unmatched_source_metadata,
                  confirmations=EXCLUDED.confirmations, learned_template=EXCLUDED.learned_template
            """), payload)
    def load(self, session_id):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            row=conn.execute(text("SELECT * FROM phase7_teaching_sessions WHERE session_id=:id"),
                             {"id":session_id}).mappings().first()
        if not row: raise KeyError(session_id)
        confirmations=[CLIExample(**x) for x in row["confirmations"]]
        context_paths=row.get("unmatched_context_paths") or [None] * len(row["unmatched_lines"])
        source_metadata=row.get("unmatched_source_metadata") or [{} for _ in row["unmatched_lines"]]
        s=TeachingSession(
            session_id=row["session_id"], vendor=row["vendor"],
            unmatched_lines=row["unmatched_lines"],
            state=TeachingState(row["state"]), confirmations=confirmations,
            unmatched_context_paths=context_paths,
            unmatched_source_metadata=source_metadata,
        )
        if row["learned_template"]:
            toks=tuple(row["learned_template"].split())
            s.template=SyntaxTemplate(toks,row["learned_template"])
        return s

    def save_confirmation(self, example, signature):
        from sqlalchemy import text
        with self.engine.begin() as conn:
            conn.execute(text("""
              INSERT INTO phase7_confirmed_examples
              (session_id,raw_line,vendor,canonical_field,template_signature,context_path,source_metadata)
              VALUES (:session,:line,:vendor,:field,:sig,:context,:meta)
            """), {"session":example.session_id,"line":example.raw_line,"vendor":example.vendor,
                   "field":example.canonical_field,"sig":signature,"context":example.context_path,
                   "meta":example.source_metadata or {}})
    def save_template(self, session):
        from sqlalchemy import text
        if not session.template: return
        field=session.confirmations[0].canonical_field
        with self.engine.begin() as conn:
            conn.execute(text("""
              INSERT INTO phase7_learned_templates
              (session_id,vendor,canonical_field,template,signature,example_count)
              VALUES (:session,:vendor,:field,:template,:sig,:count)
              ON CONFLICT (vendor,canonical_field,signature) DO UPDATE
              SET example_count=EXCLUDED.example_count, session_id=EXCLUDED.session_id
            """), {"session":session.session_id,"vendor":session.vendor,"field":field,
                   "template":session.template.text,"sig":session.template.signature,
                   "count":len(session.confirmations)})
    def save_decision(self, session_id, result):
        from sqlalchemy import text
        d=result.to_dict()
        with self.engine.begin() as conn:
            conn.execute(text("""
              INSERT INTO phase7_mapping_decisions
              (session_id,original_line,normalized_line,vendor,candidate_canonical_field,
               syntax_score,context_score,value_semantics_score,framework_fit_score,precedent_score,
               available_signals,effective_weights,fusion_score,confidence_bucket,decision,
               matched_example,matched_template,bge_score,final_mapping_status,explanation)
              VALUES (:session,:original,:normalized,:vendor,:field,:syntax,:context,:value,:framework,:precedent,
                      :available,:weights,:fusion,:bucket,:decision,:example,:template,:bge,:status,:explanation)
            """), {"session":session_id,"original":d["original_line"],"normalized":d["normalized_line"],
                   "vendor":d["vendor"],"field":d["candidate_canonical_field"],
                   "syntax":d["syntax_score"],"context":d["context_score"],
                   "value":d["value_semantics_score"],"framework":d["framework_fit_score"],
                   "precedent":d["precedent_score"],"available":json.dumps(d["available_signals"]),
                   "weights":json.dumps(d["effective_weights"]),"fusion":d["fusion_score"],
                   "bucket":d["confidence_bucket"],"decision":d["decision"],
                   "example":d["matched_example"],"template":d["matched_template"],
                   "bge":d["bge_score"],"status":d["final_mapping_status"],
                   "explanation":json.dumps(d["explanation"])})
