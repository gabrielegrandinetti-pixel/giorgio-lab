from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

PASS = "PASS"
FT = "FT"
INFRA_ERR = "INFRA_ERR"

SUITES: dict[str, tuple[str, ...]] = {
    "BRIDGE_CORE": ("python", "-m", "pytest", "-q", "tests/acceptance/test_bridge_core_pipeline.py"),
    "ISOLATION_KERNEL": ("python", "-m", "pytest", "-q", "tests/acceptance/test_isolation_kernel.py"),
}

@dataclass(frozen=True)
class Preflight:
    expected_sha: str
    actual_sha: str
    suite_id: str
    argv: tuple[str, ...]


class InfraError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if p.returncode:
        raise InfraError("GIT_ERROR")
    return p.stdout.strip()


def preflight(repo: Path, expected_sha: str, suite_id: str) -> Preflight:
    expected_sha = expected_sha.strip().lower()
    if len(expected_sha) != 40 or any(c not in "0123456789abcdef" for c in expected_sha):
        raise InfraError("INVALID_TARGET_SHA")
    actual = _git(repo, "rev-parse", "HEAD").lower()
    if actual != expected_sha:
        raise InfraError("SOURCE_COMMIT_MISMATCH")
    if _git(repo, "status", "--porcelain"):
        raise InfraError("DIRTY_WORKTREE")
    try:
        argv = SUITES[suite_id]
    except KeyError as exc:
        raise InfraError("UNKNOWN_SUITE_ID") from exc
    return Preflight(expected_sha, actual, suite_id, argv)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def evidence_hash(payload: dict) -> str:
    required = (
        "target_sha", "suite_sha", "env_fp", "exit_code",
        "term_reason", "raw_log_hash",
    )
    material = {k: payload[k] for k in required}
    return sha256_bytes(canonical_json(material))


def seal_evidence(vault: Path, payload: dict) -> Path:
    body = dict(payload)
    body["evi_hash"] = evidence_hash(body)
    vault.mkdir(parents=True, exist_ok=True)
    path = vault / f'{body["evi_hash"]}.json'
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(path, flags, 0o400)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical_json(body))
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    os.chmod(path, 0o400)
    return path


@dataclass(frozen=True)
class SandboxResult:
    status: str
    term_reason: str
    exit_code: int
    raw_log: bytes


def docker_argv(image: str, source: Path, wrapper: Path, suite_argv: Sequence[str]) -> list[str]:
    # Docker receives argv directly. No shell interpolation is used.
    return [
        "docker", "run", "--rm",
        "--network", "none",
        "--cap-drop", "ALL",
        "--pids-limit", "64",
        "--memory", "512m",
        "--cpus", "1.0",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--mount", f"type=bind,src={source.resolve()},dst=/app,readonly",
        "--mount", f"type=bind,src={wrapper.resolve()},dst=/bin/runner_wrapper.py,readonly",
        "--workdir", "/app",
        image,
        "python", "/bin/runner_wrapper.py",
        *suite_argv,
    ]


def classify_run(returncode: int, output: bytes, timed_out: bool = False, oom_killed: bool = False) -> SandboxResult:
    if timed_out:
        return SandboxResult(INFRA_ERR, "TIMEOUT_KILL", returncode, output)
    if oom_killed:
        return SandboxResult(INFRA_ERR, "OOM_KILL", returncode, output)
    begin = b"---BEGIN_G5P_RESULT---"
    end = b"---END_G5P_RESULT---"
    if returncode != 0 or begin not in output or end not in output:
        return SandboxResult(INFRA_ERR, "RUNTIME_FAULT", returncode, output)
    framed = output.split(begin, 1)[1].split(end, 1)[0].strip()
    try:
        marker = json.loads(framed)
    except (ValueError, TypeError):
        return SandboxResult(INFRA_ERR, "INVALID_RESULT_MARKER", returncode, output)
    status = marker.get("suite_status")
    if status == PASS:
        return SandboxResult(PASS, "SUCCESS", returncode, output)
    if status == FT:
        return SandboxResult(FT, "TEST_FAILURE", returncode, output)
    return SandboxResult(INFRA_ERR, "INVALID_RESULT_MARKER", returncode, output)
