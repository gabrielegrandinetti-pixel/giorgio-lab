"""Dependency-light crash-aware transaction supervisor.

This module deliberately avoids importing the agent/Ollama runtime so the safety
pipeline can be collected and tested in headless environments.
"""
from pathlib import Path
import json as _json
import multiprocessing as _mp
import os as _os
import tempfile as _tempfile
import threading as _threading
import time as _time
from dataclasses import dataclass as _dataclass, asdict as _asdict, field as _field
from enum import Enum as _Enum
from typing import Any as _Any, Callable as _Callable, Optional as _Optional
from core.executor import isolated_executor_entry as _isolated_executor_entry


class JournalRecoveryRequired(RuntimeError):
    pass


class SupervisorState(_Enum):
    RUNNING = 'RUNNING'
    STOPPING = 'STOPPING'
    STOPPED = 'STOPPED'
    JOURNAL_RECOVERY_REQUIRED = 'JOURNAL_RECOVERY_REQUIRED'


class TransactionStatus(_Enum):
    PENDING = 'PENDING'
    RUNNING = 'RUNNING'
    VERIFIED = 'VERIFIED'
    VERIFIED_LATE = 'VERIFIED_LATE'
    VERIFIED_AFTER_RESTART = 'VERIFIED_AFTER_RESTART'
    FAILED = 'FAILED'
    ROLLED_BACK = 'ROLLED_BACK'
    NOT_APPLIED = 'NOT_APPLIED'
    RECOVERY_REQUIRED = 'RECOVERY_REQUIRED'
    NEEDS_RECONCILIATION = 'NEEDS_RECONCILIATION'
    CANCELLED = 'CANCELLED'


_TERMINAL = {s.value for s in TransactionStatus if s not in {
    TransactionStatus.PENDING, TransactionStatus.RUNNING, TransactionStatus.NEEDS_RECONCILIATION
}}


@_dataclass
class TaskJournalRecord:
    task_id: str
    capability: str
    arguments: dict
    status: str
    created_at: float
    deadline_seconds: float
    pid: _Optional[int] = None
    pre_evidence: dict = _field(default_factory=dict)
    expected_evidence: dict = _field(default_factory=dict)
    terminal_result: _Optional[dict] = None


