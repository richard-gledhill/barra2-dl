# Contributing to barra2-dl-wr

Thank you for your interest in contributing! This project is a fork of [akarich73/barra2-dl](https://github.com/akarich73/barra2-dl) with a Windows GUI and additional features.

## Dependencies

We use [poetry](https://github.com/python-poetry/poetry) to manage dependencies.

```bash
poetry install
```

To activate the virtual environment:

```bash
poetry shell
```

## Development

Run all tests and linting with one command:

```bash
make test
```

### Running tests

```bash
pytest
```

### Linting

```bash
ruff check .
```

### Type checks

```bash
mypy barra2_dl tests/**/*.py
```

## Submitting changes

1. Create a new branch: `issue-$TASKNUMBER` or a descriptive branch name
2. Make your changes and add tests for new functionality
3. Run `pytest`, `mypy`, and `ruff` to verify everything passes
4. Update `CHANGELOG.md` with a summary of your changes
5. Open a pull request

## License

This project is licensed under CC-BY-4.0. Any contributions will be released under the same license. See [LICENSE](LICENSE) for details.
