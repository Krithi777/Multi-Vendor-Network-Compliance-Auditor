"""Small orchestration seam: recognized parser output bypasses Phase 7."""
from __future__ import annotations
from .parser_adapter import collect_unmatched
from .teaching_session import TeachingSessionManager

def start_from_parser_output(manager: TeachingSessionManager, parser_records):
    unmatched = collect_unmatched(parser_records)
    if not unmatched:
        return None
    # Keep the parser-produced hierarchy context and source metadata aligned
    # with the raw lines for the entire teaching/generalization session.
    session = manager.start(
        unmatched[0].vendor,
        [x.raw_line for x in unmatched],
        unmatched_context_paths=[x.context_path for x in unmatched],
        unmatched_source_metadata=[x.source_metadata or {} for x in unmatched],
    )
    return session