class TransactionSupervisor:
    """Crash-aware process supervisor used by the P0 isolation harness.

    verifier(task_record) must be read-only and return one of:
    VERIFIED, ROLLED_BACK/NOT_APPLIED, or RECOVERY_REQUIRED/FAILED.
    """
    def __init__(self, journal_path, executor_func, verifier_func, recovery_func=None,
                 start_timeout=2.0, kill_grace=0.25):
        self.journal_path = Path(journal_path).resolve()
        self.executor_func = executor_func
        self.verifier_func = verifier_func
        self.recovery_func = recovery_func
        self.start_timeout = float(start_timeout)
        self.kill_grace = float(kill_grace)
        self.state = SupervisorState.RUNNING
        self.registry = {}
        self._children = {}
        self._lock = _threading.RLock()
        self._ctx = _mp.get_context('spawn')
        self._load_journal_fail_closed()

    def _load_journal_fail_closed(self):
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.journal_path.exists():
            self._save_journal_atomic()
            return
        try:
            raw = _json.loads(self.journal_path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                raise ValueError('journal root must be an object')
            self.registry = {key: TaskJournalRecord(**value) for key, value in raw.items()}
        except Exception as exc:
            self.state = SupervisorState.JOURNAL_RECOVERY_REQUIRED
            raise JournalRecoveryRequired(f'Journal non leggibile: {exc}') from exc

    def _save_journal_atomic(self):
        payload = _json.dumps({k: _asdict(v) for k, v in self.registry.items()},
                              ensure_ascii=False, sort_keys=True, indent=2)
        fd, temp_name = _tempfile.mkstemp(prefix='.giorgio-journal-', suffix='.tmp',
                                          dir=str(self.journal_path.parent))
        try:
            with _os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
                stream.write(payload)
                stream.flush()
                _os.fsync(stream.fileno())
            _os.replace(temp_name, self.journal_path)
            # Best effort directory durability on POSIX; Windows rejects O_DIRECTORY.
            if hasattr(_os, 'O_DIRECTORY'):
                dfd = _os.open(str(self.journal_path.parent), _os.O_DIRECTORY)
                try:
                    _os.fsync(dfd)
                finally:
                    _os.close(dfd)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def _persist(self, record, status=None, terminal_result=None):
        with self._lock:
            if status is not None:
                record.status = status.value if isinstance(status, TransactionStatus) else str(status)
            if terminal_result is not None:
                record.terminal_result = terminal_result
            self.registry[record.task_id] = record
            self._save_journal_atomic()

    @staticmethod
    def _normalize_result(result):
        if not isinstance(result, dict):
            return TransactionStatus.FAILED, {'error': 'malformed_core_result'}
        status = result.get('status')
        try:
            parsed = TransactionStatus(status)
        except Exception:
            return TransactionStatus.FAILED, {'error': 'malformed_core_status', 'raw': repr(status)}
        if parsed in {TransactionStatus.PENDING, TransactionStatus.RUNNING,
                      TransactionStatus.NEEDS_RECONCILIATION}:
            return TransactionStatus.FAILED, {'error': 'non_terminal_core_status'}
        return parsed, result

    def _reconcile(self, record, after_restart=False, core_error=None):
        observed = self.verifier_func(record)
        status, evidence = self._normalize_result(observed)
        if status in {TransactionStatus.VERIFIED, TransactionStatus.VERIFIED_LATE,
                      TransactionStatus.VERIFIED_AFTER_RESTART}:
            final = TransactionStatus.VERIFIED_AFTER_RESTART if after_restart else TransactionStatus.VERIFIED_LATE
        elif status is TransactionStatus.ROLLED_BACK:
            final = TransactionStatus.ROLLED_BACK
        elif status is TransactionStatus.NOT_APPLIED:
            final = TransactionStatus.NOT_APPLIED
        else:
            final = TransactionStatus.RECOVERY_REQUIRED
            if self.recovery_func is not None:
                # Recovery is deliberately separate from verifier. Its return is evidence;
                # reconciliation remains RECOVERY_REQUIRED until a later read-only verify.
                try:
                    recovery = self.recovery_func(record)
                    evidence = {'reconcile': evidence, 'recovery': recovery}
                except Exception as exc:
                    evidence = {'reconcile': evidence, 'recovery_error': str(exc)}
        if core_error is not None:
            evidence = {'verifier': evidence, 'core_error': core_error}
        self._persist(record, final, evidence)
        return final

    def submit_transaction(self, task_id, capability, arguments, timeout=5.0,
                           pre_evidence=None, expected_evidence=None):
        with self._lock:
            if self.state is not SupervisorState.RUNNING:
                return TransactionStatus.FAILED
            if task_id in self.registry:
                return TransactionStatus.FAILED
            record = TaskJournalRecord(task_id, capability, dict(arguments),
                                       TransactionStatus.PENDING.value, _time.time(), float(timeout),
                                       pre_evidence=dict(pre_evidence or {}),
                                       expected_evidence=dict(expected_evidence or {}))
            self._persist(record, TransactionStatus.PENDING)

        parent, child = self._ctx.Pipe(duplex=True)
        process = self._ctx.Process(target=_isolated_executor_entry,
                                    args=(child, task_id, capability, dict(arguments), self.executor_func))
        process.start()
        child.close()
        try:
            if not parent.poll(self.start_timeout):
                self._terminate(process)
                self._persist(record, TransactionStatus.FAILED, {'error': 'started_timeout'})
                return TransactionStatus.FAILED
            started = parent.recv()
            if not isinstance(started, dict) or started.get('event') != 'STARTED' or started.get('pid') != process.pid:
                self._terminate(process)
                self._persist(record, TransactionStatus.FAILED, {'error': 'invalid_started_handshake'})
                return TransactionStatus.FAILED

            # Critical barrier: PID + RUNNING reach durable journal before authorization.
            record.pid = process.pid
            self._persist(record, TransactionStatus.RUNNING)
            with self._lock:
                if self.state is not SupervisorState.RUNNING:
                    self._terminate(process)
                    return self._reconcile(record)
                self._children[task_id] = process
            parent.send({'event': 'EXECUTE_ALLOWED', 'task_id': task_id})

            deadline = _time.monotonic() + float(timeout)
            while _time.monotonic() < deadline:
                remaining = max(0.0, deadline - _time.monotonic())
                if parent.poll(min(0.05, remaining)):
                    try:
                        message = parent.recv()
                    except (EOFError, OSError):
                        # A concurrent shutdown/termination can close the child end.
                        # The filesystem, not the broken IPC channel, decides the outcome.
                        return self._reconcile(record)
                    if isinstance(message, dict) and message.get('event') == 'CORE_RESULT':
                        status, evidence = self._normalize_result(message.get('result'))
                        process.join(timeout=self.kill_grace)
                        if process.is_alive():
                            self._terminate(process)
                        self._persist(record, status, evidence)
                        return status
                    if isinstance(message, dict) and message.get('event') == 'CORE_EXCEPTION':
                        process.join(timeout=self.kill_grace)
                        if process.is_alive():
                            self._terminate(process)
                        core_error = message.get('error') or {}
                        if core_error.get('winerror') is not None or core_error.get('errno') is not None:
                            return self._reconcile(record, core_error=core_error)
                        self._persist(record, TransactionStatus.FAILED, core_error)
                        return TransactionStatus.FAILED
                if not process.is_alive():
                    # Died without a terminal message: filesystem truth decides.
                    return self._reconcile(record)

            self._terminate(process)
            return self._reconcile(record)
        finally:
            with self._lock:
                self._children.pop(task_id, None)
            try:
                parent.close()
            except Exception:
                pass
            try:
                process.close()
            except Exception:
                pass

    def _terminate(self, process):
        if process.is_alive():
            process.terminate()
            process.join(timeout=self.kill_grace)
        if process.is_alive() and hasattr(process, 'kill'):
            process.kill()
            process.join(timeout=self.kill_grace)

    def reconcile_after_restart(self):
        results = {}
        for record in list(self.registry.values()):
            if record.status == TransactionStatus.RUNNING.value:
                self._persist(record, TransactionStatus.NEEDS_RECONCILIATION)
                results[record.task_id] = self._reconcile(record, after_restart=True)
        return results

    def shutdown(self):
        with self._lock:
            if self.state is SupervisorState.STOPPED:
                return
            self.state = SupervisorState.STOPPING
            children = list(self._children.items())
        for task_id, process in children:
            self._terminate(process)
            record = self.registry.get(task_id)
            if record and record.status == TransactionStatus.RUNNING.value:
                self._reconcile(record)
        # PENDING tasks were never authorized; classify them without executing.
        for record in list(self.registry.values()):
            if record.status == TransactionStatus.PENDING.value:
                self._persist(record, TransactionStatus.CANCELLED, {'reason': 'shutdown_before_execution'})
        with self._lock:
            self.state = SupervisorState.STOPPED
            self._save_journal_atomic()
