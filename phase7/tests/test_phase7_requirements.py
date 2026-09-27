from phase7.teaching_session import TeachingSessionManager
from phase7.matcher import Phase7Matcher
from phase7.schemas import CLIExample
from phase7.config import Phase7Config
from phase7.bge_matcher import InMemoryVectorStore
from phase7.template_induction import induce_template
class Provider:
    def embed(self,texts): return [[1.,0.] for _ in texts]
class FakeBGE:
    def __init__(self):
        self.provider=Provider(); self.vector_store=InMemoryVectorStore()
    def match(self,line,vendor):
        return None
def test_four_seed_examples_are_supported_and_embedded_only_after_confirmation():
    c={"x":{"expected_value":2,"operator":"eq"}}
    b=FakeBGE(); m=TeachingSessionManager(Phase7Matcher(c, bge=b), min_examples=4)
    lines=["set x 1","set x 2","set x 3","set x 4","set x 5"]
    s=m.start("v",lines)
    for line in lines[:4]:
        m.confirm(s.session_id,line,"x")
    assert len(b.vector_store.records)==4
    assert s.template is not None
def test_confirmed_mapping_becomes_precedent():
    c={"x":{"expected_value":2,"operator":"eq"}}
    m=TeachingSessionManager(Phase7Matcher(c),min_examples=3)
    lines=["set x 1","set x 2","set x 3","set x 4"]
    s=m.start("v",lines)
    for line in lines[:3]: m.confirm(s.session_id,line,"x")
    assert m.matcher.precedent.count("v","x",s.template.signature)>=3
def test_match_result_exposes_all_component_scores():
    c={"x":{"expected_value":2,"operator":"eq"}}
    ex=[CLIExample("set x 1","v","x","root"),CLIExample("set x 2","v","x","root"),CLIExample("set x 3","v","x","root")]
    t=induce_template([e.raw_line for e in ex])
    r=Phase7Matcher(c).match("set x 2","v",t,ex,"root")
    d=r.to_dict()
    for key in ("syntax_score","context_score","value_semantics_score","framework_fit_score","precedent_score",
                "available_signals","effective_weights","fusion_score","confidence_bucket","decision",
                "matched_template","final_mapping_status"):
        assert key in d
