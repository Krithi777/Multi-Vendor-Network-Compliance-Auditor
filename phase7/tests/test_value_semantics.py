from phase7.value_semantics import *
def test_types():
    assert infer_value(["version","2"]).kind=="numeric"
    assert infer_value(["enabled","yes"]).kind=="boolean"
    assert infer_value(["address","192.168.1.1"]).kind=="ip"
    assert infer_value(["mode","ssh"]).kind=="enum"
def test_negation_gate():
    a=infer_value(["no","telnet"])
    b=infer_value(["telnet"])
    assert not negation_matches(a,[b])
def test_compatible_incompatible():
    assert value_semantics_score(infer_value(["x","2"]),2)==1
    assert value_semantics_score(infer_value(["x","yes"]),2)==0

def test_mixed_negation_examples_are_variable_value_slot():
    yes = infer_value(["root-login", "yes"])
    no = infer_value(["root-login", "no"])
    assert negation_matches(yes, [yes, no])
    assert negation_matches(no, [yes, no])

def test_consistent_negation_still_hard_gates_mismatch():
    no = infer_value(["root-login", "no"])
    yes = infer_value(["root-login", "yes"])
    assert not negation_matches(yes, [no, no, no])
    assert negation_matches(no, [no, no, no])
