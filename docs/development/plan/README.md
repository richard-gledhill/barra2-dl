# Plan

The current piece of work: what is being built, how, and what is left. One piece of work at a time.

| File | What it is |
|---|---|
| `SPEC.md` | The technical spec for the current piece of work. Links to its source in [`../requirements/`](../requirements/README.md) and references `conventions.md`, `constraints.md` and `testing/` instead of restating them. |
| `plan.md` | The implementation plan for `SPEC.md`. Created by agents. |
| `todo.md` | The task list for the plan. Created by agents. |
| `archive/` | Finished work, one folder each. |
| `parked/` | Unfinished work set aside for something that must go first, one folder each, opening with a note on why and what to change before resuming. Resume it by moving its files back here. |

## Lifecycle

1. Write `SPEC.md`, then `plan.md` and `todo.md`. If this folder already holds an unfinished plan for different
   work, stop and ask before replacing it.
2. Build against them. Decisions that outlive the work become ADRs in [`../adr/`](../adr/README.md).
3. When the work ships, move `SPEC.md`, `plan.md` and `todo.md` together into `archive/YYYY-MM-<feature>/`, set the
   requirement's status to `Done`, and remove the item from [`../backlog.md`](../backlog.md).
4. Start the next piece of work with a fresh `SPEC.md`.
