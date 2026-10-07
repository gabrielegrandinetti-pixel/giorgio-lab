import unittest
from gsp.gsp import Agent, Action, State, Record, ProtocolError, encode, decode

class GSPTests(unittest.TestCase):
    def test_round_trip(self):
        r=Record(Agent.D,Agent.C,"T52",Action.HANDOFF,State.PASS_TEST,
                 "abc123",("E81",))
        self.assertEqual(decode(encode(r)),r)

    def test_verified_requires_evidence(self):
        r=Record(Agent.C,Agent.GIO,"T52",Action.VERDICT,State.VERIFIED,"abc123")
        with self.assertRaises(ProtocolError): encode(r)

    def test_verified_requires_sha(self):
        r=Record(Agent.C,Agent.GIO,"T52",Action.VERDICT,State.VERIFIED,
                 evidence_ids=("E82",))
        with self.assertRaises(ProtocolError): encode(r)

    def test_developer_cannot_self_verify(self):
        r=Record(Agent.D,Agent.GIO,"T52",Action.VERDICT,State.VERIFIED,
                 "abc123",("E82",))
        with self.assertRaises(ProtocolError): encode(r)

    def test_malformed_fails_closed(self):
        with self.assertRaises(ProtocolError): decode(b"{}")

if __name__ == "__main__":
    unittest.main()
