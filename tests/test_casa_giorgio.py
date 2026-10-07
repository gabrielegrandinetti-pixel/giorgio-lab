import json
import os
from pathlib import Path

import pytest

from sandbox.casa_giorgio import InfraError, evidence_hash, seal_evidence


def test_evidence_hash_is_deterministic():
    payload = {
        "target_sha": "a" * 40,
        "suite_sha": "b" * 64,
        "env_fp": "c" * 64,
        "exit_code": 0,
        "term_reason": "SUCCESS",
        "raw_log_hash": "d" * 64,
    }
    assert evidence_hash(payload) == evidence_hash(dict(reversed(list(payload.items()))))


def test_seal_evidence_is_exclusive_and_read_only(tmp_path: Path):
    payload = {
        "target_sha": "a" * 40,
        "suite_sha": "b" * 64,
        "env_fp": "c" * 64,
        "exit_code": 0,
        "term_reason": "SUCCESS",
        "raw_log_hash": "d" * 64,
    }
    path = seal_evidence(tmp_path, payload)
    stored = json.loads(path.read_text())
    assert stored["evi_hash"] == evidence_hash(payload)
    assert (path.stat().st_mode & 0o777) == 0o400
    with pytest.raises(FileExistsError):
        seal_evidence(tmp_path, payload)
