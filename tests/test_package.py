"""This module contains package-level structure tests."""

import ast
import importlib
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

import barra2_dl

SRC = Path(barra2_dl.__file__).parent
INTERFACES = [*SRC.glob('gui/**/*.py'), *SRC.glob('cli.py')]
# the interface layers, and the toolkits the optional gui extra may bring
INTERFACE_MODULES = ('barra2_dl.gui', 'barra2_dl.cli')
TOOLKITS = ('streamlit', 'nicegui', 'panel', 'dash', 'flet', 'tkinter')
MODULES = ['convert', 'download', 'globals', 'mapping', 'merge', 'project']


def _imports(path: Path) -> list[ast.Import | ast.ImportFrom]:
    """Return every import statement in a source file."""
    return [
        node
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
        if isinstance(node, ast.Import | ast.ImportFrom)
    ]


def _undeclared_imports(path: Path) -> list[str]:
    """Return the names a file imports from a barra2_dl module that the module doesn't list in its __all__.

    Constants from barra2_dl.globals are allowed without being listed, and so is importing a whole module.
    """
    undeclared: list[str] = []
    for node in _imports(path):
        if not isinstance(node, ast.ImportFrom) or not node.module or node.module == 'barra2_dl.globals':
            continue
        if node.module.startswith('barra2_dl.'):
            declared = importlib.import_module(node.module).__all__
            undeclared += [f'{node.module}.{alias.name}' for alias in node.names if alias.name not in declared]
    return undeclared


def _exposed_submodules() -> list[str]:
    """Run in a fresh interpreter: the submodules reachable as attributes right after import barra2_dl."""
    import barra2_dl

    return [name for name in ('convert', 'download', 'mapping', 'merge', 'project') if hasattr(barra2_dl, name)]


def test_package_exposes_submodules() -> None:
    """The submodules are importable straight from the package, with nothing else imported first."""
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
        assert pool.submit(_exposed_submodules).result() == ['convert', 'download', 'mapping', 'merge', 'project']


@pytest.mark.parametrize('module', MODULES)
def test_all_names_resolve(module: str) -> None:
    """Every name declared in a module's __all__ exists, and private helpers are not exported."""
    mod = importlib.import_module(f'barra2_dl.{module}')
    for name in mod.__all__:
        assert hasattr(mod, name)
        assert not name.startswith('_')


@pytest.mark.parametrize('module', MODULES)
def test_all_has_no_repeats(module: str) -> None:
    """__all__ has no repeats, so a name is declared once."""
    mod = importlib.import_module(f'barra2_dl.{module}')
    assert len(set(mod.__all__)) == len(mod.__all__)


def _loaded_interfaces() -> list[str]:
    """Run in a fresh interpreter: the interface and toolkit modules loaded once barra2_dl is imported."""
    import barra2_dl  # noqa: F401 - the import is what is being tested

    return [m for m in sys.modules if m.split('.')[0] in TOOLKITS or m in INTERFACE_MODULES]


def test_importing_the_package_loads_no_interface_or_toolkit() -> None:
    """Import barra2_dl works without the gui extra: in a fresh interpreter it loads no gui, cli or toolkit module."""
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
        assert pool.submit(_loaded_interfaces).result() == []


@pytest.mark.parametrize('path', sorted(SRC.glob('*.py')), ids=lambda path: path.name)
def test_library_modules_do_not_import_an_interface_or_toolkit(path: Path) -> None:
    """No library or engine module imports barra2_dl.gui, barra2_dl.cli or a GUI toolkit."""
    names = []
    for node in _imports(path):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        else:
            names += [node.module or '', *(f'{node.module}.{alias.name}' for alias in node.names)]

    offending = [name for name in names if name.startswith(INTERFACE_MODULES) or name.split('.')[0] in TOOLKITS]

    assert offending == []


@pytest.mark.parametrize('path', INTERFACES, ids=lambda path: str(path.relative_to(SRC)))
def test_interfaces_import_only_declared_names(path: Path) -> None:
    """An interface imports only names a module lists in __all__, plus constants from globals."""
    assert _undeclared_imports(path) == []


def test_undeclared_imports_finds_a_private_name(tmp_path: Path) -> None:
    """The checker itself finds a private name; a declared name and a globals constant pass."""
    sample = tmp_path / 'interface.py'
    sample.write_text(
        'from barra2_dl.download import _download_file, download_serial\n'
        'from barra2_dl.globals import BARRA2_FREQS\n'
        'from barra2_dl.mapping import LatLonPoint\n'
    )

    assert _undeclared_imports(sample) == ['barra2_dl.download._download_file']


def _import_mapping_first() -> list[str]:
    """Run in a fresh interpreter: import mapping before download, which imports mapping, and look a node up."""
    import barra2_dl.mapping as mapping

    return [name for name in ('GridNode', 'nearest_nodes') if hasattr(mapping, name)]


def test_importing_mapping_first_works_despite_download_importing_mapping() -> None:
    """Mapping imports download only inside nearest_nodes, so there is no import cycle whichever is imported first."""
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
        assert pool.submit(_import_mapping_first).result() == ['GridNode', 'nearest_nodes']


def test_node_selection_type_matches_the_constant() -> None:
    """The Literal type and the tuple of node selections list the same values."""
    from typing import get_args

    from barra2_dl.globals import BARRA2_NODE_SELECTIONS, NodeSelection

    assert get_args(NodeSelection.__value__) == BARRA2_NODE_SELECTIONS
