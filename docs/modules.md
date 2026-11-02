# Modules

::: barra2_dl
    options:
      members: false

::: barra2_dl.convert

::: barra2_dl.download

::: barra2_dl.globals

::: barra2_dl.mapping

::: barra2_dl.merge

::: barra2_dl.project

## The notebook GUI

`barra2_dl.gui` holds the `barra2-dl-gui` command. Install it with `pip install "barra2-dl[gui]"`, then run
`barra2-dl-gui [folder]`: it copies the notebook `barra2_dl_gui.ipynb` into the folder (default `./barra2-dl-gui`),
keeping any copy that is already there, and starts JupyterLab on it. The interface code is in `barra2_dl.gui.app`, which
needs the extra and is not rendered here.

::: barra2_dl.gui
