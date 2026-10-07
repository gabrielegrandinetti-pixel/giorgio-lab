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


from sandbox.casa_giorgio import PASS, FT, INFRA_ERR, classify_run, docker_argv


def test_docker_argv_enforces_isolation(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    wrapper = tmp_path / "runner_wrapper.py"
    wrapper.write_text("# trusted")
    argv = docker_argv("python@sha256:" + "a" * 64, source, wrapper, ("python", "-m", "pytest", "-q", "x.py"))
    joined = " ".join(argv)
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined
    assert "--pids-limit 64" in joined
    assert "--read-only" in argv
    assert "dst=/app,readonly" in joined
    assert "dst=/bin/runner_wrapper.py,readonly" in joined
    assert "bash" not in argv and "sh" not in argv


def test_classifier_requires_trusted_marker():
    assert classify_run(1, b"pytest failed").status == INFRA_ERR


def test_classifier_accepts_wrapper_fail_test():
    marker = b'---BEGIN_G5P_RESULT---\n{"suite_status":"FT"}\n---END_G5P_RESULT---'
    result = classify_run(0, marker)
    assert result.status == FT
    assert result.term_reason == "TEST_FAILURE"


def test_classifier_timeout_beats_marker():
    marker = b'---BEGIN_G5P_RESULT---\n{"suite_status":"PASS"}\n---END_G5P_RESULT---'
    result = classify_run(137, marker, timed_out=True)
    assert result.status == INFRA_ERR
    assert result.term_reason == "TIMEOUT_KILL"
