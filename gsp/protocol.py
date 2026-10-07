"""GSP/0 experimental deterministic codec.

Compact transport for routine inter-agent state. It never replaces evidence:
evidence is referenced by immutable IDs and expanded out-of-band.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
import struct

MAGIC=b"GSP"
VERSION=0

class Agent(IntEnum):
    GIOVANNA=1; RESPONSABILE=2; DEVELOPER=3; CONTROLLORE=4; INSPECTOR=5; GIORGIO=6
class Kind(IntEnum):
    ACK=1; HANDOFF=2; VERIFY=3; PASS_=4; FAIL=5; AUDIT=6; VERDICT=7; BLOCKED=8
class Level(IntEnum):
    COMPACT=0; STANDARD=1; FORENSIC=2

@dataclass(frozen=True)
class Record:
    source: Agent
    target: Agent
    kind: Kind
    level: Level=Level.COMPACT
    task_id: str=""
    sha: str=""
    evidence_id: str=""
    payload: str=""

    def __post_init__(self):
        if self.level is Level.COMPACT and self.payload:
            raise ValueError("COMPACT records cannot carry free-text payload")
        if self.kind in (Kind.VERIFY, Kind.PASS_, Kind.FAIL, Kind.AUDIT, Kind.VERDICT) and not self.sha:
            raise ValueError("verification/audit records require sha")
        if self.kind in (Kind.PASS_, Kind.FAIL, Kind.VERDICT) and not self.evidence_id:
            raise ValueError("result records require evidence_id")

def _pack_text(value: str) -> bytes:
    raw=value.encode("utf-8")
    if len(raw)>65535: raise ValueError("field too large")
    return struct.pack("!H",len(raw))+raw

def _unpack_text(data: bytes, offset: int):
    if offset+2>len(data): raise ValueError("truncated field")
    n=struct.unpack_from("!H",data,offset)[0]; offset+=2
    if offset+n>len(data): raise ValueError("truncated field")
    return data[offset:offset+n].decode("utf-8"), offset+n

def encode(record: Record) -> bytes:
    head=struct.pack("!3sBBBBB",MAGIC,VERSION,int(record.source),int(record.target),int(record.kind),int(record.level))
    return head+b"".join(_pack_text(v) for v in (record.task_id,record.sha,record.evidence_id,record.payload))

def decode(data: bytes) -> Record:
    if len(data)<8: raise ValueError("truncated GSP record")
    magic,version,source,target,kind,level=struct.unpack_from("!3sBBBBB",data,0)
    if magic!=MAGIC: raise ValueError("invalid GSP magic")
    if version!=VERSION: raise ValueError("unsupported GSP version")
    off=8; values=[]
    for _ in range(4):
        value,off=_unpack_text(data,off); values.append(value)
    if off!=len(data): raise ValueError("trailing bytes")
    return Record(Agent(source),Agent(target),Kind(kind),Level(level),*values)
