"""The notebook GUI of barra2-dl, installed with the gui extra: pip install "barra2-dl[gui]".

Importing this package loads no GUI toolkit. barra2-dl-gui (main) copies the notebook into a folder and starts
JupyterLab on it; the interface code is in barra2_dl.gui.app, which needs ipywidgets and ipyleaflet.
"""

import argparse
import importlib.util
import logging
import os
import sys
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = ['main']

NOTEBOOK = 'barra2_dl_gui.ipynb'
DEFAULT_FOLDER = 'barra2-dl-gui'
TOOLKIT = ('ipywidgets', 'ipyleaflet', 'jupyterlab')


def main(argv: Sequence[str] | None = None) -> int:
    """Copy the GUI notebook into a folder and start JupyterLab on it; this is the barra2-dl-gui command.

    An existing copy is never overwritten, so the analyst's edits survive; --reset replaces it with the shipped one.
    The cache, the output and last_session.json default to the same folder.

    Args:
        argv (Sequence[str] | None): The command line without the program name. Default sys.argv[1:].

    Returns:
        int: 0 on success, 1 if the gui extra is not installed.
    """
    parser = argparse.ArgumentParser(
        prog='barra2-dl-gui', description='Copy the GUI notebook into a folder and start JupyterLab on it.'
    )
    parser.add_argument(
        'folder', nargs='?', default=DEFAULT_FOLDER, help=f'where to put the notebook (default ./{DEFAULT_FOLDER})'
    )
    parser.add_argument('--reset', action='store_true', help='replace the notebook in the folder with the shipped one')
    parser.add_argument(
        '--no-launch', action='store_true', help='copy the notebook and stop, without starting JupyterLab'
    )
    args = parser.parse_args(argv)
    if not args.no_launch:
        missing = [name for name in TOOLKIT if importlib.util.find_spec(name) is None]
        if missing:
            _say(f'The GUI needs {", ".join(missing)}. Install it with:  pip install "barra2-dl[gui]"')
            return 1
    notebook = _copy_notebook(Path(args.folder), reset=args.reset)
    if not args.no_launch:
        _launch(notebook)
    return 0


def _say(text: str) -> None:
    """Write a message to the log and to the console, as the library's modules do."""
    logger.info(text)
    sys.stdout.write(text + '\n')


def _copy_notebook(folder: Path, *, reset: bool) -> Path:
    """Put the shipped notebook in the folder, unless the analyst's copy is there and reset is False."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / NOTEBOOK
    if target.exists() and not reset:
        _say(f'Kept your copy of {target}. Use --reset to replace it with the shipped notebook.')
    else:
        target.write_bytes((resources.files('barra2_dl.gui') / NOTEBOOK).read_bytes())
        _say(f'Wrote {target}.')
    return target


def _launch(notebook: Path) -> None:
    """Start JupyterLab on the notebook, in its folder so the cache and output land beside it."""
    from jupyterlab.labapp import LabApp

    os.chdir(notebook.parent)
    LabApp.launch_instance(argv=[str(notebook.resolve())])
