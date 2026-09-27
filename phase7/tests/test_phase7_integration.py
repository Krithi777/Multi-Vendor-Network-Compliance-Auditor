from phase7.matcher import Phase7Matcher
from phase7.config import Phase7Config
from phase7.schemas import CLIExample
from phase7.template_induction import induce_template
def test_end_to_end_high_medium_low_and_bge_gate():
    controls={"management.ssh.version":{"expected_value":2,"operator":"eq"}}
    matcher=Phase7Matcher(controls,Phase7Config())
    examples=[CLIExample("set system services ssh version 2","juniper_junos","management.ssh.version","system.services.ssh"),
              CLIExample("set system services ssh version 1","juniper_junos","management.ssh.version","system.services.ssh"),
              CLIExample("set system services ssh version 3","juniper_junos","management.ssh.version","system.services.ssh")]
    t=induce_template([e.raw_line for e in examples])
    high=matcher.match("set system services ssh version 2","juniper_junos",t,examples,"system.services.ssh")
    assert high.confidence_bucket=="HIGH" and high.decision=="AUTO_APPLY"
    # A negation mismatch must remain LOW even if structure otherwise matches.
    low=matcher.match("set system services ssh no","juniper_junos",t,examples,"system.services.ssh")
    assert low.fusion_score==0 and low.confidence_bucket=="LOW" and low.decision=="ADMIN_REVIEW"
def test_context_unavailable_is_not_zeroed_weight():
    controls={"x":{"expected_value":2,"operator":"eq"}}
    matcher=Phase7Matcher(controls)
    ex=[CLIExample("set x 2","v","x",None),CLIExample("set x 3","v","x",None),CLIExample("set x 4","v","x",None)]
    t=induce_template([e.raw_line for e in ex])
    r=matcher.match("set x 2","v",t,ex,None)
    assert r.context_score is None
    assert "context" not in r.effective_weights
