# Casa di Giorgio v1.5

Minimal runtime-verification sandbox for @C and @I.

Security invariants:
- external immutable target SHA
- clean worktree before execution
- source mounted read-only
- network disabled
- all Linux capabilities dropped
- PID/memory/CPU/time limits
- suite IDs map to fixed argv; no arbitrary shell command
- trusted wrapper lives outside the target tree
- runner emits evidence only; it never emits VERIFIED
- local evidence is tamper-evident, not immutable

V1 implementation intentionally starts with preflight + trusted suite protocol. Docker spawning is the next small batch after these contracts are tested.
