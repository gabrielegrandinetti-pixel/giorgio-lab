from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import IntEnum
import json
from typing import Iterable, Optional, Tuple

VERSION = 0

class Agent(IntEnum):
    GIO=0; R=1; D=2; C=3; I=4

class Action(IntEnum):
    ACK=0; NACK=1; HANDOFF=2; VERIFY=3; AUDIT=4; VERDICT=5; BLOCK=6; ESCALATE=7

class State(IntEnum):
    READY=0; PASS_TEST=1; FAIL_TEST=2; VERIFIED=3
    REJECTED_CODE=4; BLOCKED_ENVIRONMENT=5; INCONCLUSIVE=6; BLOCKED_TOOL_ACCESS=7

@dataclass(frozen=True)
class Record:
    sender: Agent
    receiver: Agent
    task: str
    action: Action
    state: State
    candidate_sha: Optional[str]=None
    evidence_ids: Tuple[str, ...]=()
    payload: Optional[str]=None
    version: int=VERSION

class ProtocolError(ValueError):
    pass

def validate(r: Record) -> None:
    if r.version != VERSION: raise ProtocolError("version")
    if not r.task.strip(): raise ProtocolError("task")
    if r.state == State.VERIFIED:
        if r.sender == Agent.D: raise ProtocolError("developer_self_verification")
        if not r.candidate_sha: raise ProtocolError("verified_without_sha")
        if not r.evidence_ids: raise ProtocolError("verified_without_evidence")

def encode(r: Record) -> bytes:
    validate(r)
    d=asdict(r)
    d["sender"]=int(r.sender); d["receiver"]=int(r.receiver)
    d["action"]=int(r.action); d["state"]=int(r.state)
    d["evidence_ids"]=list(r.evidence_ids)
    return json.dumps(d,separators=(",",":"),ensure_ascii=False).encode("utf-8")

def decode(data: bytes) -> Record:
    try:
        d=json.loads(data.decode("utf-8"))
        r=Record(sender=Agent(d["sender"]),receiver=Agent(d["receiver"]),task=d["task"],
                 action=Action(d["action"]),state=State(d["state"]),
                 candidate_sha=d.get("candidate_sha"),
                 evidence_ids=tuple(d.get("evidence_ids",[])),
                 payload=d.get("payload"),version=d["version"])
    except (KeyError, ValueError, TypeError, UnicodeError, json.JSONDecodeError) as e:
        raise ProtocolError("malformed") from e
    validate(r)
    return r
