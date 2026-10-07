# Architecture

STUB: mermaid diagrams and subsystem notes land in P10 (SPEC §12).

Until then, see [SPEC.md](./SPEC.md) §§6–9 for the intended design:

- Event store as source of truth; run state by folding events
- State machine: INTAKE → UNDERSTAND → PLAN → EXECUTE ↔ AWAIT_APPROVAL → VERIFY → REPORT → COMPLETE
- Independent verifier (agent never grades itself)
- Policy engine for irreversible actions and approvals
