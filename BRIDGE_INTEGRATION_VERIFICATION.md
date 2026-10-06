# Giorgio Codex v5 — Bridge Ollama/Core verification

Date: 2026-10-06

## Genealogy

`bridge-v1-task1 -> bridge-v1-task2 (11 tests) -> bridge-v1-ollama-provider (14 tests)`

The historical Task 2 checkpoint was not changed. The distinct
`checkpoints/bridge-v1-ollama-provider/` checkpoint contains the later five-file
Bridge state and its own SHA-256 manifest; verification reported 0 discrepancies.

## PRESENTE NEL CODICE

- Strict, fail-closed `MODIFY_FILE` Bridge contracts and parser.
- Injected-transport Ollama provider with typed provider failures.
- Pure Bridge-to-Core adapter requiring a target-bound permission and pre-state hash.
- Existing Supervisor execution boundary with independent read-only verification.
- Explicit real-Ollama E2E runner excluded from ordinary unittest discovery.

## TESTATO CON MOCK

- Bridge contracts/parser/provider: 14/14 PASS.
- Adapter: 6/6 PASS, including malformed types, unsafe paths, digest mismatch,
  denied/mismatched permission, and zero filesystem mutation.

## VERIFICATO SU WINDOWS

- Bridge + adapter + Core pipeline: 22/22 PASS.
- Win32 exclusive lock: 1/1 PASS (`NOT_APPLIED` while locked, `VERIFIED` after unlock).
- Isolation Kernel: 14/14 PASS.
- Deterministic Action Harness: 270/270 PASS.
- Natural Actions: 18/18 PASS.
- Non-GUI regression suite: 64/64 PASS.

## VERIFICATO CON OLLAMA REALE

- Model: `qwen3:4b-instruct`.
- Deterministic parser fallback confirmed before calling Ollama.
- Provider returned a strict `MODIFY_FILE` intent with no Bridge error.
- Final measured duration: 8,888 ms.
- Pre SHA-256: `9bc35ec0b931276787da44b5592cb6dc755fdb4f89e44b1592dc1f8c465aa2db`.
- Expected/post SHA-256: `eb55da14a180316ffd15a54eab7d82b11ff65dd6c342096639ae2a1b90f9d06d`.

## E2E CORE VERIFIED

- Capability: `MODIFY_FILE`.
- Core status: `VERIFIED`.
- Journal status: `VERIFIED`.
- Independent verifier status: `VERIFIED`.
- Final file hash exactly matched the Bridge-derived expected hash.

## NON VERIFICATO / BLOCCATO

- None in the approved Bridge v1 scope.
- Groq and actions other than `MODIFY_FILE` remain intentionally out of scope.
