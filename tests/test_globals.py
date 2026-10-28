"""This module contains data-integrity tests for barra2.globals."""

import re
from datetime import timedelta

import pytest

from barra2_dl.globals import (
    BARRA2_DOMAINS,
    BARRA2_FREQS,
    BARRA2_INDEX,
    BARRA2_URL,
    BARRA2_URL_AUS11_1HR,
    BARRA2_URL_AUST04_1HR,
    BARRA2_VAR_ALIASES,
    BARRA2_VAR_WIND_50,
    BARRA2_VAR_WIND_DEFAULT,
    BARRA2_WIND_VARS,
)


# region BARRA2_INDEX
def test_index_columns() -> None:
    """The join key starts with time and has no duplicates."""
    assert BARRA2_INDEX[0] == 'time'
    assert len(BARRA2_INDEX) == len(set(BARRA2_INDEX))


# endregion


# region BARRA2_WIND_VARS
@pytest.mark.parametrize('entry', BARRA2_WIND_VARS, ids=[entry[0] for entry in BARRA2_WIND_VARS])
def test_wind_vars_pairs_are_consistent(entry: tuple[str, str, int]) -> None:
    """Each (ua, va, height) tuple names matching u/v variables and their height in metres."""
    ua, va, height = entry
    assert ua.startswith('ua')
    assert va == ua.replace('u', 'v', 1)
    assert isinstance(height, int)
    if ua == 'uas':  # uas/vas are the 10 m winds and carry no height in their name
        assert height == 10
    else:
        assert ua == f'ua{height}m'


def test_wind_vars_are_unique() -> None:
    """No wind variable or height is listed twice."""
    names = [name for entry in BARRA2_WIND_VARS for name in entry[:2]]
    heights = [height for *_, height in BARRA2_WIND_VARS]
    assert len(names) == len(set(names))
    assert len(heights) == len(set(heights))


def test_wind_vars_are_server_names() -> None:
    """The table holds server names only; aliases are never listed in it."""
    names = {name for entry in BARRA2_WIND_VARS for name in entry[:2]}
    assert names.isdisjoint(BARRA2_VAR_ALIASES)


# endregion


# region BARRA2_VAR_ALIASES
@pytest.mark.parametrize(('alias', 'server'), BARRA2_VAR_ALIASES.items())
def test_aliases_name_the_height_of_their_server_variable(alias: str, server: str) -> None:
    """Each alias points at a wind table variable and names that variable's height."""
    heights = {name: height for ua, va, height in BARRA2_WIND_VARS for name in (ua, va)}
    assert server in heights
    assert alias == f'{server[:2]}{heights[server]}m'


# endregion


# region BARRA2_DOMAINS and BARRA2_FREQS
def test_freqs_cover_every_domain() -> None:
    """Every domain has frequencies, and only known domains are listed."""
    assert set(BARRA2_FREQS) == set(BARRA2_DOMAINS)


@pytest.mark.parametrize('domain', BARRA2_FREQS)
def test_freqs_include_hourly_default(domain: str) -> None:
    """1hr, the default frequency, is available on every domain."""
    assert BARRA2_FREQS[domain]['1hr'] == timedelta(hours=1)


def test_freqs_aust04_20min() -> None:
    """AUST-04 publishes 20-minute data."""
    assert BARRA2_FREQS['AUST-04']['20min'] == timedelta(minutes=20)


# endregion


# region BARRA2_VAR_WIND_DEFAULT and BARRA2_VAR_WIND_50
@pytest.mark.parametrize('variables', [BARRA2_VAR_WIND_DEFAULT, BARRA2_VAR_WIND_50])
def test_default_variable_lists_are_known(variables: list[str]) -> None:
    """Wind components in the default lists are covered by BARRA2_WIND_VARS, and come in u/v pairs."""
    pairs = {entry[:2] for entry in BARRA2_WIND_VARS}
    components = [v for v in variables if v.startswith(('ua', 'va', 'uas', 'vas'))]
    assert components
    for var in components:
        assert any(var in pair for pair in pairs)
    for ua, va, *_ in BARRA2_WIND_VARS:
        assert (ua in variables) == (va in variables)


# endregion


# region BARRA2_URL
TEMPLATE_FIELDS = {
    'domain': 'AUS-11',
    'model': 'BARRA-R2',
    'freq': '1hr',
    'var': 'ua50m',
    'year': 2023,
    'month': 1,
    'latitude': -23.55,
    'longitude': 133.39,
    'time_start_str': '2023-01-01T00:00:00Z',
    'time_end_str': '2023-01-31T23:00:00Z',
    'fileout_type': 'csv_file',
}

DOMAIN_FREQS = [(domain, freq) for domain, freqs in BARRA2_FREQS.items() for freq in freqs]


@pytest.mark.parametrize(('domain', 'freq'), DOMAIN_FREQS)
def test_url_template_formats_fully(domain: str, freq: str) -> None:
    """The template fills with the fields download.py supplies and leaves no placeholders."""
    fields = TEMPLATE_FIELDS | {'domain': domain, 'model': BARRA2_DOMAINS[domain], 'freq': freq}
    formatted = BARRA2_URL.format(**fields)
    assert not re.search(r'[{}]', formatted)
    assert formatted.startswith('https://thredds.nci.org.au/')
    assert f'/reanalysis/{domain}/' in formatted
    assert f'/{freq}/ua50m/' in formatted
    assert f'_{freq}_202301-202301.nc' in formatted
    assert formatted.endswith('accept=csv_file')


def test_url_template_uses_only_supplied_fields() -> None:
    """Every placeholder in the templates is one download.py provides."""
    for url in (BARRA2_URL, BARRA2_URL_AUS11_1HR, BARRA2_URL_AUST04_1HR):
        assert set(re.findall(r'{(\w+)', url)) <= set(TEMPLATE_FIELDS)


@pytest.mark.parametrize(
    ('url', 'domain'),
    [(BARRA2_URL_AUS11_1HR, 'AUS-11'), (BARRA2_URL_AUST04_1HR, 'AUST-04')],
)
def test_deprecated_url_templates_match_generic_template(url: str, domain: str) -> None:
    """The deprecated pre-filled templates are BARRA2_URL filled for their domain at 1hr."""
    fields = TEMPLATE_FIELDS | {'domain': domain, 'model': BARRA2_DOMAINS[domain]}
    assert url.format(**fields) == BARRA2_URL.format(**fields)


# endregion
