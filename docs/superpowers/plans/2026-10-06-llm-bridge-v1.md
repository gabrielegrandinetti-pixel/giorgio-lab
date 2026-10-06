# LLM Bridge v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify an isolated, immutable, fail-closed LLM Bridge that can emit only validated `MODIFY_FILE` intents from Ollama or Groq raw responses.

**Architecture:** Add a new `core.bridge` package without changing the existing deterministic parser, Supervisor, executor, or verifier. Provider adapters isolate transport failures; a zero-I/O strict parser produces immutable success/error results and independently computes the expected SHA-256 digest.

**Tech Stack:** Python 3 standard library (`abc`, `dataclasses`, `enum`, `hashlib`, `json`, `ntpath`, `re`, `unittest`, `unittest.mock`).

**Spec:** `docs/superpowers/specs/2026-10-06-llm-bridge-v1-design.md`

## Global Constraints

- Work only on a copy/checkpoint derived from `GiorgioCodex_v5_win32_lock_verified`; preserve the verified ZIP.
- Version 1 authorizes only `MODIFY_FILE`.
- The parser performs zero filesystem, network, Journal, Supervisor, or system API I/O.
- Acceptance tests use deterministic fake transports; no real Ollama or Groq endpoint.
- Invalid data fails closed as a typed `BridgeResult`; no Bridge exception crosses the public provider boundary.
- Do not connect the Bridge to production Supervisor execution in this plan.
- This extracted baseline has no Git metadata; create recoverable filesystem checkpoints instead of commits.

## Review Focus

- Unicode separator lookalikes and normalized Windows separators must not create a traversal bypass; Task 2 tests literal `\\`, `/`, mixed separators, and components after normalization.
- JSON objects with boolean/null/container values in string fields must be rejected rather than coerced; Task 2 tests every field type boundary.
- Duplicate keys at nested and top-level objects must fail closed; Task 2 uses repeated `action_type`, `parameters`, and `target_path` keys.
- UTF-8 byte size, not Python character count, controls the 2 MiB content limit; Task 3 tests multibyte content on both sides of the boundary.
- A transport returning a `str` subclass or raising `BaseException` outside ordinary `Exception` must have deliberate behavior; Task 4 accepts normal strings/subclasses and converts ordinary exceptions only, while `KeyboardInterrupt`/`SystemExit` remain process-control signals.

---

### Task 1: Immutable Bridge contracts

**Files:**
- Create: `core/bridge/__init__.py`
- Create: `core/bridge/base_provider.py`
- Create: `tests/acceptance/test_llm_bridge.py`

**Interfaces:**
- Consumes: no existing production interface.
- Produces: `BridgeErrorCode`, `ActionIntent`, `BridgeError`, `BridgeResult`, and abstract `LLMBridgeProvider.request_intent(prompt: str) -> BridgeResult`.

- [ ] **Step 1: Write failing contract tests**

Add tests named `test_bridge_result_requires_exactly_one_variant`, `test_action_intent_and_result_are_frozen`, and `test_provider_interface_is_abstract`. Assert construction fails for zero/two variants, attribute assignment raises `FrozenInstanceError`, and the base provider cannot be instantiated.

- [ ] **Step 2: Run contract tests and verify RED**

Run: `python -m unittest tests.acceptance.test_llm_bridge.BridgeContractTests -v`

Expected: import failure because `core.bridge` does not exist.

- [ ] **Step 3: Implement the immutable contract**

Create the exact dataclasses and enum from the design. `BridgeResult.__post_init__` raises `ValueError` unless exactly one variant is set. Define `LLMBridgeProvider` with abstract `provider_name: str` and `request_intent(prompt: str) -> BridgeResult`.

- [ ] **Step 4: Run contract tests and verify GREEN**

Run the Step 2 command. Expected: all `BridgeContractTests` pass.

- [ ] **Step 5: Save checkpoint `checkpoints/bridge-v1-task1/`**

