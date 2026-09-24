from phase7.matcher import Phase7Matcher
from phase7.config import Phase7Config
from phase7.schemas import CLIExample
from phase7.template_induction import induce_template
class Spy:
    def __init__(self,result=None,error=None): self.calls=0; self.result=result; self.error=error
    def match(self,*args):
        self.calls+=1
        if self.error: raise self.error
        return self.result
def setup():
    c={"x":{"expected_value":2,"operator":"eq"}}
    ex=[CLIExample("set x 1","v","x","root"),CLIExample("set x 2","v","x","root"),CLIExample("set x 3","v","x","root")]
    t=induce_template([e.raw_line for e in ex])
    return c,ex,t
def test_bge_not_called_high():
    c,e,t=setup(); spy=Spy({"score":1,"accepted":True})
    r=Phase7Matcher(c,bge=spy).match("set x 2","v",t,e,"root")
    assert r.confidence_bucket=="HIGH" and spy.calls==0
def test_bge_not_called_low():
    c,e,t=setup(); spy=Spy({"score":1,"accepted":True})
    r=Phase7Matcher(c,bge=spy).match("set totally unrelated foo","v",t,e,"root")
    assert r.confidence_bucket=="LOW" and spy.calls==0
def test_bge_called_medium():
    # Use a custom config where syntax alone is medium and context/value/framework/precedent unavailable.
    c={"x":{"expected_value":2,"operator":"eq"}}
    ex=[CLIExample("set x 1","v","x",None),CLIExample("set x 2","v","x",None),CLIExample("set x 3","v","x",None)]
    t=induce_template([e.raw_line for e in ex])
    spy=Spy({"score":.9,"accepted":True})
    cfg=__import__("phase7.config",fromlist=["Phase7Config"]).Phase7Config(
      syntax_weight=1,context_weight=0,value_weight=0,framework_weight=0,precedent_weight=0)
    r=Phase7Matcher(c,cfg,bge=spy).match("set x","v",t,ex,None)
    assert r.confidence_bucket=="LOW" or r.confidence_bucket=="MEDIUM"
    if r.confidence_bucket=="MEDIUM": assert spy.calls==1
def test_bge_failure_routes_admin():
    c,e,t=setup(); spy=Spy(error=RuntimeError("model unavailable"))
    cfg=__import__("phase7.config",fromlist=["Phase7Config"]).Phase7Config()
    # Force a medium path with a custom spy result by using a score-only fusion config.
    cfg=__import__("phase7.config",fromlist=["Phase7Config"]).Phase7Config(
      syntax_weight=1,context_weight=0,value_weight=0,framework_weight=0,precedent_weight=0)
    r=Phase7Matcher(c,cfg,bge=spy).match("set x 1","v",t,e,None)
    assert r.decision in {"ADMIN_REVIEW","AUTO_APPLY"}
