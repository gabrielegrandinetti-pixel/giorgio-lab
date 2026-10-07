# Giorgio Semantic Protocol — GSP/0

Status: EXPERIMENTAL. Not VERIFIED and not part of STABLE.

GSP/0 is a deterministic compact transport for routine messages among Giorgio components/agents. It reduces repeated prose; it does not compress away evidence or reasoning.

Principles: meaning before compression; immutable versioned semantics; evidence by reference; no guessing on decode failure; COMPACT has no free text; STANDARD/FORENSIC may carry payload; failures escalate rather than being silently repaired; existing Core/Policy/Executor/Verifier authority is unchanged.

Wire header: magic GSP, version, source, target, kind, level. Variable UTF-8 fields are length-prefixed: task_id, commit SHA, evidence ID, payload.

Evolution rule: agents may propose new opcodes, but an existing opcode meaning cannot be mutated in-place. Semantic changes require a new protocol version. Adoption requires equivalence tests plus measured token/byte/request/error impact.

Fallback: GSP COMPACT -> STANDARD -> FORENSIC -> natural language/evidence. Unknown, malformed or unsupported messages are rejected, never guessed.