Copy only the new package and acceptance test into the checkpoint; record SHA-256 hashes in `checkpoints/bridge-v1-task1/SHA256SUMS.txt`.

### Task 2: Strict JSON schema and lexical path validation

**Files:**
- Create: `core/bridge/intent_parser.py`
- Modify: `core/bridge/__init__.py`
- Modify: `tests/acceptance/test_llm_bridge.py`

**Interfaces:**
- Consumes: Task 1 immutable contracts.
- Produces: `parse_intent(raw_response: str) -> BridgeResult` and private pure validators.

- [ ] **Step 1: Write failing syntax/schema tests**

Add literal fixtures for valid raw JSON, malformed JSON, Markdown fences, prefix/suffix prose, multiple JSON values, non-object roots, unknown keys, missing keys, wrong types, and duplicate keys at every object level. Assert only the valid fixture reaches an `ActionIntent`; all other cases return `INVALID_INTENT` without raising.

- [ ] **Step 2: Write failing action/path tests**

Assert `CREATE`, `DELETE`, and `EXECUTE` return `UNSUPPORTED_ACTION`. Assert rejection of `..`, `.`, empty components, absolute POSIX paths, drive absolute/relative paths, UNC/device paths, ADS colons, illegal characters, controls/NUL, trailing dot/space, and reserved device basenames. Assert one normalized relative mixed-separator path becomes `src/main.py`.

- [ ] **Step 3: Prove zero-I/O and verify RED**

Patch `builtins.open`, `pathlib.Path.resolve`, `pathlib.Path.exists`, `pathlib.Path.stat`, and `os.stat` to raise if called; parse one valid and one invalid payload. Run `python -m unittest tests.acceptance.test_llm_bridge.StrictParserTests -v` and confirm failure is due to missing parser behavior, not fixture errors.

- [ ] **Step 4: Implement strict decoding and field/path validation**

Use `json.JSONDecoder`/`json.loads` with `object_pairs_hook` that rejects duplicate keys, exact key-set comparisons, and explicit `type(value) is str` checks. Perform only lexical validation with `ntpath`/string operations; do not instantiate resolved filesystem paths.

- [ ] **Step 5: Run parser tests and verify GREEN**

Run the Step 3 command. Expected: all `StrictParserTests` pass and zero-I/O sentinels remain untouched.

- [ ] **Step 6: Save checkpoint `checkpoints/bridge-v1-task2/` with hashes**

### Task 3: Canonical SHA-256 and size boundaries

**Files:**
- Modify: `core/bridge/intent_parser.py`
- Modify: `tests/acceptance/test_llm_bridge.py`

**Interfaces:**
- Consumes: `parse_intent(raw_response: str) -> BridgeResult`.
- Produces: canonical lowercase digest in every successful `ActionIntent`.

- [ ] **Step 1: Write failing digest tests**

Use hand-calculated literal digests for ASCII and multibyte UTF-8 content. Assert omitted hash is inserted; matching lowercase hash is accepted; uppercase, non-hex, wrong length, and mismatched hashes return `INVALID_INTENT`.

- [ ] **Step 2: Write failing boundary tests**

Assert empty content succeeds, exactly 2 MiB of UTF-8 bytes succeeds, one byte over fails, and multibyte text is judged by encoded byte length. Assert target path and reasoning summary length limits at the exact boundary and one code point above.

- [ ] **Step 3: Run integrity tests and verify RED**

Run: `python -m unittest tests.acceptance.test_llm_bridge.HashAndBoundsTests -v`

Expected: failures for missing canonical digest and unenforced boundaries.

- [ ] **Step 4: Implement digest and boundary validation**

Calculate `hashlib.sha256(content.encode('utf-8')).hexdigest()` internally, compare any supplied digest exactly, and apply the spec's byte/code-point limits.

- [ ] **Step 5: Run integrity tests and verify GREEN**

