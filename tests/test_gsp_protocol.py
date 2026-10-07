import pytest
from gsp.protocol import Agent, Kind, Level, Record, decode, encode

def test_roundtrip_compact():
    r=Record(Agent.DEVELOPER,Agent.CONTROLLORE,Kind.VERIFY,Level.COMPACT,"PBW-001","abc123","E81")
    assert decode(encode(r))==r

def test_result_requires_evidence():
    with pytest.raises(ValueError):
        Record(Agent.CONTROLLORE,Agent.INSPECTOR,Kind.PASS_,sha="abc123")

def test_verification_requires_sha():
    with pytest.raises(ValueError):
        Record(Agent.DEVELOPER,Agent.CONTROLLORE,Kind.VERIFY,evidence_id="E1")

def test_compact_rejects_free_text():
    with pytest.raises(ValueError):
        Record(Agent.DEVELOPER,Agent.CONTROLLORE,Kind.HANDOFF,payload="ambiguous prose")

def test_bad_magic_rejected():
    r=Record(Agent.DEVELOPER,Agent.CONTROLLORE,Kind.HANDOFF)
    data=bytearray(encode(r)); data[0]=0
    with pytest.raises(ValueError): decode(bytes(data))
