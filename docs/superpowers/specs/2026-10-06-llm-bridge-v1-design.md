# LLM Bridge v1 Design

## Purpose

Introduce a fail-closed translation boundary between Ollama/Groq output and Giorgio's existing Supervisor. Version 1 accepts only `MODIFY_FILE`, performs no filesystem or system I/O in the parser, never invokes the Supervisor itself, and never allows provider exceptions to cross the Bridge result boundary.

The implementation targets the verified `GiorgioCodex_v5_win32_lock_verified` baseline. It must not alter the existing deterministic action parser, isolation kernel, executor, verifier, or Supervisor behavior.

## Scope

Version 1 includes:

- immutable bridge contracts;
- strict JSON parsing and validation;
- one abstract provider interface;
- Ollama and Groq provider adapters with injected transport callables;
- deterministic acceptance tests with fake transports;
- `MODIFY_FILE` as the only supported action.

Version 1 excludes:

- connecting the Bridge to `TransactionSupervisor`;
- real Ollama or Groq network calls in acceptance tests;
- API-key storage or settings UI;
- `CREATE`, `MKDIR`, `MOVE`, `COPY`, `DELETE`, `EXECUTE`, or other capabilities;
- filesystem existence checks, path resolution, file reading, or file writing;
- direct Journal writes.

## Package Layout

```text
core/bridge/
├── __init__.py
├── base_provider.py
├── intent_parser.py
├── ollama_provider.py
└── groq_provider.py

tests/acceptance/test_llm_bridge.py
```

## Immutable Contracts

`base_provider.py` defines:

```python
class BridgeErrorCode(str, Enum):
    INVALID_INTENT = "INVALID_INTENT"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"

@dataclass(frozen=True)
class ActionIntent:
    action_type: Literal["MODIFY_FILE"]
    target_path: str
    content: str
    expected_sha256: str
    reasoning_summary: str

@dataclass(frozen=True)
class BridgeError:
    code: BridgeErrorCode
    message: str
    provider: str | None = None
    exception_type: str | None = None

@dataclass(frozen=True)
class BridgeResult:
    intent: ActionIntent | None = None
    error: BridgeError | None = None
```

`BridgeResult.__post_init__` enforces exactly one of `intent` or `error`. No mutable dictionary is exposed as the validated intent.

`LLMBridgeProvider` is an abstract base with this public operation:

```python
def request_intent(self, prompt: str) -> BridgeResult
```

Provider adapters may perform network I/O through their injected transport, but the parser and immutable contract layer perform none.

## Raw JSON Contract

The provider response must be a Python `str` containing exactly one JSON object and no surrounding non-whitespace content:

```json
{
  "action_type": "MODIFY_FILE",
  "parameters": {
    "target_path": "progetto/main.py",
    "content": "print('Hello World')",
    "expected_sha256": "optional-lowercase-sha256"
  },
  "reasoning_summary": "Sostituzione entrypoint principale."
}
```

Only these keys are allowed. Unknown top-level or parameter keys are invalid. Required fields are `action_type`, `parameters`, `target_path`, `content`, and `reasoning_summary`. `expected_sha256` is optional in raw JSON but always populated in `ActionIntent`.

Markdown fences, prose before or after the object, multiple JSON values, non-object roots, duplicate JSON keys, malformed JSON, non-string values, and non-finite or decoder-specific extensions are rejected as `INVALID_INTENT`.

## Action and Field Validation

