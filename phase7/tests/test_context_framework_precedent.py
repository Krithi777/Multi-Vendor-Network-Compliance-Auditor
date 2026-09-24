from phase7.context_scorer import context_score
from phase7.framework_fit import framework_fit
from phase7.value_semantics import infer_value
from phase7.precedent import PrecedentStore
def test_context_exact_and_partial():
    assert context_score("system.services.ssh",["system.services.ssh"])==1
    assert context_score("system.services.ssh",["system.services"])>0
def test_framework_fit_success_failure():
    assert framework_fit(infer_value(["x","2"]),"eq",2)==1
    assert framework_fit(infer_value(["x","3"]),"eq",2)==0
def test_precedent_formula_and_zero():
    p=PrecedentStore()
    assert p.score("v","f","s")==0
    p.add("v","f","s",3); p.add("v","f","other",1)
    assert 0 < p.score("v","f","s") <= 1
