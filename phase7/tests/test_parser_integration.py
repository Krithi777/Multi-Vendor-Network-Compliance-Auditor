from phase7.parser_adapter import collect_unmatched
from phase7.integration import start_from_parser_output
from phase7.teaching_session import TeachingSessionManager
from phase7.matcher import Phase7Matcher
def test_recognized_bypass_and_unmatched_preserved():
    rows=[{"vendor":"v","raw_line":"known","matched":True,"context_path":"root"},
          {"vendor":"v","raw_line":"unknown","matched":False,"context_path":"root","line_number":8}]
    out=collect_unmatched(rows)
    assert len(out)==1 and out[0].raw_line=="unknown" and out[0].line_number==8
def test_integration_zero_unmatched_returns_none():
    m=TeachingSessionManager(Phase7Matcher({"x":{"expected_value":2,"operator":"eq"}}))
    assert start_from_parser_output(m,[{"vendor":"v","raw_line":"known","recognized":True}]) is None

def test_integration_preserves_parser_context_for_generalization():
    from phase7.integration import start_from_parser_output
    from phase7.teaching_session import TeachingSessionManager
    from phase7.matcher import Phase7Matcher
    from phase7.config import Phase7Config

    manager = TeachingSessionManager(
        Phase7Matcher({"management.ssh.version": {"expected_value": 2, "operator": "eq"}}, Phase7Config()),
        min_examples=3,
    )
    rows = [
        {"vendor":"juniper_junos", "raw_line":"set system services ssh version 2", "matched":False, "context_path":"system.services.ssh"},
        {"vendor":"juniper_junos", "raw_line":"set system services ssh version 1", "matched":False, "context_path":"system.services.ssh"},
        {"vendor":"juniper_junos", "raw_line":"set system services ssh version 3", "matched":False, "context_path":"system.services.ssh"},
        {"vendor":"juniper_junos", "raw_line":"set system services ssh version 4", "matched":False, "context_path":"system.services.ssh"},
    ]
    session = start_from_parser_output(manager, rows)
    manager.confirm(session.session_id, rows[0]["raw_line"], "management.ssh.version")
    manager.confirm(session.session_id, rows[1]["raw_line"], "management.ssh.version")
    manager.confirm(session.session_id, rows[2]["raw_line"], "management.ssh.version")
    assert session.unmatched_context_paths == ["system.services.ssh"] * 4
    assert session.results[0].context_score == 1.0
