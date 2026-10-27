# Architecture

The system overview, diagrams and data model.

The pipeline is described in [AGENTS.md](../../../AGENTS.md#architecture): `globals` (static configuration) →
`download` (URLs and parallel fetch) → `merge` (outer join on `BARRA2_INDEX`) → `convert` (wind speed and
direction from `ua`/`va`), with `mapping` holding geo helpers. Decisions behind it are in [`../adr/`](../adr/README.md).

User-facing explanations belong in the published MkDocs docs, not here.
