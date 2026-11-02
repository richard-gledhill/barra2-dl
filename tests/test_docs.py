"""Tests that docs/project-file.md lists the keys the project loader knows and that its examples load."""

import json
import re
import tomllib
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from barra2_dl.project import ProjectError, project_from_dict

DOC = Path(__file__).parent.parent / 'docs' / 'project-file.md'
SETTINGS_DEFAULTS = {'settings': {'start': date(2023, 1, 1), 'end': date(2023, 1, 31), 'format': 'netcdf'}}
FARM = {
    'type': 'Feature',
    'properties': {},
    'geometry': {
        'type': 'Polygon',
        'coordinates': [[[133.40, -23.50], [133.50, -23.50], [133.50, -23.60], [133.40, -23.60], [133.40, -23.50]]],
    },
}


def _section(title: str) -> str:
    """The text of one '## ' section of the reference."""
    text = DOC.read_text(encoding='utf-8')
    match = re.search(rf'^## {re.escape(title)}\n(.*?)(?=^## |\Z)', text, re.DOTALL | re.MULTILINE)
    assert match, f'{DOC.name} has no "## {title}" section'
    return match.group(1)


def _documented_keys(title: str) -> list[str]:
    """The keys in the first column of the tables of a section, each written in backticks."""
    return re.findall(r'^\| `(\w+)` \|', _section(title), re.MULTILINE)


def _known_keys(data: Mapping[str, Any], marker: str) -> list[str]:
    """The keys the loader says are known, read from the message it gives for an unknown key."""
    with pytest.raises(ProjectError) as caught:
        project_from_dict(data)
    message = next(line for line in str(caught.value).splitlines() if marker in line)
    return message.split('Known: ')[1].rstrip('.').split(', ')


def test_project_file_settings_keys_match_the_loader() -> None:
    """Every key the loader accepts in [settings] is documented, and nothing else is."""
    known = _known_keys(
        {'settings': {'unknown_key': 1}, 'site': [{'name': 'a', 'lat': 0, 'lon': 0}]}, 'Unknown setting'
    )
    assert sorted(_documented_keys('Settings keys')) == sorted(known)


def test_project_file_site_keys_match_the_loader() -> None:
    """Every key the loader accepts in a [[site]] table is documented, and nothing else is."""
    data = {**SETTINGS_DEFAULTS, 'site': [{'name': 'a', 'lat': 0, 'lon': 0, 'unknown_key': 1}]}
    assert sorted(_documented_keys('Site keys')) == sorted(_known_keys(data, 'Unknown key'))


def test_project_file_examples_load(tmp_path: Path) -> None:
    """Each toml example in the reference loads, with a farm.geojson beside it and default settings if it has none."""
    (tmp_path / 'farm.geojson').write_text(json.dumps(FARM), encoding='utf-8')
    blocks = re.findall(r'```toml\n(.*?)```', DOC.read_text(encoding='utf-8'), re.DOTALL)
    assert blocks
    for block in blocks:
        data = tomllib.loads(block)
        if 'settings' not in data:
            data |= SETTINGS_DEFAULTS
        assert project_from_dict(data, tmp_path).sites
