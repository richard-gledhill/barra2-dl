"""This module contains the tests of the shipped GUI notebook, barra2_dl_gui.ipynb, and of the barra2-dl-gui command.

The notebook is executed offline: its cells only build the app and show it, and make no request until a button is
pressed. A core-only environment, without the gui extra, skips the executing tests.
"""

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import nbclient
import nbformat
import pytest

import barra2_dl.gui
from barra2_dl.gui import NOTEBOOK, main

# region Test helpers
GUI = Path(barra2_dl.gui.__file__).parent
SOURCE = GUI / 'barra2_dl_gui.py'
SHIPPED = GUI / NOTEBOOK
needs_toolkit = pytest.mark.skipif(
    any(importlib.util.find_spec(name) is None for name in ('ipywidgets', 'ipyleaflet')),
    reason='needs the gui extra: pip install "barra2-dl[gui]"',
)


def _cells(notebook: Any) -> list[tuple[str, str]]:
    """The type and source of each cell, which is what a notebook is made of apart from its outputs and ids."""
    return [(cell['cell_type'], cell['source']) for cell in notebook['cells']]


# endregion


# region The shipped notebook
def test_notebook_matches_its_jupytext_source() -> None:
    """The .ipynb is what jupytext makes of the .py, so editing one without the other fails here."""
    jupytext = pytest.importorskip('jupytext')

    assert _cells(nbformat.read(SHIPPED, as_version=4)) == _cells(jupytext.read(SOURCE))


def test_notebook_has_about_five_code_cells() -> None:
    """The cells only import, build and show: the interface is in barra2_dl.gui.app, where it is tested."""
    code = [cell for cell in nbformat.read(SHIPPED, as_version=4).cells if cell['cell_type'] == 'code']

    assert 2 <= len(code) <= 6
    assert all(len(cell['source'].splitlines()) <= 5 for cell in code)


@needs_toolkit
def test_notebook_executes_offline_without_an_error(tmp_path: Path) -> None:
    """Every cell runs in a kernel, in a folder of its own, and the last one shows the form and the map."""
    notebook = nbformat.read(SHIPPED, as_version=4)

    client = nbclient.NotebookClient(notebook, timeout=120, resources={'metadata': {'path': str(tmp_path)}})
    client.execute()

    last = notebook.cells[-1]
    assert any('application/vnd.jupyter.widget-view+json' in output.get('data', {}) for output in last.outputs)
    assert not any(
        output.get('output_type') == 'error' for cell in notebook.cells for output in cell.get('outputs', [])
    )


# endregion


# region main
def test_main_no_launch_copies_the_notebook(tmp_path: Path) -> None:
    """The notebook lands in the folder named, which is made if it is not there."""
    folder = tmp_path / 'my' / 'gui'

    assert main(['--no-launch', str(folder)]) == 0

    assert (folder / NOTEBOOK).read_bytes() == SHIPPED.read_bytes()


def test_main_does_not_overwrite_an_edited_copy_unless_reset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The analyst's edits survive a second start; --reset puts the shipped notebook back."""
    main(['--no-launch', str(tmp_path)])
    (tmp_path / NOTEBOOK).write_text('my edits', encoding='utf-8')

    assert main(['--no-launch', str(tmp_path)]) == 0
    assert (tmp_path / NOTEBOOK).read_text(encoding='utf-8') == 'my edits'
    assert 'Kept your copy' in capsys.readouterr().out

    assert main(['--no-launch', '--reset', str(tmp_path)]) == 0
    assert (tmp_path / NOTEBOOK).read_bytes() == SHIPPED.read_bytes()


def test_main_defaults_to_a_folder_in_the_current_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no folder, the notebook goes to ./barra2-dl-gui."""
    monkeypatch.chdir(tmp_path)

    main(['--no-launch'])

    assert (tmp_path / 'barra2-dl-gui' / NOTEBOOK).exists()


def test_main_launches_jupyterlab_on_the_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After copying, JupyterLab is started on the notebook; here the start is replaced by a recorder."""
    started: list[Path] = []
    monkeypatch.setattr(barra2_dl.gui, '_launch', started.append)
    monkeypatch.setattr(importlib.util, 'find_spec', lambda _name: object())

    assert main([str(tmp_path)]) == 0

    assert started == [tmp_path / NOTEBOOK]


def test_launch_passes_an_absolute_path_that_survives_the_chdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative folder is made absolute before JupyterLab is started in it, so the path is not applied twice."""
    seen: list[list[str]] = []
    labapp: Any = types.ModuleType('jupyterlab.labapp')
    labapp.LabApp = types.SimpleNamespace(launch_instance=lambda argv: seen.append(argv))
    monkeypatch.setitem(sys.modules, 'jupyterlab', types.ModuleType('jupyterlab'))
    monkeypatch.setitem(sys.modules, 'jupyterlab.labapp', labapp)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(importlib.util, 'find_spec', lambda _name: object())

    main(['gui'])

    assert Path(seen[0][0]).is_absolute()
    assert Path(seen[0][0]).exists()


def test_main_without_the_extra_says_how_to_install_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing toolkit gives the install line and exit code 1, copies nothing, and shows no traceback."""
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: None if name == 'ipyleaflet' else object())

    assert main([str(tmp_path / 'gui')]) == 1

    assert 'pip install "barra2-dl[gui]"' in capsys.readouterr().out
    assert not (tmp_path / 'gui').exists()


# endregion
