"""Transport-neutral durable Team Runtime spool.

This module deliberately does not know how to reach ChatGPT Library and does not
execute filesystem actions itself.  A caller must provide an authorized handler
that enters Giorgio's existing policy/Core boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any


class RuntimeEnvelopeError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeEnvelope:
    message_id: str
    task_id: str
    body: dict


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _validate(raw: Any) -> RuntimeEnvelope:
    if not isinstance(raw, dict):
        raise RuntimeEnvelopeError("Envelope non oggetto")
    mid, tid, body = raw.get("message_id"), raw.get("task_id"), raw.get("body")
    if not isinstance(mid, str) or not mid.strip() or len(mid) > 200:
        raise RuntimeEnvelopeError("message_id non valido")
    if not isinstance(tid, str) or not tid.strip() or len(tid) > 200:
        raise RuntimeEnvelopeError("task_id non valido")
    if not isinstance(body, dict):
        raise RuntimeEnvelopeError("body non valido")
    return RuntimeEnvelope(mid.strip(), tid.strip(), body)


class LocalTeamRuntimeSpool:
    """Consume immutable JSON inbox files once and emit immutable JSON outbox events.

    The handler is the security boundary adapter supplied by the host application;
    this class never grants permission and never calls Executor directly.
    """

    def __init__(self, root: str | Path, authorized_handler: Callable[[RuntimeEnvelope, str], dict]):
        if not callable(authorized_handler):
            raise TypeError("authorized_handler richiesto")
        self.root = Path(root)
        self.inbox = self.root / "inbox"
        self.outbox = self.root / "outbox"
        self.state = self.root / "state"
        self.processed = self.state / "processed"
        self.handler = authorized_handler
        for p in (self.inbox, self.outbox, self.processed):
            p.mkdir(parents=True, exist_ok=True)

    def _marker(self, message_id: str) -> Path:
        digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()
        return self.processed / f"{digest}.json"

    def process_file(self, path: str | Path) -> dict:
        src = Path(path)
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
            env = _validate(raw)
        except Exception as exc:
            return {"status": "BLOCKED", "reason": "INVALID_ENVELOPE", "error_type": type(exc).__name__}

        marker = self._marker(env.message_id)
        if marker.exists():
            return {"status": "DUPLICATE", "message_id": env.message_id, "task_id": env.task_id}

        trace_id = str(uuid.uuid4())
        try:
            result = self.handler(env, trace_id)
            if not isinstance(result, dict):
                raise TypeError("authorized_handler deve restituire dict")
            status = result.get("status")
            if status not in {"VERIFIED", "BLOCKED", "NOT_APPLIED", "RECOVERY_REQUIRED"}:
                raise RuntimeEnvelopeError("stato handler non ammesso")
        except Exception as exc:
            # Fail closed: a handler failure is not marked processed, allowing safe retry/reconciliation.
            return {
                "status": "BLOCKED", "reason": "AUTHORIZED_PIPELINE_FAILED",
                "message_id": env.message_id, "task_id": env.task_id,
                "trace_id": trace_id, "error_type": type(exc).__name__,
            }

        event = {
            "message_id": f"RUNTIME-{uuid.uuid4()}",
            "task_id": env.task_id,
            "from_agent_id": "giorgio-runtime",
            "to_agent_id": "chatgpt-coordinator",
            "type": "EVIDENCE" if status == "VERIFIED" else "BLOCKER",
            "provenance": "DIRECT_WRITE",
            "ack_of": env.message_id,
            "body": {"trace_id": trace_id, "pipeline_result": result},
        }
        out = self.outbox / f"{env.message_id}.json"
        _atomic_json(out, event)
        _atomic_json(marker, {"message_id": env.message_id, "task_id": env.task_id, "trace_id": trace_id, "outbox": out.name})
        return {"status": status, "message_id": env.message_id, "task_id": env.task_id, "trace_id": trace_id, "outbox": str(out)}
