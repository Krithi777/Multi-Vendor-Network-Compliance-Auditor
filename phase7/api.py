"""Framework-neutral service boundary for FastAPI/Next.js integration in Phase 9."""
from .teaching_session import TeachingSessionManager

def start_teaching_session(manager: TeachingSessionManager, vendor: str, unmatched_lines: list[str]):
    return manager.start(vendor, unmatched_lines)

def submit_admin_confirmation(manager, session_id, raw_line, canonical_field, context_path=None, source_metadata=None):
    return manager.confirm(session_id, raw_line, canonical_field, context_path, source_metadata)

def learn_template(manager, session_id):
    session=manager.status(session_id)
    if session.template is None:
        raise ValueError("Teaching threshold has not been reached")
    return session.template

def generalize(manager, session_id):
    # Confirmation automatically triggers generalization once the seed count is reached.
    return manager.results(session_id)

def query_bge(manager, session_id, line):
    session=manager.status(session_id)
    if session.template is None:
        raise ValueError("No learned template")
    return manager.matcher.match(line,session.vendor,session.template,session.confirmations)

def get_session_status(manager, session_id):
    s=manager.status(session_id)
    return {"session_id":s.session_id,"state":s.state.value,"confirmed_count":len(s.confirmations),
            "unmatched_count":len(s.unmatched_lines),"results":manager.results(session_id) if s.state.value=="COMPLETED" else None}
