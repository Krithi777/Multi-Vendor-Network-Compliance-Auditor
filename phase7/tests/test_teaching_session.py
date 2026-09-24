from phase7.teaching_session import TeachingSessionManager
from phase7.matcher import Phase7Matcher
from phase7.config import Phase7Config
CONT={"management.ssh.version":{"expected_value":2,"operator":"eq"}}
def manager():
    return TeachingSessionManager(Phase7Matcher(CONT,Phase7Config()),min_examples=3)
def test_three_confirmations_generalize():
    m=manager()
    lines=["set system services ssh version 2","set system services ssh version 1",
           "set system services ssh version 3","set system services ssh version 4"]
    s=m.start("juniper_junos",lines)
    m.confirm(s.session_id,lines[0],"management.ssh.version","system.services.ssh")
    m.confirm(s.session_id,lines[1],"management.ssh.version","system.services.ssh")
    s=m.confirm(s.session_id,lines[2],"management.ssh.version","system.services.ssh")
    assert s.state.value=="COMPLETED"
    assert s.template.text=="set system services ssh version {VALUE}"
    assert len(s.results)==1
def test_zero_unmatched_skips_phase7():
    m=manager()
    assert m.start("cisco_ios",[]) is None
def test_session_can_resume_in_memory():
    m=manager(); s=m.start("cisco_ios",["set ssh version 2","set ssh version 1","set ssh version 3"])
    m.confirm(s.session_id,s.unmatched_lines[0],"management.ssh.version")
    assert m.status(s.session_id).state.value=="TEACHING"

def test_session_resumes_from_repository_after_manager_restart():
    class Repo:
        def __init__(self): self.saved = {}
        def save(self, session): self.saved[session.session_id] = session
        def load(self, sid): return self.saved[sid]

    repo = Repo()
    first = TeachingSessionManager(Phase7Matcher(CONT, Phase7Config()), repository=repo, min_examples=3)
    s = first.start("cisco_ios", ["set ssh version 2", "set ssh version 1", "set ssh version 3"])
    first.confirm(s.session_id, s.unmatched_lines[0], "management.ssh.version")

    restarted = TeachingSessionManager(Phase7Matcher(CONT, Phase7Config()), repository=repo, min_examples=3)
    resumed = restarted.status(s.session_id)
    assert resumed.session_id == s.session_id
    assert resumed.state.value == "TEACHING"
    restarted.confirm(s.session_id, s.unmatched_lines[1], "management.ssh.version")
    assert len(restarted.status(s.session_id).confirmations) == 2
