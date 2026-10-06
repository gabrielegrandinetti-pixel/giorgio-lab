# Win32 File Lock P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that a real Windows exclusive file lock produces a safe, verified `NOT_APPLIED`, then that the same Supervisor verifies the same `MODIFY_FILE` after unlock.

**Architecture:** Exercise the existing `TransactionSupervisor`, spawned `isolated_executor_entry`, `apply_approved`, backup layer, and a read-only verifier. Add only the minimal exception/reconciliation evidence needed if the acceptance test exposes a semantic gap.

**Tech Stack:** Python stdlib `unittest`, `multiprocessing`, `ctypes`, Win32 `CreateFileW`, SHA-256.

**Spec:** `C:\Users\gabri\.codex\attachments\a9e66370-1d60-4421-a94f-9a32d1b313da\Testo incollato.txt`

## Global Constraints

- Work only in the extracted isolated copy; preserve the stable ZIP.
- Use the real Supervisor and MODIFY_FILE pipeline; no pseudocode substitutes.
- The Win32 lock uses `CreateFileW`, `dwShareMode=0`, correct ctypes signatures, 64-bit-safe invalid handle detection, and guaranteed `CloseHandle`.
- No production rewrite, paid service, UI, Ollama, Activity Stream, Pet, memory, or installer work.
- `VERIFIED` comes only from filesystem evidence.

## Review Focus

- A locked target must remain byte-identical and never become `VERIFIED`.
- `NOT_APPLIED` must not be mislabeled `ROLLED_BACK` when no mutation occurred.
- A core exception must retain structured Win32 evidence while filesystem truth determines the terminal state.
- No `.giorgio-*` or journal temporary file may remain after either transaction.
- The same live Supervisor must successfully execute the unlocked retry with no child process leak.

---

### Task 1: Real Win32 lock acceptance test

**Files:**
- Create: `tests/acceptance/test_win32_file_lock.py`

**Interfaces:**
- Consumes: `TransactionSupervisor.submit_transaction(...)`, `TransactionStatus`, `apply_approved(...)`.
- Produces: one Windows-only end-to-end acceptance test and observed evidence for locked/unlocked phases.

- [ ] Write a single test that locks `test_lock.txt`, submits real `MODIFY_FILE`, releases the handle in `finally`, then retries through the same Supervisor.
- [ ] Assert hashes, bytes, size, temporary artifacts, child PIDs, Supervisor state, and journal state for both phases.
- [ ] Run the test and verify it fails for the existing semantic gap rather than setup or ctypes errors.

### Task 2: Minimal Supervisor error reconciliation

**Files:**
- Modify: `core/app_worker.py`
- Modify: `core/executor.py`
- Modify only if semantically obsolete: `tests/acceptance/test_isolation_kernel.py`

**Interfaces:**
- Consumes: existing read-only verifier result and child `CORE_EXCEPTION` event.
- Produces: filesystem-derived `NOT_APPLIED`/`ROLLED_BACK` distinction plus structured exception type, winerror, and traceback evidence.

- [ ] Add a regression assertion for the failing behavior before production code changes.
- [ ] Preserve the child exception evidence and invoke the verifier on `CORE_EXCEPTION`.
- [ ] Preserve `NOT_APPLIED` when the verifier proves the pre-state; preserve `ROLLED_BACK` only when the verifier reports it.
- [ ] Run the dedicated acceptance test until both locked and unlocked phases pass.

### Task 3: Full regression and checkpoint

**Files:**
- Create after all tests pass: `GiorgioCodex_v5_win32_lock_verified.zip`

**Interfaces:**
- Consumes: verified isolated project tree.
- Produces: complete ZIP, SHA-256, and observed test counters/evidence.

- [ ] Run Isolation Kernel Harness, Action Harness, Natural Actions, then the compatible non-GUI unittest suite.
- [ ] Inspect the final journal and verify no child or temporary artifacts remain.
- [ ] Create the complete ZIP only if every required test passes.
- [ ] Hash the final ZIP bytes and report only observed results.

