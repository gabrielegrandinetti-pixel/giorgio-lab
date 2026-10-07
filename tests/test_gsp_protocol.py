"""Reference conformance tests for GSP v0.1 semantics.

These tests deliberately test protocol invariants before any binary codec exists.
"""
from dataclasses import dataclass
from typing import Tuple

ROLES = {"GIO", "RESP", "DEV", "CTRL", "INSP"}
OPCODES = {"ACK","NACK","HANDOFF","VERIFY_REQUEST","AUDIT_REQUEST","PASS_TEST","FAIL_TEST","BLOCKED","VERDICT","EVIDENCE","ESCALATE"}

@dataclass(frozen=True)
class Record:
    version: int
    message_id: str
    sender: str
    receiver: str
    task: str
    candidate_sha: str
    opcode: str
    evidence_refs: Tuple[str, ...] = ()

def validate(r: Record) -> None:
    if r.version != 1:
        raise ValueError("unsupported_version")
    if r.sender not in ROLES or r.receiver not in ROLES:
        raise ValueError("unknown_role")
    if r.opcode not in OPCODES:
        raise ValueError("unknown_opcode")
    if not r.message_id or not r.task or not r.candidate_sha:
        raise ValueError("missing_required_field")

def same_candidate(a: Record, b: Record) -> None:
    validate(a); validate(b)
    if a.candidate_sha != b.candidate_sha:
        raise ValueError("candidate_sha_mismatch")

def test_valid_compact_record():
    validate(Record(1,"m1","DEV","CTRL","T1","abc123","VERIFY_REQUEST",("E1",)))

def test_unknown_opcode_rejected():
    try:
        validate(Record(1,"m1","DEV","CTRL","T1","abc123","MAGIC"))
    except ValueError as e:
        assert str(e) == "unknown_opcode"
    else:
        raise AssertionError("unknown opcode accepted")

def test_candidate_mismatch_rejected():
    a=Record(1,"m1","DEV","CTRL","T1","abc","HANDOFF")
    b=Record(1,"m2","CTRL","INSP","T1","def","AUDIT_REQUEST")
    try:
        same_candidate(a,b)
    except ValueError as e:
        assert str(e) == "candidate_sha_mismatch"
    else:
        raise AssertionError("candidate mismatch accepted")
