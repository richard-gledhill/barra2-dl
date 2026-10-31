# Architecture decision records

One file per decision, named `ADR-NNN-title.md`. Numbers are sequential: continue the existing sequence. ADRs are
never deleted; a reversed decision gets a new ADR that supersedes the old one.

Each ADR records the context, the decision, the alternatives considered and why they lost, and the consequences.

| ADR | Decision |
|---|---|
| [ADR-001](ADR-001-ruff-and-mypy-only.md) | Style is enforced by ruff and mypy alone |
| [ADR-002](ADR-002-per-variable-month-idempotent-downloads.md) | One remote file per variable per month, downloads are idempotent |
| [ADR-003](ADR-003-cached-files-must-match-the-request.md) | Cached files must match the request, checked before any request |
| [ADR-004](ADR-004-library-first-layering.md) | A top-level library with interfaces beside it; one engine path for a form, a file and a CLI |
