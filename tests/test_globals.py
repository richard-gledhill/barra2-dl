"""This module contains data-integrity tests for barra2.globals."""

import re

import pytest

from barra2_dl.globals import (
    BARRA2_INDEX,
    BARRA2_URL_AUS11_1HR,
    BARRA2_URL_AUST04_1HR,
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
UNIT = '[unit="m s-1"]'


def _wind_var_params() -> list:
    return [
        pytest.param(
            entry,
            id=entry[0],
            marks=[pytest.mark.xfail(strict=True, reason="ua300m/va300m unit is '30m...' instead of '300m...'")]
            if entry[0] == 'ua300m'
            else [],
        )
        for entry in BARRA2_WIND_VARS
    ]


@pytest.mark.parametrize('entry', _wind_var_params())
def test_wind_vars_pairs_are_consistent(entry: tuple[str, str, str]) -> None:
    """Each (ua, va, height) tuple names matching u/v variables and the height used for the output columns."""
    ua, va, height = entry
    assert ua.startswith('ua') or ua == 'uas'
    assert va == ua.replace('u', 'v', 1)
    assert height.endswith(UNIT)
    if ua != 'uas':  # uas/vas are the 10 m surface winds and carry no height in their name
        assert height == ua[2:] + UNIT


def test_wind_vars_are_unique() -> None:
    """No wind variable is listed twice."""
    names = [name for entry in BARRA2_WIND_VARS for name in entry[:2]]
    assert len(names) == len(set(names))


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


# region BARRA2_URL_AUS11_1HR and BARRA2_URL_AUST04_1HR
TEMPLATE_FIELDS = {
    'var': 'ua50m',
    'year': 2023,
    'month': 1,
    'latitude': -23.55,
    'longitude': 133.39,
    'time_start_str': '2023-01-01T00:00:00Z',
    'time_end_str': '2023-01-31T23:00:00Z',
    'fileout_type': 'csv_file',
}


@pytest.mark.parametrize('url', [BARRA2_URL_AUS11_1HR, BARRA2_URL_AUST04_1HR])
def test_url_templates_format_fully(url: str) -> None:
    """The templates fill with the fields download.py supplies and leave no placeholders."""
    formatted = url.format(**TEMPLATE_FIELDS)
    assert not re.search(r'[{}]', formatted)
    assert formatted.startswith('https://thredds.nci.org.au/')
    assert '/1hr/' in formatted
    assert formatted.endswith('accept=csv_file')


def test_url_templates_use_only_supplied_fields() -> None:
    """Every placeholder in the templates is one download.py provides."""
    for url in (BARRA2_URL_AUS11_1HR, BARRA2_URL_AUST04_1HR):
        assert set(re.findall(r'{(\w+)', url)) <= set(TEMPLATE_FIELDS)


# endregion
