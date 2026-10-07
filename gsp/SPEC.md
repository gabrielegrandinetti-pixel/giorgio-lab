# Giorgio Semantic Protocol (GSP) — experimental v0

Status: EXPERIMENTAL. This protocol does not change Giorgio governance, VERIFIED/STABLE rules, or the Core→Executor→Verifier authority chain.

Goal: reduce repeated inter-agent text without losing evidence or semantic precision.

## Design
Three adaptive levels:
- COMPACT: routine typed records and evidence references.
- STANDARD: adds bounded textual detail for anomalies or new information.
- FORENSIC: full evidence/log detail for failures, ambiguity, security or verification disputes.

GSP compresses transport, not reasoning or evidence. Evidence is stored once and referenced by ID.

## Record
Required fields: version, sender, receiver, task, action, state.
Optional: candidate_sha, evidence_ids, priority, payload.

Agents: GIO, R, D, C, I.
Actions: ACK, NACK, HANDOFF, VERIFY, AUDIT, VERDICT, BLOCK, ESCALATE.
States: READY, PASS_TEST, FAIL_TEST, VERIFIED, REJECTED_CODE, BLOCKED_ENVIRONMENT, INCONCLUSIVE, BLOCKED_TOOL_ACCESS.

## Safety invariants
A message cannot self-promote a Developer result to VERIFIED.
VERIFIED requires evidence references and a candidate SHA.
Unknown codes, missing required fields, version mismatch, or ambiguous decoding MUST fail closed and escalate to a textual level.
A new candidate SHA invalidates applicability of prior candidate-specific verification unless explicitly re-established.
No compressed message authorizes execution by itself. Core/Policy remain authoritative.

## Evolution
The dictionary may evolve only by versioned additions backed by measured frequency/benefit. Existing opcode meaning is immutable within a version. No autonomous semantic mutation. Candidate extensions must pass round-trip, malformed-input, semantic-equivalence, and token/byte/request benchmarks before adoption.

## Wire direction
Human-readable GSP is canonical during experimentation. A binary codec may be added only after measurement shows benefit. Raw 0/1 strings are not a goal.
