"""This module contains package-level structure tests."""

import importlib

import pytest

import barra2_dl


@pytest.mark.parametrize('module', ['convert', 'download', 'mapping', 'merge'])
def test_package_exposes_submodules(module: str) -> None:
    """The submodules are importable straight from the package."""
    assert hasattr(barra2_dl, module)


@pytest.mark.parametrize('module', ['convert', 'download', 'merge'])
def test_all_names_resolve(module: str) -> None:
    """Every name declared in a module's __all__ exists, and private helpers are not exported."""
    mod = importlib.import_module(f'barra2_dl.{module}')
    for name in mod.__all__:
        assert hasattr(mod, name)
        assert not name.startswith('_')
