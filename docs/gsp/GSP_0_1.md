# Giorgio Semantic Protocol (GSP) — Draft 0.1

Status: EXPERIMENTAL. This document does not modify Giorgio's Constitution, STABLE, verification thresholds, or the current v5.2 candidate.

## Purpose

GSP is a compact, typed, evolvable protocol for communication among Giorgio components and agents. It reduces repeated natural-language context without reducing evidence, safety, or semantic precision.

GSP is inspired by symbolic multi-agent communication research such as CLSR and by semantic agent-context compression ideas such as ACCP. It is Giorgio-specific and must earn adoption through measurements.

## Non-negotiable invariants

1. Compression never changes authority: LLM interprets; Core decides; Executor acts; Verifier proves.
2. Evidence is never replaced by a symbol. GSP may reference immutable evidence by ID.
3. No decoder guessing. Invalid, unknown, ambiguous, or version-incompatible frames fail closed and escalate to a richer representation.
4. No role can self-certify VERIFIED through GSP.
5. STABLE and current candidate rules are unchanged.
6. Protocol evolution cannot silently redefine an existing opcode.
7. Human-facing output remains ordinary language unless explicitly requested otherwise.

## Adaptive representation

GSP uses three semantic levels:

- C0 COMPACT: routine acknowledgements, state transitions, handoffs, known evidence references.
- C1 STRUCTURED: typed payload with explicit fields for anomalies, new facts, or non-routine work.
- C2 FORENSIC: complete evidence/log context required for failures, conflicts, security findings, or irreversible decisions.

Escalate C0 -> C1/C2 when decoding is uncertain, required fields are missing, SHA changes, agents disagree, tests fail, evidence is new, or consequences are high-risk. De-escalate only after the ambiguity or failure is resolved.

## Canonical frame

A logical GSP frame contains:

- version
- sender
- recipient
- task_id
- candidate_sha (when code/candidate relevant)
- intent
- status
- evidence_refs[]
- payload (optional)
- schema_id
- sequence
- checksum/digest when serialized

Illustrative symbolic form:

GSP/0.1 @D>@C T:52 ^A91 I:VERIFY S:READY #E44

This is a human-readable diagnostic representation, not the final binary wire format.

## Core intents

ACK, NACK, HANDOFF, VERIFY, AUDIT, RESULT, BLOCK, QUERY, SYNC, ESCALATE, COMPRESS.

## Core statuses

READY, PASS_TEST, FAIL_TEST, VERIFIED, REJECTED_CODE, BLOCKED_ENVIRONMENT, INCONCLUSIVE, BLOCKED_TOOL_ACCESS, UNKNOWN.

VERIFIED remains subject to Giorgio governance and evidence rules; encoding the status does not grant it.

## Evidence-by-reference

Large logs, test output, provenance, and artifacts are stored once in the evidence store and referenced as immutable IDs such as #E44. A receiver MUST be able to resolve a required evidence reference before relying on it. Missing evidence causes NACK/ESCALATE, never inference.

## Checkpoint and delta

Shared state is checkpointed at task completion, handoff, phase boundary, or context-budget threshold. After a checkpoint, send deltas rather than retransmitting unchanged context. Raw evidence remains in cold storage; compact state contains references.

## Evolution

GSP may evolve dialects/opcodes only through a controlled proposal process:

OBSERVE repeated semantic pattern -> PROPOSE candidate encoding -> SHADOW TEST against canonical meaning -> BENCHMARK -> ACCEPT or REJECT -> VERSION.

No live self-modification of the active dictionary. New encodings are versioned and reversible.

Acceptance requires no statistically meaningful quality regression on the evaluation set and a measurable improvement in at least one target metric without unacceptable regression in the others.

## Metrics

Measure:
- input/output tokens
- number of model calls
- wall-clock latency
- decode/validation failures
- semantic-equivalence accuracy
- task success rate
- evidence-resolution failures
- escalation rate
- rework rate

Do not claim efficiency gains before measurement.

## Semantic equivalence test

For each benchmark task, compare:
A. natural-language baseline
B. current G5P-Lite
C. GSP candidate

The final task outcome, required evidence, authorization decision, and verifier verdict must be equivalent where the input facts are equivalent. Any safety or evidence loss is an automatic rejection regardless of token savings.

## Binary layer

A binary serialization may be added only after the semantic protocol is stable. The binary representation is a transport optimization, not a reasoning language. The LLM should normally consume validated symbolic/structured meaning rather than arbitrary bit strings.

## Compatibility

G5P-Lite is treated as an experimental human-readable profile that can later map onto GSP. GSP must coexist with current TEAM-RUNTIME and must not require waking all five agents. Routing follows minimum-necessary participation.

## Initial rollout

Phase 0: specification and benchmark only, isolated from main.
Phase 1: codec + strict validator + round-trip tests.
Phase 2: shadow mode: produce GSP alongside existing messages but do not control actions.
Phase 3: limited C0 handoffs if equivalence benchmarks pass.
Phase 4: adaptive C0/C1/C2 routing.
Phase 5: optional compact binary transport after profiling proves value.

## Failure policy

Unknown opcode, schema mismatch, missing mandatory field, unresolved evidence, invalid sequence, checksum failure, or semantic mismatch => reject frame and escalate. Never guess.

## Design goal

Minimum necessary representation; maximum verifiable meaning.
