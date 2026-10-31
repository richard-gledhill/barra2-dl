# GUI toolkit spikes (RFC-005, slice 3)

Throwaway code. **Never merged to `main`.** Spec: `docs/development/plan/SPEC.md`, "Slice 3 addendum".

Each spike builds the same thin slice: a form that builds `Settings`/`Site`, a map with the nodes from
`mapping.nearest_nodes`, polygon drawing, a background `project.run_site` with progress and cancel, and the run summary.

## Run a spike (about 10 minutes each)

One scratch environment per spike, outside the repo, so `pyproject.toml` and `uv.lock` stay untouched:

```bash
uv venv --python 3.12 <scratch>/streamlit
uv pip install --python <scratch>/streamlit/Scripts/python.exe -e . -e spikes/common -r spikes/streamlit/requirements.txt
<scratch>/streamlit/Scripts/python.exe spikes/streamlit/app.py     # opens the browser
```

NiceGUI is the same with `nicegui` (`python spikes/nicegui/app.py`, port 8602).

- The fake NCSS server (`spikes/common/fake_ncss.py`) serves the `tests/data` fixtures, so no network is needed except
  map tiles. It serves AUS-11 only and only the fixture point (-23.55, 133.40); the form starts there.
- `SPIKE_DELAY=6` makes each file take 6 s (so Cancel is easy to try); `SPIKE_FAIL=va50m` makes that variable return
  404 (a failed or partial run); `SPIKE_LIVE=1` turns the fake off for a real month from the NCI server.
- Outputs and the cache go in `spikes/_scratch/` (git-ignored). Delete `spikes/_scratch/cache` to run again from empty.

## Evidence

`spikes/_evidence/`: pin dry runs (`compile-<toolkit>-<python>.txt`), `uv pip freeze` per spike, install sizes, licences
and release dates (`facts.txt`), screenshots (`screens/`) and the findings notes. The checklist the owner completes is
`spikes/common/checklist.md`.
