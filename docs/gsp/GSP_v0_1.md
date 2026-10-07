# Giorgio Semantic Protocol (GSP) v0.1 — Experimental

Status: EXPERIMENTAL. This protocol does not modify Giorgio Constitution, STABLE, Core/Policy/Executor/Verifier authority, or verification thresholds.

## Goal
Reduce inter-agent tokens, duplicate context, and unnecessary calls without reducing evidence quality or independent roles.

## Principle
Compress repetition, never evidence or uncertainty.

## Layers
- COMPACT: routine handoff/status. Fixed typed fields, evidence by immutable reference.
- STANDARD: new technical information, disagreement, or missing fields.
- FORENSIC: failures, security/bypass findings, irreversible decisions, or verification disputes.
Automatic escalation: COMPACT -> STANDARD -> FORENSIC. De-escalate only after ambiguity is resolved.

## Canonical record
Every record has:
version, message_id, from, to, task, candidate_sha, opcode, status, evidence_refs, flags, payload_hash, timestamp.

Payload text is optional. If semantics cannot be represented losslessly by the schema, use STANDARD/FORENSIC instead of inventing an opcode.

## Initial role IDs
GIO=0, RESP=1, DEV=2, CTRL=3, INSP=4.

## Initial opcodes
ACK=1, NACK=2, HANDOFF=3, VERIFY_REQUEST=4, AUDIT_REQUEST=5, PASS_TEST=6, FAIL_TEST=7, BLOCKED=8, VERDICT=9, EVIDENCE=10, ESCALATE=11.

VERIFIED is not an agent convenience opcode. A final VERIFIED state remains subject to existing Giorgio governance and evidence rules.

## Safety invariants
1. Unknown version/opcode/required field => reject; never guess.
2. candidate_sha mismatch => reject and escalate.
3. Evidence is stored once and referenced by ID/hash; references never substitute for missing evidence.
4. Negative evidence from the competent independent role cannot be compressed away or overwritten by majority.
5. No protocol message authorizes execution. Core/Policy remain the authority; Executor acts only on authorized actions; Verifier proves results.
6. Binary encoding is transport only. Canonical semantics are the typed record.
7. Schema/opcode evolution is versioned and backward-compatible or explicitly migrated.
8. Learned abbreviations are proposals until deterministic tests prove encode/decode equivalence.

## Evolution
A repeated semantic pattern may become a candidate opcode only when measurement shows meaningful savings. Promotion requires:
frequency threshold -> proposed mapping -> round-trip tests -> ambiguity tests -> measured token/request improvement -> independent review.
Any mapping that increases semantic error is deprecated.

## Measurement
Compare Natural Language vs G5P vs GSP on identical tasks:
input/output tokens, request count, bytes, latency, clarification count, semantic mismatch, task result, verification result.
Optimization target: minimum communication cost subject to zero accepted semantic mismatch and unchanged verification quality.

## Transport
v0.1 uses readable canonical records first. A later binary codec may encode enums/flags/IDs as bytes or varints. Raw 0/1 strings are explicitly not a goal.

## Fallback
BINARY -> CANONICAL GSP -> NATURAL LANGUAGE.
Failure to decode is a protocol event, not permission to infer intent.