Run the Step 3 command. Expected: all `HashAndBoundsTests` pass.

- [ ] **Step 6: Save checkpoint `checkpoints/bridge-v1-task3/` with hashes**

### Task 4: Ollama and Groq provider adapters

**Files:**
- Create: `core/bridge/ollama_provider.py`
- Create: `core/bridge/groq_provider.py`
- Modify: `core/bridge/__init__.py`
- Modify: `tests/acceptance/test_llm_bridge.py`

**Interfaces:**
- Consumes: `parse_intent`, `LLMBridgeProvider`, `BridgeResult`, `BridgeError`, and `BridgeErrorCode`.
- Produces: `OllamaBridgeProvider(transport: Callable[[str], str])` and `GroqBridgeProvider(transport: Callable[[str], str])`.

- [ ] **Step 1: Write failing shared provider contract tests**

Run identical cases against both providers: valid raw response, invalid raw response, empty/non-string prompt, non-string transport result, timeout, connection error, and generic exception. Assert `PROVIDER_FAILURE` includes provider name and exception type, parser errors remain unchanged, and no ordinary exception escapes.

- [ ] **Step 2: Write failing non-invocation tests**

Use a Supervisor spy with a `submit_transaction` method that fails the test if called. Assert malformed, unsupported, path-invalid, hash-invalid, and provider-failure cases leave its call count at zero. The provider has no Supervisor dependency; the spy is kept only in the test orchestration fixture.

- [ ] **Step 3: Run provider tests and verify RED**

Run: `python -m unittest tests.acceptance.test_llm_bridge.ProviderAdapterTests -v`

Expected: import failure because provider modules do not exist.

- [ ] **Step 4: Implement the two thin adapters**

Validate prompt type/content, call the injected transport exactly once, require a string response, delegate to `parse_intent`, and convert ordinary `Exception` instances into `PROVIDER_FAILURE`. Do not catch `KeyboardInterrupt`, `SystemExit`, or other `BaseException` process-control signals. Do not retry.

- [ ] **Step 5: Run provider tests and full Bridge suite**

Run: `python -m unittest tests.acceptance.test_llm_bridge -v`

Expected: all Bridge acceptance tests pass with no network or filesystem access.

- [ ] **Step 6: Save checkpoint `checkpoints/bridge-v1-task4/` with hashes**

### Task 5: Regression verification and deliverable checkpoint

**Files:**
- Verify: all files created or modified in Tasks 1–4.
- Create only after all gates pass: `GiorgioCodex_v5_llm_bridge_v1_verified.zip`

**Interfaces:**
- Consumes: complete isolated Bridge implementation.
- Produces: regression evidence and a hash-verified project ZIP.

- [ ] **Step 1: Run Bridge acceptance suite**

Run: `python -m unittest tests.acceptance.test_llm_bridge -v`.

- [ ] **Step 2: Run P0 regression suites sequentially**

Run, one process at a time:

- `python -m unittest tests.acceptance.test_win32_file_lock -v`
- `python -m unittest tests.acceptance.test_isolation_kernel -v`
- `python tests/acceptance/action_harness.py`
- `python -m unittest tests.acceptance.test_natural_actions -v`

- [ ] **Step 3: Run the compatible non-GUI suite**

Run the existing explicit non-GUI module list and include the new Bridge acceptance module. Record actual pass/fail/skip counts.

- [ ] **Step 4: Inspect scope and artifacts**

Verify that existing Core execution files are unchanged from the `win32_lock_verified` checkpoint except files explicitly added by this plan; verify no `.pyc`, `__pycache__`, provider credentials, API keys, or test network artifacts enter the deliverable.

- [ ] **Step 5: Create and verify the final ZIP only when every gate is green**

Create `GiorgioCodex_v5_llm_bridge_v1_verified.zip`, verify required entries, calculate SHA-256 directly on final bytes, and report observed results only.

