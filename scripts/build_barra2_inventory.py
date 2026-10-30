"""Build the BARRA2 variable inventory from the NCI THREDDS server.

Lists every variable that barra2-dl can download for each domain and frequency in BARRA2_FREQS, plus the fixed
(fx) fields, and records each variable's units, cell methods and long name from its OPeNDAP attributes. The result is
written to src/barra2_dl/data/barra2_variables.csv, which barra2_dl.globals loads as BARRA2_VARS and BARRA2_VAR_INFO.

Run it from the repository root when the server's variable list changes (the live inventory test will say so):

    uv run python scripts/build_barra2_inventory.py
"""

import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from barra2_dl.globals import BARRA2_DOMAINS, BARRA2_FREQS

THREDDS = 'https://thredds.nci.org.au/thredds'
PATH = 'ob53/output/reanalysis/{domain}/BOM/ERA5/historical/hres/{model}/v1/{freq}'
OUT = Path(__file__).resolve().parents[1] / 'src' / 'barra2_dl' / 'data' / 'barra2_variables.csv'
SAMPLE_MONTH = '202001-202001'  # any month present for every variable; only the attributes are read
WORKERS = 4  # polite load on the shared NCI server


def list_variables(domain: str, model: str, freq: str) -> list[str]:
    """Return the variable folders in one domain/frequency catalogue."""
    url = f'{THREDDS}/catalog/{PATH.format(domain=domain, model=model, freq=freq)}/catalog.xml'
    titles = re.findall(r'xlink:title="([^"]+)"', requests.get(url, timeout=60).text)
    # the catalogue also lists licence/readme entries, whose titles contain spaces or capitals
    return sorted(t for t in titles if re.fullmatch(r'[A-Za-z0-9]+', t) and t not in {'Licence', 'Readme'})


def variable_info(domain: str, model: str, freq: str, var: str) -> dict[str, str]:
    """Read one variable's units, cell methods and long name from its OPeNDAP attributes."""
    stem = f'{var}_{domain}_ERA5_historical_hres_BOM_{model}_v1'
    name = f'{stem}.nc' if freq == 'fx' else f'{stem}_{freq}_{SAMPLE_MONTH}.nc'
    url = f'{THREDDS}/dodsC/{PATH.format(domain=domain, model=model, freq=freq)}/{var}/latest/{name}.das'
    das = requests.get(url, timeout=60).text
    block = re.search(rf'\b{re.escape(var)} \{{(.*?)\n    \}}', das, re.S)
    attrs = dict(re.findall(r'String (\w+) "([^"]*)"', block.group(1))) if block else {}
    return {
        'domain': domain,
        'freq': freq,
        'var': var,
        'units': attrs.get('units', ''),
        'cell_methods': attrs.get('cell_methods', ''),
        'long_name': attrs.get('long_name', ''),
    }


def main() -> int:
    """Write the inventory CSV and report any variable whose attributes could not be read."""
    jobs = []
    for domain, model in BARRA2_DOMAINS.items():
        for freq in [*BARRA2_FREQS[domain], 'fx']:
            names = list_variables(domain, model, freq)
            print(f'{domain} {freq}: {len(names)} variables')
            jobs += [(domain, model, freq, var) for var in names]

    with ThreadPoolExecutor(WORKERS) as pool:
        rows = list(pool.map(lambda job: variable_info(*job), jobs))

    missing = [f'{r["domain"]} {r["freq"]} {r["var"]}' for r in rows if not r['units']]
    with OUT.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['domain', 'freq', 'var', 'units', 'cell_methods', 'long_name'])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r['domain'], r['freq'], r['var'])))
    print(f'Wrote {len(rows)} rows to {OUT}')
    if missing:
        print('No units found for:', ', '.join(missing))
    return 0


if __name__ == '__main__':
    sys.exit(main())
