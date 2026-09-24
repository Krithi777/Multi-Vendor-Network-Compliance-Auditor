from phase7.bge_matcher import InMemoryVectorStore, VectorRecord, BGEMatcher
class P:
    def embed(self,texts): return [[1.,0.]]
def rec():
    return VectorRecord("confirmed line","cisco_ios","management.ssh.version","sig",[1.,0.])
def test_bge_above_threshold():
    s=InMemoryVectorStore(); s.add(rec())
    r=BGEMatcher(P(),s,.8).match("candidate","cisco_ios")
    assert r["accepted"] and r["score"]==1
def test_bge_below_threshold():
    class P2:
        def embed(self,texts): return [[0.,1.]]
    s=InMemoryVectorStore(); s.add(rec())
    r=BGEMatcher(P2(),s,.8).match("candidate","cisco_ios")
    assert not r["accepted"]
def test_no_records():
    s=InMemoryVectorStore()
    assert BGEMatcher(P(),s,.8).match("candidate","cisco_ios") is None
