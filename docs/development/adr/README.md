# Architecture decision records

One file per decision, named `ADR-NNN-title.md`. Numbers are sequential: continue the existing sequence. ADRs are
never deleted; a reversed decision gets a new ADR that supersedes the old one.

Each ADR records the context, the decision, the alternatives considered and why they lost, and the consequences.

| ADR | Decision |
|---|---|
| [ADR-001](ADR-001-ruff-and-mypy-only.md) | Style is enforced by ruff and mypy alone |
| [ADR-002](ADR-002-per-variable-month-idempotent-downloads.md) | One remote file per variable per month, downloads are idempotent |