- Any `action_type` other than the exact uppercase string `MODIFY_FILE` returns `UNSUPPORTED_ACTION`.
- `reasoning_summary` must be non-empty after trimming and is bounded to 1,000 Unicode code points.
- `content` is textual, may be empty, and is bounded to 2 MiB after UTF-8 encoding to match the executor limit.
- `target_path` is textual, non-empty, and bounded to 1,024 Unicode code points.
- NUL bytes and ASCII control characters are forbidden in `target_path`.
- Backslashes are normalized to `/` only after validation.
- Absolute POSIX paths, drive-qualified or drive-relative Windows paths, UNC/device paths, leading slash/backslash, empty components, `.`, `..`, trailing dot/space components, alternate data stream colons, and Windows-illegal characters `< > : " | ? *` are rejected.
- Reserved Windows device basenames (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`) are rejected case-insensitively even when followed by an extension.
- The parser does not call `Path.resolve`, `exists`, `stat`, `open`, or any filesystem API. Project-root containment remains the responsibility of the existing Supervisor/security layer when integration is added later.

## Hash Integrity

The canonical expected digest is always calculated by the Bridge as:

```python
hashlib.sha256(content.encode("utf-8")).hexdigest()
```

If raw JSON omits `expected_sha256`, the canonical digest is inserted into `ActionIntent`. If supplied, it must be exactly 64 lowercase hexadecimal characters and equal the canonical digest. Any malformed, uppercase, or mismatched value returns `INVALID_INTENT`.

The LLM-provided digest is therefore an optional assertion, never a source of truth.

## Provider Isolation

`OllamaBridgeProvider` and `GroqBridgeProvider` each receive a transport callable through their constructor. The callable accepts the prompt and returns the raw response string. This keeps protocol/network details behind the provider boundary and permits deterministic tests without sockets.

The adapter flow is:

1. validate that the prompt is a non-empty string;
2. call the injected transport;
3. require a string response;
4. pass it to the strict parser;
5. return the parser's `BridgeResult` unchanged.

Any transport exception, timeout, or non-string response returns `PROVIDER_FAILURE` with provider name and exception type. It does not raise across `request_intent`, invoke the Supervisor, or write the Journal. A future orchestration layer may persist the returned structured error.

Provider adapters must not retry in v1. Retry policy belongs to orchestration and must not make an ambiguous LLM operation happen more than once invisibly.

## Fail-Closed Data Flow

```text
prompt
  -> provider adapter / injected transport
  -> raw string
  -> strict JSON decoder with duplicate-key rejection
  -> schema, action, path, size, and hash validation
  -> BridgeResult(intent=ActionIntent(...))

any provider fault
  -> BridgeResult(error=PROVIDER_FAILURE)

any syntax/schema/path/hash fault
  -> BridgeResult(error=INVALID_INTENT)

any known but unauthorized action
  -> BridgeResult(error=UNSUPPORTED_ACTION)
```

No error path calls the Supervisor. The acceptance suite proves this by using a supervisor spy that must remain untouched.

## Acceptance Tests

`tests/acceptance/test_llm_bridge.py` covers at least:

1. valid `MODIFY_FILE` response produces a frozen `ActionIntent`;
2. omitted digest is calculated from UTF-8 bytes;
3. matching supplied digest is accepted;
4. mismatched, malformed, or uppercase digest is rejected;
5. Markdown fences, prefix/suffix prose, malformed JSON, duplicate keys, extra keys, and wrong field types are rejected;
6. unsupported actions return `UNSUPPORTED_ACTION`;
7. traversal, absolute, drive, UNC/device, ADS, reserved-name, illegal-character, empty-component, and trailing-dot/space paths are rejected;
8. empty content is accepted while content over 2 MiB is rejected;
9. provider timeout/disconnection/exception becomes `PROVIDER_FAILURE` without escaping;
10. invalid responses and provider failures never touch the Supervisor spy;
11. both Ollama and Groq adapters obey the same result contract;
12. parser tests patch filesystem entry points to fail if any I/O is attempted.

The existing Win32 lock, Isolation Kernel, Action Harness, Natural Actions, and non-GUI suites must remain green after implementation.

## Completion Criteria

Bridge v1 is complete only when:

- all Bridge acceptance cases pass without real network or filesystem I/O;
- the immutable result invariants are enforced;
- only `MODIFY_FILE` can produce an `ActionIntent`;
- canonical SHA-256 behavior is verified with literal expected digests;
- no invalid/provider-failure path invokes the Supervisor;
- every existing required regression suite passes;
- no provider is connected to production execution yet.
