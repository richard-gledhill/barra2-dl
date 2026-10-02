# How to contribute

## Dependencies

We use [uv](https://github.com/astral-sh/uv) to manage the dependencies.

To install them you would need to run `sync` command:

```bash
uv sync --all-groups
```

To run a command inside the `virtualenv` prefix it with `uv run`, e.g. `uv run pytest`.

## One magic command

Run `make check` and `make test` to run everything we have!

## Tests

We use `pytest` for tests and [`ruff`](https://github.com/astral-sh/ruff) (lint + format) for
code style, plus [`deptry`](https://github.com/fpgmaas/deptry) to catch unused/missing dependencies.

To run all tests:

```bash
pytest
```

To run linting:

```bash
ruff check .
ruff format --check --diff .
```

Directories excluded from `ruff` (`.venv`, `.git`, `build`, etc.) are configured in
`pyproject.toml`'s `[tool.ruff]` section. These steps are mandatory during the CI, and
`make lint` / `make check` run them all together (see [Makefile](Makefile)).

## Type checks

We use `mypy` to run type checks on our code.
To use it:

```bash
mypy src/barra2_dl tests
```

This step is mandatory during the CI.

## Submitting your code

We use [trunk based](https://trunkbaseddevelopment.com/) development.

What the point of this method?

1. We use protected `main` branch,
   so the only way to push your code is via pull request
2. We use short-lived topic branches: to implement a new feature or to fix a bug
   create a new branch named `<type>/<short-description>`, where `<type>` is a
   [Conventional Commits](https://www.conventionalcommits.org/) type (`feat`/`feature`, `fix`,
   `chore`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `revert`),
   e.g. `fix/readme-example` or `chore/update-gitignore`.
   The `Branch naming` workflow checks this on every pull request (Dependabot branches are exempt)
3. Then create a pull request to `main` branch
4. We use `git tag`s and GitHub releases to make releases, so we can track what has changed
   since the latest release. Publishing a release also deploys the documentation site

So, this way we achieve an easy and scalable development process
which frees us from merging hell and long-living branches.

In this method, the latest version of the app is always in the `main` branch.

### Before submitting

Before submitting your code please do the following steps:

1. Run `pytest` to make sure everything was working before
2. Add any changes you want
3. Add tests for the new changes
4. Edit documentation if you have changed something significant
5. Write [Conventional Commits](https://www.conventionalcommits.org/) messages
   (e.g. `fix: ...`, `feat: ...`, `docs: ...`). Do not edit `CHANGELOG.md` by hand:
   it is regenerated from the commit history on every push to `main`
6. Run `pytest` again to make sure it is still working
7. Run `mypy` to ensure that types are correct
8. Run `ruff check` and `ruff format --check` to ensure that style is correct
9. Run `mkdocs build -s` (`make docs-test`) to ensure that docs build cleanly

Or just run `make check` and `make test`, which cover all of the above.

## Other help

You can contribute by spreading a word about this library.
It would also be a huge contribution to write
a short article on how you are using this project.
You can also share your best practices with us.
