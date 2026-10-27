# Development docs

Everything about *building* this project lives here. This folder is excluded from the MkDocs site
(`exclude_docs` in `mkdocs.yml`), so nothing in it is published. Anything users should read belongs in
the MkDocs part of `docs/`, one level up.

| Path | What goes there |
|---|---|
| [`constraints.md`](constraints.md) | The measured, tool-enforced quality bar. Project-wide and long-lived. Read before writing code; never weaken it to make a change pass. Only the owner changes it. |
| [`conventions.md`](conventions.md) | The judgement-based style guide. Read before writing code. Only the owner changes it. |
| [`backlog.md`](backlog.md) | Deferred work and known bugs, not yet scheduled. |
| [`requirements/`](requirements/README.md) | PRDs, product briefs and user stories. Human-owned and long-lived. |
| [`plan/`](plan/README.md) | The current piece of work: `SPEC.md`, `plan.md` and `todo.md`, plus an `archive/` of finished work. |
| [`adr/`](adr/README.md) | Architecture decision records, `ADR-NNN-title.md`, sequential, never deleted. |
| [`architecture/`](architecture/README.md) | Overview, diagrams, data model. |
| [`testing/`](testing/README.md) | Test strategy and known gaps. |

## From backlog to shipped work

1. **Backlog**: an item in [`backlog.md`](backlog.md) is picked up when it is next in line.
2. **Requirement** (if the item is a feature): a person writes `requirements/<feature>-prd.md` with `Status: Draft`,
   and marks it `Accepted` when it is ready to build.
3. **ADR**: a decision that outlives the work is recorded in `adr/`.
4. **Plan**: write `plan/SPEC.md`, linking its requirement, then `plan.md` and `todo.md`. Build against them.
5. **Archive**: when the work ships, move the spec, plan and todo together into `plan/archive/YYYY-MM-<feature>/`,
   set the requirement's status to `Done`, and remove the item from the backlog.

See [AGENTS.md](../../AGENTS.md) for the paths agents must use.
