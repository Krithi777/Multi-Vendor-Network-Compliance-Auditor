from phase7.fusion import fuse
from phase7.config import Phase7Config
def test_buckets_and_boundaries():
    c=Phase7Config()
    s,b,_,_=fuse(dict(syntax=1,context=1,value_semantics=1,framework_fit=1,precedent=1),c)
    assert b=="HIGH" and s==1
    # construct exact boundaries by equal values
    c2=Phase7Config(syntax_weight=1,context_weight=0,value_weight=0,framework_weight=0,precedent_weight=0)
    assert fuse({"syntax":.85,"context":None,"value_semantics":None,"framework_fit":None,"precedent":None},c2)[1]=="HIGH"
    assert fuse({"syntax":.60,"context":None,"value_semantics":None,"framework_fit":None,"precedent":None},c2)[1]=="MEDIUM"
    assert fuse({"syntax":.5999,"context":None,"value_semantics":None,"framework_fit":None,"precedent":None},c2)[1]=="LOW"
def test_missing_context_renormalizes():
    c=Phase7Config()
    scores={"syntax":1,"context":None,"value_semantics":1,"framework_fit":1,"precedent":1}
    score,_,weights,_=fuse(scores,c)
    assert "context" not in weights
    assert abs(sum(weights.values())-1)<1e-9
def test_negation_forces_zero():
    c=Phase7Config()
    assert fuse({"syntax":1,"context":1,"value_semantics":1,"framework_fit":1,"precedent":1},c,negation_mismatch=True)[0]==0
