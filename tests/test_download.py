"""This module contains the barra2.download test function(s)."""

import io
import os
import re
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
import requests
import xarray as xr
from pandas import Timestamp

import barra2_dl.download
import barra2_dl.globals
from barra2_dl.globals import (
    BARRA2_DOMAINS,
    BARRA2_FIXED_FREQ,
    BARRA2_FREQS,
    BARRA2_PRESET_DEFAULT,
    BARRA2_PRESETS,
    BARRA2_URL,
    BARRA2_URL_AUS11_1HR,
    BARRA2_URL_AUST04_1HR,
    BARRA2_VAR_WIND_50,
    BARRA2_VAR_WIND_DEFAULT,
    BARRA2_VARS,
    BARRA2_WIND_VARS,
)
from barra2_dl.mapping import LatLonBBox, LatLonPoint

# region Test helpers
# Tests that hit the real THREDDS server are opt-in: set BARRA2_LIVE=1 to run them.
live_network = pytest.mark.skipif(not os.environ.get('BARRA2_LIVE'), reason='live network test; set BARRA2_LIVE=1')

# every (domain, freq) barra2-dl can download
DOMAIN_FREQS = [(domain, freq) for domain, freqs in BARRA2_FREQS.items() for freq in freqs]

# every variable named in the wind table or the default list, which must exist on every (domain, freq)
LISTED_VARS = sorted({name for entry in BARRA2_WIND_VARS for name in entry[:2]} | set(BARRA2_VAR_WIND_DEFAULT))


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int = 200, content: bytes = b'time,ua50m\n1,2.0\n') -> None:
        self.status_code = status_code
        self.content = content

    @property
    def text(self) -> str:
        """The content decoded as text."""
        return self.content.decode()


@pytest.fixture(autouse=True)
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace time.sleep so retries don't wait; the list collects the delays asked for."""
    delays: list[float] = []
    monkeypatch.setattr(barra2_dl.download.time, 'sleep', delays.append)
    return delays


def _script_get(monkeypatch: pytest.MonkeyPatch, replies: list[_FakeResponse | Exception]) -> list[str]:
    """Replace requests.get with one that gives each reply in turn (raising an exception), then repeats the last."""
    requested: list[str] = []

    def _get(url: str, **_kwargs) -> _FakeResponse:
        requested.append(url)
        reply = replies[min(len(requested), len(replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(barra2_dl.download.requests, 'get', _get)
    return requested


@pytest.fixture
def fake_get(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace requests.get with a recorder returning a 200 response; the list collects requested URLs."""
    requested: list[str] = []

    def _get(url: str, **_kwargs) -> _FakeResponse:
        requested.append(url)
        return _FakeResponse()

    monkeypatch.setattr(barra2_dl.download.requests, 'get', _get)
    return requested


DATA_DIR = Path(__file__).parent / 'data'
# the location the fixtures in tests/data were requested for
FIXTURE_LAT, FIXTURE_LON = -23.55, 133.40


def _seed_cache(folder: Path, pairs: list[tuple[str, str]]) -> None:
    """Copy the matching tests/data fixture into folder under each pair's filename, where one exists."""
    for _, name in pairs:
        # fixtures cover 3 days; the pairs name whole months, and an area's box is part of its filename
        source = re.sub(r'_\d{8}_\d{8}', '_20230101_20230103', name)
        source = re.sub(r'_area_n[^_]+_s[^_]+_e[^_]+_w[^_]+_', '_average4_', source)
        if (DATA_DIR / source).exists():
            (folder / name).write_bytes((DATA_DIR / source).read_bytes())


def _point_pairs(lat: float, lon: float, fileout_type: str = 'csv_file') -> list[tuple[str, str]]:
    """The nearest-node urlfilenames for tas at the given point, named as the fixtures are."""
    return barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['tas'], lat, lon, '2023-01-01', '2023-01-03', 'fixture', fileout_type
    )


def _average4_pairs(lat: float, lon: float) -> list[tuple[str, str]]:
    """The average4 urlfilenames for tas around the given point, named as the grid fixtures are."""
    return barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['tas'], lat, lon, '2023-01-01', '2023-01-03', 'grid', node_selection='average4'
    )


def _area_pairs(box: LatLonBBox) -> list[tuple[str, str]]:
    """The area urlfilenames for tas in the box, with the grid prefix of the fixtures."""
    return barra2_dl.download.area_data_urlfilenames(box, ['tas'], '2023-01-01', '2023-01-03', 'grid')


def _snapshot(folder: Path) -> dict[str, bytes]:
    """The name and bytes of every file in folder."""
    return {path.name: path.read_bytes() for path in folder.iterdir()}


# endregion


# region Errors
# region CacheMismatchError
def test_cache_mismatch_error_message_lists_files_and_fix() -> None:
    """The message names each file and reason, and says how to fix it; problems holds the pairs."""
    error = barra2_dl.download.CacheMismatchError(
        [('a.csv', 'holds 1, 2; requested 3, 4'), ('b.nc', "can't be read")], 'cache'
    )

    assert error.problems == [('a.csv', 'holds 1, 2; requested 3, 4'), ('b.nc', "can't be read")]
    assert 'a.csv: holds 1, 2; requested 3, 4' in str(error)
    assert "b.nc: can't be read" in str(error)
    assert str(error).endswith(
        'Rename the site (the filename prefix) or delete these files from cache, then run again.'
    )
    assert isinstance(error, ValueError)


# endregion
# endregion


# region Public API
# region point_data_urlfilenames
def test_point_data_urlfilenames_mid_month_start() -> None:
    """A mid-month start date still downloads the file for the start month."""
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL,
        ['ua50m'],
        -23.5527472,
        133.3961111,
        datetime(2023, 1, 15),
        datetime(2023, 2, 10),
        'demo',
    )
    assert [filename for _, filename in urlfilenames] == [
        'demo_AUS-11_1hr_ua50m_20230101_20230131.csv',
        'demo_AUS-11_1hr_ua50m_20230201_20230228.csv',
        'demo_AUS-11_fx_orog.csv',
    ]


@pytest.mark.parametrize(
    (
        'barra2_url',
        'barra2_vars',
        'latitude',
        'longitude',
        'start_datetime',
        'end_datetime',
        'fileout_prefix',
        'expected',
    ),
    [
        (
            BARRA2_URL,
            BARRA2_VAR_WIND_50,
            LatLonPoint(-23.5527472, 133.3961111).lat,
            LatLonPoint(-23.5527472, 133.3961111).lon,
            datetime.strptime('2023-01-01T00:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            datetime.strptime('2023-03-31T23:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            'demo',
            [
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ua50m/latest/ua50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202301-202301.nc?var=ua50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-01-01T00:00:00Z&time_end=2023-01-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_AUS-11_1hr_ua50m_20230101_20230131.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ua50m/latest/ua50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202302-202302.nc?var=ua50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-02-01T00:00:00Z&time_end=2023-02-28T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_AUS-11_1hr_ua50m_20230201_20230228.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ua50m/latest/ua50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202303-202303.nc?var=ua50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-03-01T00:00:00Z&time_end=2023-03-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_AUS-11_1hr_ua50m_20230301_20230331.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/va50m/latest/va50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202301-202301.nc?var=va50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-01-01T00:00:00Z&time_end=2023-01-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_AUS-11_1hr_va50m_20230101_20230131.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/va50m/latest/va50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202302-202302.nc?var=va50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-02-01T00:00:00Z&time_end=2023-02-28T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_AUS-11_1hr_va50m_20230201_20230228.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/va50m/latest/va50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202303-202303.nc?var=va50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-03-01T00:00:00Z&time_end=2023-03-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_AUS-11_1hr_va50m_20230301_20230331.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ta50m/latest/ta50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202301-202301.nc?var=ta50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-01-01T00:00:00Z&time_end=2023-01-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_AUS-11_1hr_ta50m_20230101_20230131.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ta50m/latest/ta50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202302-202302.nc?var=ta50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-02-01T00:00:00Z&time_end=2023-02-28T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_AUS-11_1hr_ta50m_20230201_20230228.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ta50m/latest/ta50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202303-202303.nc?var=ta50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-03-01T00:00:00Z&time_end=2023-03-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_AUS-11_1hr_ta50m_20230301_20230331.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/fx/orog/latest/orog_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1.nc?var=orog&latitude=-23.5527472&longitude=133.3961111&accept=csv_file',
                    'demo_AUS-11_fx_orog.csv',
                ),
            ],
        ),
    ],
)
def test_point_data_urlfilenames(
    barra2_url, barra2_vars, latitude, longitude, start_datetime, end_datetime, fileout_prefix, expected
) -> None:
    """Test with parametrization."""
    assert (
        barra2_dl.download.point_data_urlfilenames(
            barra2_url,
            barra2_vars,
            latitude,
            longitude,
            start_datetime,
            end_datetime,
            fileout_prefix,
        )
        == expected
    )


def test_point_data_urlfilenames_unsupported_fileout_type() -> None:
    """Only csv_file and netcdf4 downloads are supported."""
    with pytest.raises(ValueError, match='not supported'):
        barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo', fileout_type='netcdf3'
        )


def test_point_data_urlfilenames_leap_february() -> None:
    """February in a leap year runs to the 29th."""
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -23.5, 133.4, '2024-02-01', '2024-02-29', 'demo'
    )

    assert [name for _, name in urlfilenames] == [
        'demo_AUS-11_1hr_ua50m_20240201_20240229.csv',
        'demo_AUS-11_fx_orog.csv',
    ]
    assert 'time_end=2024-02-29T23:00:00Z' in urlfilenames[0][0]


def test_point_data_urlfilenames_no_variables() -> None:
    """No variables means no downloads."""
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, [], -23.5, 133.4, '2023-01-01', '2023-03-31', 'demo'
    )

    assert urlfilenames == []


def test_point_data_urlfilenames_aust04_urls() -> None:
    """AUST-04 produces BARRA-C2 URLs."""
    (url, _), *_ = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['va50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo', domain='AUST-04'
    )

    assert '/AUST-04/' in url
    assert 'BARRA-C2' in url
    assert 'va50m_AUST-04' in url


def test_point_data_urlfilenames_aust04_20min() -> None:
    """AUST-04 20-minute data uses the 20min folder and ends each month at 23:40."""
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -33.88, 151.18, '2020-01-01', '2020-01-31', 'site', domain='AUST-04', freq='20min'
    )

    assert urlfilenames == [
        (
            'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/20min/ua50m/latest/ua50m_AUST-04_ERA5_historical_hres_BOM_BARRA-C2_v1_20min_202001-202001.nc?var=ua50m&latitude=-33.88&longitude=151.18&time_start=2020-01-01T00:00:00Z&time_end=2020-01-31T23:40:00Z&timeStride=&vertCoord=&accept=csv_file',
            'site_AUST-04_20min_ua50m_20200101_20200131.csv',
        ),
        (
            'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/BARRA-C2/v1/fx/orog/latest/orog_AUST-04_ERA5_historical_hres_BOM_BARRA-C2_v1.nc?var=orog&latitude=-33.88&longitude=151.18&accept=csv_file',
            'site_AUST-04_fx_orog.csv',
        ),
    ]


@pytest.mark.parametrize(('domain', 'freq'), [('AUS-11', '20min'), ('AUS-22', '1hr'), ('AUST-04', 'day')])
def test_point_data_urlfilenames_unsupported_domain_freq(domain: str, freq: str) -> None:
    """A domain and frequency that barra2-dl does not support is rejected before any URL is built."""
    with pytest.raises(
        ValueError, match=re.escape('is not supported. Supported: AUS-11 1hr, AUST-04 1hr, AUST-04 20min')
    ):
        barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo', domain=domain, freq=freq
        )


def test_point_data_urlfilenames_filenames_differ_by_domain_and_freq() -> None:
    """The same variable and period give a different cache file per domain and frequency."""
    names = {
        barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo', domain=domain, freq=freq
        )[0][1]
        for domain, freq in DOMAIN_FREQS
    }

    assert len(names) == len(DOMAIN_FREQS)


def test_point_data_urlfilenames_alias_downloads_server_name() -> None:
    """ua10m/va10m are downloaded as uas/vas."""
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua10m', 'va10m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo'
    )

    assert [name for _, name in urlfilenames] == [
        'demo_AUS-11_1hr_uas_20230101_20230131.csv',
        'demo_AUS-11_1hr_vas_20230101_20230131.csv',
        'demo_AUS-11_fx_orog.csv',
    ]
    assert all('ua10m' not in url and 'va10m' not in url for url, _ in urlfilenames)


def test_point_data_urlfilenames_alias_and_server_name_download_once() -> None:
    """Asking for uas and its alias ua10m downloads one file per month."""
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['uas', 'ua10m'], -23.5, 133.4, '2023-01-01', '2023-02-28', 'demo'
    )

    assert [name for _, name in urlfilenames] == [
        'demo_AUS-11_1hr_uas_20230101_20230131.csv',
        'demo_AUS-11_1hr_uas_20230201_20230228.csv',
        'demo_AUS-11_fx_orog.csv',
    ]


@pytest.mark.parametrize(
    ('url', 'domain'),
    [(BARRA2_URL_AUS11_1HR, 'AUS-11'), (BARRA2_URL_AUST04_1HR, 'AUST-04')],
)
def test_point_data_urlfilenames_deprecated_url(url: str, domain: str) -> None:
    """The pre-filled 1hr templates still work, warn, and match BARRA2_URL with their domain."""
    with pytest.deprecated_call():
        deprecated = barra2_dl.download.point_data_urlfilenames(
            url, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo'
        )

    assert deprecated == barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo', domain=domain
    )


def test_point_data_urlfilenames_deprecated_url_ignores_domain_freq() -> None:
    """A pre-filled template fixes its own domain and freq, so a conflicting argument can't mislabel the files."""
    with pytest.deprecated_call():
        (_, name), *_ = barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL_AUS11_1HR, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo', domain='AUST-04'
        )

    assert name == 'demo_AUS-11_1hr_ua50m_20230101_20230131.csv'


@live_network
@pytest.mark.parametrize(('domain', 'freq'), DOMAIN_FREQS)
@pytest.mark.parametrize('var', LISTED_VARS)
def test_point_data_urlfilenames_variables_are_served(var: str, domain: str, freq: str) -> None:
    """Every listed wind variable and default variable is served on every supported domain and frequency."""
    (url, _), *_ = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, [var], -33.88, 151.18, '2020-01-01', '2020-01-31', 'live', domain=domain, freq=freq
    )

    assert requests.get(url, timeout=120).status_code == 200


@live_network
def test_point_data_urlfilenames_20min_has_three_steps_per_hour() -> None:
    """A 20-minute download has a value every 20 minutes through to 23:40 on the last day."""
    (url, _), *_ = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -33.88, 151.18, '2020-01-01', '2020-01-31', 'live', domain='AUST-04', freq='20min'
    )

    times = pd.read_csv(io.StringIO(requests.get(url, timeout=120).text))['time']

    assert len(times) == 31 * 24 * 3
    assert times.iloc[-1] == '2020-01-31T23:40:00Z'


@pytest.mark.xfail(strict=True, reason='fileout_prefix=None is documented as a todo and yields a "None_" filename')
def test_point_data_urlfilenames_default_prefix() -> None:
    """A missing prefix should not leak the string 'None' into filenames."""
    (_, name), *_ = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31'
    )

    assert not name.startswith('None')


def test_point_data_urlfilenames_unknown_variable() -> None:
    """A variable the server doesn't have is rejected before any URL is built."""
    with pytest.raises(ValueError, match=re.escape('Not available at AUS-11 1hr: ua20m, notavar.')):
        barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL, ['ua50m', 'ua20m', 'notavar'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo'
        )


def test_point_data_urlfilenames_variable_missing_at_20min_points_to_1hr() -> None:
    """The variables ps and hurs aren't published at 20min; the error names them and says they exist at 1hr."""
    with pytest.raises(
        ValueError, match=re.escape('Not available at AUST-04 20min: ps, hurs. Available at 1hr: ps, hurs.')
    ):
        barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL,
            ['ua50m', 'ps', 'hurs'],
            -33.88,
            151.18,
            '2020-01-01',
            '2020-01-31',
            'demo',
            domain='AUST-04',
            freq='20min',
        )


def test_point_data_urlfilenames_orog_once_per_node() -> None:
    """Every point download includes exactly one orog request, after the monthly files."""
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, BARRA2_PRESETS[BARRA2_PRESET_DEFAULT], -23.5, 133.4, '2023-01-01', '2023-03-31', 'demo'
    )
    names = [name for _, name in urlfilenames]

    assert names.count('demo_AUS-11_fx_orog.csv') == 1
    assert names[-1] == 'demo_AUS-11_fx_orog.csv'
    assert len(names) == len(BARRA2_PRESETS[BARRA2_PRESET_DEFAULT]) * 3 + 1


def test_point_data_urlfilenames_sftlf_only_on_request() -> None:
    """The land fraction sftlf is downloaded once, with the site preset, and never without it."""
    without = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo'
    )
    with_site = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m', *BARRA2_PRESETS['site']], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo'
    )

    assert not any('sftlf' in name for _, name in without)
    assert [name for _, name in with_site][-2:] == ['demo_AUS-11_fx_orog.csv', 'demo_AUS-11_fx_sftlf.csv']


def test_point_data_urlfilenames_fixed_field_url_has_no_time_range() -> None:
    """Fixed fields use the fx file, with no month and no time range."""
    (url, name), *_ = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['sftlf'], -33.88, 151.18, '2023-01-01', '2023-03-31', 'site', domain='AUST-04'
    )

    assert name == 'site_AUST-04_fx_orog.csv'
    assert url == (
        'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUST-04/BOM/ERA5/historical/hres/'
        'BARRA-C2/v1/fx/orog/latest/orog_AUST-04_ERA5_historical_hres_BOM_BARRA-C2_v1.nc'
        '?var=orog&latitude=-33.88&longitude=151.18&accept=csv_file'
    )


@live_network
@pytest.mark.parametrize(('domain', 'freq'), [*DOMAIN_FREQS, *((d, BARRA2_FIXED_FREQ) for d in BARRA2_DOMAINS)])
def test_inventory_matches_server(domain: str, freq: str) -> None:
    """The checked-in inventory lists the same variables as the THREDDS catalogue (rebuild it if this fails)."""
    url = (
        f'https://thredds.nci.org.au/thredds/catalog/ob53/output/reanalysis/{domain}/BOM/ERA5/historical/hres/'
        f'{BARRA2_DOMAINS[domain]}/v1/{freq}/catalog.xml'
    )
    titles = re.findall(r'xlink:title="([^"]+)"', requests.get(url, timeout=120).text)
    served = {t for t in titles if re.fullmatch(r'[A-Za-z0-9]+', t) and t not in {'Licence', 'Readme'}}

    assert served == BARRA2_VARS[(domain, freq)]


@live_network
@pytest.mark.parametrize('domain', BARRA2_DOMAINS)
def test_point_data_urlfilenames_orog_is_served(domain: str) -> None:
    """The fx point request returns one orog value as CSV."""
    url, _ = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -33.88, 151.18, '2020-01-01', '2020-01-31', 'live', domain=domain
    )[-1]

    df = pd.read_csv(io.StringIO(requests.get(url, timeout=120).text))

    assert len(df) == 1
    assert 'orog[unit="m"]' in df.columns


def test_point_data_urlfilenames_netcdf4_names_and_urls() -> None:
    """netCDF4 downloads ask for accept=netcdf4 and are cached as .nc, including the orog fixed field."""
    pairs = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo', fileout_type='netcdf4'
    )

    assert [name for _, name in pairs] == ['demo_AUS-11_1hr_ua50m_20230101_20230131.nc', 'demo_AUS-11_fx_orog.nc']
    assert all(url.endswith('accept=netcdf4') for url, _ in pairs)


def test_point_data_urlfilenames_csv_and_netcdf4_share_a_cache_without_clashing() -> None:
    """The same request as csv and as netCDF4 differs only in extension, so both can sit in one cache folder."""
    args = (BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo')
    csv_names = [name for _, name in barra2_dl.download.point_data_urlfilenames(*args)]
    nc_names = [name for _, name in barra2_dl.download.point_data_urlfilenames(*args, fileout_type='netcdf4')]

    assert [Path(name).stem for name in csv_names] == [Path(name).stem for name in nc_names]
    assert set(csv_names).isdisjoint(nc_names)


@live_network
def test_point_data_urlfilenames_netcdf4_is_served() -> None:
    """The netCDF4 point request returns a netCDF4 (HDF5) file."""
    (url, _), *_ = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -33.88, 151.18, '2020-01-01', '2020-01-31', 'live', fileout_type='netcdf4'
    )

    response = requests.get(url, timeout=120)

    assert response.status_code == 200
    assert response.content[1:4] == b'HDF'


def test_point_data_urlfilenames_average4_requests_a_box_around_the_site() -> None:
    """The four-node average is one bounding-box request per variable-month, a grid spacing either side of the site."""
    pairs = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -23.55, 133.40, '2023-01-01', '2023-01-31', 'demo', node_selection='average4'
    )

    url, name = pairs[0]
    assert name == 'demo_AUS-11_1hr_average4_ua50m_20230101_20230131.nc'
    assert 'north=-23.44&south=-23.66&east=133.51&west=133.29&horizStride=1' in url
    assert 'latitude=' not in url
    assert url.endswith('accept=netcdf4')
    assert 'time_start=2023-01-01T00:00:00Z&time_end=2023-01-31T23:00:00Z' in url


def test_point_data_urlfilenames_average4_box_follows_the_domain_grid_spacing() -> None:
    """AUST-04 nodes are 0.04 degrees apart, so its box is smaller."""
    (url, _), *_ = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL,
        ['ua50m'],
        -33.88,
        151.18,
        '2020-01-01',
        '2020-01-31',
        'demo',
        domain='AUST-04',
        node_selection='average4',
    )

    assert 'north=-33.84&south=-33.92&east=151.22&west=151.14' in url


def test_point_data_urlfilenames_average4_orog_is_requested_for_the_same_box() -> None:
    """The automatic orog is a bounding-box request with no time range, cached under the average4 name."""
    pairs = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -23.55, 133.40, '2023-01-01', '2023-01-31', 'demo', node_selection='average4'
    )

    url, name = pairs[-1]
    assert name == 'demo_AUS-11_fx_average4_orog.nc'
    assert '/fx/orog/' in url
    assert 'north=-23.44&south=-23.66&east=133.51&west=133.29' in url
    assert 'time_start' not in url


def test_point_data_urlfilenames_average4_cannot_be_csv() -> None:
    """A grid doesn't fit csv, so asking for it is an error rather than a silent switch."""
    with pytest.raises(ValueError, match='netcdf4'):
        barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL,
            ['ua50m'],
            -23.5,
            133.4,
            '2023-01-01',
            '2023-01-31',
            'demo',
            fileout_type='csv_file',
            node_selection='average4',
        )


def test_point_data_urlfilenames_average4_names_do_not_clash_with_the_nearest_node() -> None:
    """Nearest and average4 downloads for the same site and period can share a cache folder."""
    args = (BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo')
    nearest = {name for _, name in barra2_dl.download.point_data_urlfilenames(*args, fileout_type='netcdf4')}
    average = {name for _, name in barra2_dl.download.point_data_urlfilenames(*args, node_selection='average4')}

    assert nearest.isdisjoint(average)


@pytest.mark.parametrize('node_selection', ['area', 'average9'])
def test_point_data_urlfilenames_unsupported_node_selection(node_selection: str) -> None:
    """A point request is for the nearest node or the four-node average; an area has its own function."""
    with pytest.raises(ValueError, match='node_selection'):
        barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo', node_selection=node_selection
        )


@live_network
@pytest.mark.parametrize(('domain', 'freq'), DOMAIN_FREQS)
def test_point_data_urlfilenames_average4_box_returns_nodes_around_the_site(
    domain: str, freq: str, tmp_path: Path
) -> None:
    """The live bounding-box response holds real nodes on both sides of the site, so the four can be picked."""
    (url, _), *_ = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL,
        ['ua50m'],
        -33.88,
        151.18,
        '2020-01-01',
        '2020-01-02',
        'live',
        domain=domain,
        freq=freq,
        node_selection='average4',
    )
    response = requests.get(url, timeout=120)
    (tmp_path / 'grid.nc').write_bytes(response.content)

    with xr.open_dataset(tmp_path / 'grid.nc') as grid:
        lats, lons = grid['lat'].to_numpy(), grid['lon'].to_numpy()

    assert response.status_code == 200
    assert lats.min() <= -33.88 <= lats.max()
    assert lons.min() <= 151.18 <= lons.max()
    assert lats.size >= 2
    assert lons.size >= 2


# endregion


# region area_data_urlfilenames
BOX = LatLonBBox(north=-23.4, south=-23.7, east=133.5, west=133.2)


def test_area_data_urlfilenames_requests_the_box_with_the_box_in_the_name() -> None:
    """One bounding-box request per variable-month for the given box, with the box in the cache filename."""
    pairs = barra2_dl.download.area_data_urlfilenames(BOX, ['ua50m'], '2023-01-01', '2023-02-28', 'farm')

    assert [name for _, name in pairs] == [
        'farm_AUS-11_1hr_area_n-23.4_s-23.7_e133.5_w133.2_ua50m_20230101_20230131.nc',
        'farm_AUS-11_1hr_area_n-23.4_s-23.7_e133.5_w133.2_ua50m_20230201_20230228.nc',
        'farm_AUS-11_fx_area_n-23.4_s-23.7_e133.5_w133.2_orog.nc',
    ]
    assert 'north=-23.4&south=-23.7&east=133.5&west=133.2&horizStride=1' in pairs[0][0]
    assert all(url.endswith('accept=netcdf4') for url, _ in pairs)


def test_area_data_urlfilenames_different_boxes_have_different_cache_files() -> None:
    """Changing the box must not reuse the previous box's cached files."""
    other = LatLonBBox(north=-23.4, south=-23.7, east=133.6, west=133.2)
    first = barra2_dl.download.area_data_urlfilenames(BOX, ['ua50m'], '2023-01-01', '2023-01-31', 'farm')
    second = barra2_dl.download.area_data_urlfilenames(other, ['ua50m'], '2023-01-01', '2023-01-31', 'farm')

    assert {name for _, name in first}.isdisjoint(name for _, name in second)


def test_area_data_urlfilenames_resolves_aliases_and_domain_and_freq() -> None:
    """Aliases are downloaded under server names, and the 20-minute month ends at 23:40."""
    (url, name), *_ = barra2_dl.download.area_data_urlfilenames(
        BOX, ['ua10m'], '2020-01-01', '2020-01-31', 'farm', domain='AUST-04', freq='20min'
    )

    assert '_20min_area_' in name
    assert '/uas/' in url
    assert 'time_end=2020-01-31T23:40:00Z' in url


def test_area_data_urlfilenames_cannot_be_csv() -> None:
    """A grid doesn't fit csv."""
    with pytest.raises(ValueError, match='netcdf4'):
        barra2_dl.download.area_data_urlfilenames(
            BOX, ['ua50m'], '2023-01-01', '2023-01-31', 'farm', fileout_type='csv_file'
        )


def test_area_data_urlfilenames_unknown_variable_and_freq() -> None:
    """Variables and the domain and frequency are validated before any URL is built."""
    with pytest.raises(ValueError, match='Not available'):
        barra2_dl.download.area_data_urlfilenames(BOX, ['ua999m'], '2023-01-01', '2023-01-31', 'farm')
    with pytest.raises(ValueError, match='not supported'):
        barra2_dl.download.area_data_urlfilenames(BOX, ['ua50m'], '2023-01-01', '2023-01-31', 'farm', freq='20min')


@live_network
def test_area_data_urlfilenames_box_returns_a_grid(tmp_path: Path) -> None:
    """The live response for a box is a (time, lat, lon) grid covering it."""
    (url, _), *_ = barra2_dl.download.area_data_urlfilenames(BOX, ['ua50m'], '2023-01-01', '2023-01-02', 'live')
    response = requests.get(url, timeout=120)
    (tmp_path / 'grid.nc').write_bytes(response.content)

    with xr.open_dataset(tmp_path / 'grid.nc') as grid:
        dims = grid['ua50m'].dims
        lats = grid['lat'].to_numpy()

    assert response.status_code == 200
    assert dims == ('time', 'lat', 'lon')
    # nodes whose grid cell overlaps the box are returned, so the edge nodes can sit just inside or outside it
    assert -23.76 < lats.min() < -23.6
    assert -23.5 < lats.max() < -23.35


# endregion


# region preset_variables
@pytest.mark.parametrize('domain', BARRA2_DOMAINS)
@pytest.mark.parametrize('preset', BARRA2_PRESETS)
def test_preset_variables_default_frequency(preset: str, domain: str) -> None:
    """Every preset resolves at the 1hr default on both domains."""
    assert barra2_dl.download.preset_variables(preset, domain) == BARRA2_PRESETS[preset]


def test_preset_variables_wind_at_20min() -> None:
    """The wind preset works at AUST-04 20min."""
    assert barra2_dl.download.preset_variables('wind', 'AUST-04', '20min') == BARRA2_PRESETS['wind']


def test_preset_variables_default_preset_at_20min_points_to_wind() -> None:
    """wind+density at 20min fails naming ps and hurs, says they exist at 1hr, and offers the wind preset."""
    with pytest.raises(ValueError, match=r'needs ps, hurs.*available at 1hr.*Presets available at AUST-04 20min: wind'):
        barra2_dl.download.preset_variables(BARRA2_PRESET_DEFAULT, 'AUST-04', '20min')


@pytest.mark.parametrize(('preset', 'missing'), [('extremes', 'sfcWindmax'), ('environment', 'pr, rsds, hurs')])
def test_preset_variables_partial_presets_at_20min(preset: str, missing: str) -> None:
    """Presets only partly published at 20min are rejected, never downloaded in part."""
    with pytest.raises(ValueError, match=re.escape(f'needs {missing}, which are not available at AUST-04 20min')):
        barra2_dl.download.preset_variables(preset, 'AUST-04', '20min')


def test_preset_variables_unknown_preset() -> None:
    """An unknown preset name lists the presets."""
    with pytest.raises(ValueError, match=re.escape('Unknown preset <windy>. Presets: wind, wind+density')):
        barra2_dl.download.preset_variables('windy')


def test_preset_variables_unsupported_freq() -> None:
    """A frequency the domain doesn't have is rejected."""
    with pytest.raises(ValueError, match='AUS-11 20min is not supported'):
        barra2_dl.download.preset_variables('wind', 'AUS-11', '20min')


def test_preset_variables_returns_a_copy() -> None:
    """Changing the returned list doesn't change the preset."""
    barra2_dl.download.preset_variables('wind').append('ps')

    assert 'ps' not in BARRA2_PRESETS['wind']


# endregion


# region resolve_variable_versions
def _das_text(version: str) -> str:
    """An OPeNDAP .das response carrying the given variable_version."""
    return f'Attributes {{ NC_GLOBAL {{ String variable_version "{version}"; }} }}'


def test_resolve_variable_versions_reads_each_variables_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each variable (and the automatic orog) gets the version its own file reports; aliases resolve to server names."""
    versions = {'uas': 'v20231001', 'ua50m': 'v20240516', 'orog': 'v20231001'}

    def _get(url: str, **_kwargs) -> _FakeResponse:
        found = re.search(r'/([A-Za-z0-9]+)_AUS-11_ERA5', url)
        assert found
        return _FakeResponse(200, _das_text(versions[found.group(1)]).encode())

    monkeypatch.setattr(barra2_dl.download.requests, 'get', _get)

    result = barra2_dl.download.resolve_variable_versions(['ua10m', 'ua50m'], 'AUS-11', '1hr')

    assert result == versions


def test_resolve_variable_versions_asks_the_opendap_attributes(fake_get: list[str]) -> None:
    """Versions come from the small OPeNDAP .das request, not a data download."""
    barra2_dl.download.resolve_variable_versions(['ua50m'], 'AUST-04', '20min')

    assert all('/dodsC/' in url and url.endswith('.nc.das') for url in fake_get)
    assert any('/20min/ua50m/' in url for url in fake_get)
    assert any('/fx/orog/' in url for url in fake_get)


@pytest.mark.parametrize('failure', ['status', 'text', 'error'])
def test_resolve_variable_versions_falls_back_to_latest(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A variable whose version can't be read is recorded as latest."""

    def _get(url: str, **_kwargs) -> _FakeResponse:
        if failure == 'error':
            raise requests.ConnectionError('offline')
        if failure == 'status':
            return _FakeResponse(404, b'')
        return _FakeResponse(200, b'no such attribute')

    monkeypatch.setattr(barra2_dl.download.requests, 'get', _get)

    assert barra2_dl.download.resolve_variable_versions(['ua50m']) == {'ua50m': 'latest', 'orog': 'latest'}


def test_resolve_variable_versions_without_variables_is_empty(fake_get: list[str]) -> None:
    """No variables means nothing to resolve, not even the automatic orog."""
    assert barra2_dl.download.resolve_variable_versions([]) == {}
    assert fake_get == []


def test_resolve_variable_versions_unsupported_freq() -> None:
    """An unsupported domain and frequency is rejected."""
    with pytest.raises(ValueError, match='not supported'):
        barra2_dl.download.resolve_variable_versions(['ua50m'], 'AUS-11', '20min')


@live_network
@pytest.mark.parametrize(('domain', 'freq'), DOMAIN_FREQS)
def test_resolve_variable_versions_live(domain: str, freq: str) -> None:
    """The server reports a dated version such as v20240516 for the winds and the node altitude."""
    result = barra2_dl.download.resolve_variable_versions(['ua50m', 'va50m'], domain, freq)

    assert set(result) == {'ua50m', 'va50m', 'orog'}
    assert all(re.fullmatch(r'v\d{8}', version) for version in result.values())


# endregion


# region download_serial
@live_network
@pytest.mark.parametrize(('domain', 'freq'), DOMAIN_FREQS)
def test_download_serial(domain: str, freq: str, tmp_path: Path) -> None:
    """Three months of the 50 m variables download from every supported domain and frequency."""
    download_folder = tmp_path / 'cache'
    download_folder.mkdir()
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL,
        BARRA2_VAR_WIND_50,
        LatLonPoint(-23.5527472, 133.3961111).lat,
        LatLonPoint(-23.5527472, 133.3961111).lon,
        datetime(2023, 1, 1),
        datetime(2023, 3, 31),
        'live',
        domain=domain,
        freq=freq,
    )

    barra2_dl.download.download_serial(urlfilenames, download_folder)

    for item in [item[1] for item in urlfilenames]:
        filename = download_folder / os.path.basename(item)
        assert filename.exists()


def test_download_serial_offline(fake_get: list[str], tmp_path: Path) -> None:
    """Every pair is fetched in order and saved, without touching the network."""
    urlfilenames = [(f'https://example.test/{i}', f'file_{i}.csv') for i in range(3)]

    barra2_dl.download.download_serial(urlfilenames, tmp_path)

    assert fake_get == [url for url, _ in urlfilenames]
    assert sorted(p.name for p in tmp_path.iterdir()) == ['file_0.csv', 'file_1.csv', 'file_2.csv']


def test_download_serial_cancel_mid_run_stops_new_requests(fake_get: list[str], tmp_path: Path) -> None:
    """Setting cancel from progress stops the next request; the files not yet tried come back cancelled."""
    cancel = threading.Event()
    urlfilenames = [(f'https://example.test/{i}', f'file_{i}.csv') for i in range(4)]

    results = barra2_dl.download.download_serial(
        urlfilenames,
        tmp_path,
        progress=lambda done, _total, _result: cancel.set() if done == 2 else None,
        cancel=cancel,
    )

    assert [result.status for result in results] == ['downloaded', 'downloaded', 'cancelled', 'cancelled']
    assert fake_get == [url for url, _ in urlfilenames[:2]]


def test_download_serial_empty_list(fake_get: list[str], tmp_path: Path) -> None:
    """An empty list downloads nothing."""
    barra2_dl.download.download_serial([], tmp_path)

    assert fake_get == []


# endregion


# region download_multithread
@live_network
@pytest.mark.parametrize(('domain', 'freq'), DOMAIN_FREQS)
def test_download_multithread(domain: str, freq: str, tmp_path: Path) -> None:
    """Three months of the 50 m variables download from every supported domain and frequency."""
    download_folder = tmp_path / 'cache'
    download_folder.mkdir()
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL,
        BARRA2_VAR_WIND_50,
        LatLonPoint(-23.5527472, 133.3961111).lat,
        LatLonPoint(-23.5527472, 133.3961111).lon,
        datetime(2023, 1, 1),
        datetime(2023, 3, 31),
        'live',
        domain=domain,
        freq=freq,
    )

    barra2_dl.download.download_multithread(urlfilenames, download_folder)

    for item in [item[1] for item in urlfilenames]:
        filename = download_folder / os.path.basename(item)
        assert filename.exists()


@pytest.mark.parametrize(('workers', 'expected'), [(None, 4), (2, 2), (8, 8), (0, 1)])
def test_download_multithread_pool_size(
    workers: int | None, expected: int, fake_get: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The pool has workers threads (4 by default), never fewer than one, whatever the cpu count."""
    sizes: list[int] = []
    real_pool = barra2_dl.download.ThreadPool

    def recording_pool(size: int):
        sizes.append(size)
        return real_pool(size)

    monkeypatch.setattr(barra2_dl.download, 'ThreadPool', recording_pool)
    urlfilenames = [(f'https://example.test/{i}', f'file_{i}.csv') for i in range(3)]

    if workers is None:
        results = barra2_dl.download.download_multithread(urlfilenames, tmp_path)
    else:
        results = barra2_dl.download.download_multithread(urlfilenames, tmp_path, workers=workers)

    assert sizes == [expected]
    assert [result.status for result in results] == ['downloaded'] * 3


def test_download_multithread_offline(fake_get: list[str], tmp_path: Path) -> None:
    """Every pair is fetched and saved in parallel, without touching the network."""
    urlfilenames = [(f'https://example.test/{i}', f'file_{i}.csv') for i in range(5)]

    barra2_dl.download.download_multithread(urlfilenames, tmp_path)

    assert sorted(fake_get) == sorted(url for url, _ in urlfilenames)
    assert len(list(tmp_path.iterdir())) == 5


@pytest.mark.parametrize('download', ['download_serial', 'download_multithread'])
def test_download_results_come_back_in_input_order(
    download: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each input has a result, in input order: downloaded, skipped or failed."""
    (tmp_path / 'file_1.csv').write_bytes(b'cached')
    monkeypatch.setattr(
        barra2_dl.download.requests,
        'get',
        lambda url, **_k: _FakeResponse(404, b'') if url.endswith('/2') else _FakeResponse(),
    )
    urlfilenames = [(f'https://example.test/{i}', f'file_{i}.csv') for i in range(4)]

    results = getattr(barra2_dl.download, download)(urlfilenames, tmp_path)

    assert [(result.filename, result.status) for result in results] == [
        ('file_0.csv', 'downloaded'),
        ('file_1.csv', 'skipped'),
        ('file_2.csv', 'failed'),
        ('file_3.csv', 'downloaded'),
    ]


@pytest.mark.parametrize('download', ['download_serial', 'download_multithread'])
def test_download_progress_is_called_once_per_file_from_the_calling_thread(
    download: str, fake_get: list[str], tmp_path: Path
) -> None:
    """progress(done, total, result) runs for each file in order, on the thread that called the download."""
    calls: list[tuple[int, int, str, int]] = []

    def progress(done: int, total: int, result: barra2_dl.download.FileResult) -> None:
        calls.append((done, total, result.filename, threading.get_ident()))

    urlfilenames = [(f'https://example.test/{i}', f'file_{i}.csv') for i in range(3)]

    getattr(barra2_dl.download, download)(urlfilenames, tmp_path, progress=progress)

    assert [call[:3] for call in calls] == [(1, 3, 'file_0.csv'), (2, 3, 'file_1.csv'), (3, 3, 'file_2.csv')]
    assert {call[3] for call in calls} == {threading.get_ident()}


@pytest.mark.parametrize('download', ['download_serial', 'download_multithread'])
def test_download_cancelled_before_the_start_makes_no_request(
    download: str, fake_get: list[str], tmp_path: Path
) -> None:
    """With cancel already set every file comes back cancelled and nothing is requested or written."""
    cancel = threading.Event()
    cancel.set()
    urlfilenames = [(f'https://example.test/{i}', f'file_{i}.csv') for i in range(3)]

    results = getattr(barra2_dl.download, download)(urlfilenames, tmp_path, cancel=cancel)

    assert [result.status for result in results] == ['cancelled'] * 3
    assert fake_get == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('download', ['download_serial', 'download_multithread'])
def test_download_missing_folder_raises(download: str, fake_get: list[str], tmp_path: Path) -> None:
    """A missing cache folder still raises before any request."""
    with pytest.raises(FileNotFoundError):
        getattr(barra2_dl.download, download)([('https://example.test/a', 'a.csv')], tmp_path / 'missing')

    assert fake_get == []


# endregion
# endregion


# region Helpers
# region _list_months
@pytest.mark.parametrize(
    ('start_datetime', 'end_datetime', 'expected'),
    [
        (
            '1/1/2023',
            '1/1/2024',
            [
                Timestamp('2023-01-01 00:00:00'),
                Timestamp('2023-02-01 00:00:00'),
                Timestamp('2023-03-01 00:00:00'),
                Timestamp('2023-04-01 00:00:00'),
                Timestamp('2023-05-01 00:00:00'),
                Timestamp('2023-06-01 00:00:00'),
                Timestamp('2023-07-01 00:00:00'),
                Timestamp('2023-08-01 00:00:00'),
                Timestamp('2023-09-01 00:00:00'),
                Timestamp('2023-10-01 00:00:00'),
                Timestamp('2023-11-01 00:00:00'),
                Timestamp('2023-12-01 00:00:00'),
                Timestamp('2024-01-01 00:00:00'),
            ],
        ),
    ],
)
def test_list_months(start_datetime: str, end_datetime: str, expected: list) -> None:
    """Test with parametrization."""
    assert barra2_dl.download._list_months(start_datetime, end_datetime) == expected


@pytest.mark.parametrize(
    ('start_datetime', 'end_datetime', 'expected'),
    [
        # a mid-month start still includes the month it falls in
        ('2023-01-15', '2023-03-10', [Timestamp('2023-01-01'), Timestamp('2023-02-01'), Timestamp('2023-03-01')]),
        ('2023-01-31', '2023-02-01', [Timestamp('2023-01-01'), Timestamp('2023-02-01')]),
        (datetime(2023, 1, 15, 13, 30), datetime(2023, 1, 20), [Timestamp('2023-01-01')]),
        # start and end within the same month give that month only
        ('2023-06-10', '2023-06-20', [Timestamp('2023-06-01')]),
        # end at the very start of the next month includes it
        ('2023-12-31', '2024-01-01', [Timestamp('2023-12-01'), Timestamp('2024-01-01')]),
    ],
)
def test_list_months_mid_month_start(
    start_datetime: str | datetime, end_datetime: str | datetime, expected: list
) -> None:
    """The start month is never dropped when the start date is not the first of the month."""
    assert barra2_dl.download._list_months(start_datetime, end_datetime) == expected


def test_list_months_invalid_start() -> None:
    """An unparseable start is reported as such."""
    with pytest.raises(ValueError, match='Invalid start_datetime'):
        barra2_dl.download._list_months('not a date', '2023-01-01')


def test_list_months_invalid_end() -> None:
    """An unparseable end is reported as such."""
    with pytest.raises(ValueError, match='Invalid end_datetime'):
        barra2_dl.download._list_months('2023-01-01', 'not a date')


# endregion


# region _list_timestamp_range
def test_list_timestamp_range_returns_first_and_last() -> None:
    """The earliest and latest timestamps are returned, whatever the row order."""
    df = pd.DataFrame({'time': ['2023-01-03', '2023-01-01', '2023-01-02']})

    assert barra2_dl.download._list_timestamp_range(df, 'time') == [Timestamp('2023-01-01'), Timestamp('2023-01-03')]


def test_list_timestamp_range_missing_column() -> None:
    """A missing column is rejected."""
    with pytest.raises(ValueError, match='does not exist'):
        barra2_dl.download._list_timestamp_range(pd.DataFrame({'time': ['2023-01-01']}), 'timestamp')


# endregion


# region _download_file
def test_download_file_writes_content(fake_get: list[str], tmp_path: Path) -> None:
    """A 200 response is saved as folder/file_name."""
    barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert fake_get == ['https://example.test/a']
    assert (tmp_path / 'a.csv').read_bytes() == b'time,ua50m\n1,2.0\n'


@pytest.mark.parametrize('status_code', [404, 500])
def test_download_file_failed_status_writes_nothing(
    status_code: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-200 response is reported but not raised, and no file is created."""
    monkeypatch.setattr(barra2_dl.download.requests, 'get', lambda *_a, **_k: _FakeResponse(status_code, b'error'))

    barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert not (tmp_path / 'a.csv').exists()


def test_download_file_existing_file_is_skipped(fake_get: list[str], tmp_path: Path) -> None:
    """An existing file is neither re-fetched nor overwritten, so a re-run resumes."""
    (tmp_path / 'a.csv').write_bytes(b'original')

    barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert fake_get == []
    assert (tmp_path / 'a.csv').read_bytes() == b'original'


def test_download_file_result_downloaded(fake_get: list[str], tmp_path: Path) -> None:
    """A download returns its filename, status, status code and the one attempt."""
    result = barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert result == barra2_dl.download.FileResult('a.csv', 'downloaded', 200, 1)


def test_download_file_result_skipped(fake_get: list[str], tmp_path: Path) -> None:
    """An existing file is reported as skipped, with no attempt."""
    (tmp_path / 'a.csv').write_bytes(b'original')

    result = barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert result == barra2_dl.download.FileResult('a.csv', 'skipped')


def test_download_file_404_is_not_retried(monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tmp_path: Path) -> None:
    """A 404 fails at once: one attempt, no waiting, nothing written."""
    requested = _script_get(monkeypatch, [_FakeResponse(404, b'missing')])

    result = barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert result == barra2_dl.download.FileResult('a.csv', 'failed', 404, 1, 'Status code: 404')
    assert len(requested) == 1
    assert sleeps == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    'bad_reply',
    [_FakeResponse(503, b'busy'), _FakeResponse(200, b''), requests.ConnectionError('reset'), requests.Timeout('slow')],
    ids=['5xx', 'empty', 'connection-error', 'timeout'],
)
def test_download_file_retries_then_succeeds(
    bad_reply: _FakeResponse | Exception, monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tmp_path: Path
) -> None:
    """A transient failure is retried after 1 then 2 seconds, and a later success is written."""
    requested = _script_get(monkeypatch, [bad_reply, bad_reply, _FakeResponse()])

    result = barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert result == barra2_dl.download.FileResult('a.csv', 'downloaded', 200, 3)
    assert len(requested) == 3
    assert sleeps == [1, 2]
    assert (tmp_path / 'a.csv').exists()


@pytest.mark.parametrize(
    ('bad_reply', 'status_code', 'error'),
    [
        (_FakeResponse(500, b'x'), 500, 'Status code: 500'),
        (_FakeResponse(200, b''), 200, 'The response was empty.'),
        (requests.ConnectionError('reset'), None, 'ConnectionError: reset'),
        (requests.Timeout('slow'), None, 'Timeout: slow'),
    ],
    ids=['5xx', 'empty', 'connection-error', 'timeout'],
)
def test_download_file_gives_up_after_four_attempts(
    bad_reply: _FakeResponse | Exception,
    status_code: int | None,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
    sleeps: list[float],
    tmp_path: Path,
) -> None:
    """Three retries (four attempts) waiting 1, 2 and 4 seconds, then a failed result: nothing is raised or written."""
    requested = _script_get(monkeypatch, [bad_reply])

    result = barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert result == barra2_dl.download.FileResult('a.csv', 'failed', status_code, 4, error)
    assert len(requested) == 4
    assert sleeps == [1, 2, 4]
    assert list(tmp_path.iterdir()) == []


def test_download_file_missing_folder(fake_get: list[str], tmp_path: Path) -> None:
    """A missing folder raises before any request is made."""
    with pytest.raises(FileNotFoundError):
        barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path / 'missing')

    assert fake_get == []


def test_download_file_empty_response_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A 200 with an empty body is a failure: reported, and nothing is written."""
    monkeypatch.setattr(barra2_dl.download.requests, 'get', lambda *_a, **_k: _FakeResponse(200, b''))

    barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert list(tmp_path.iterdir()) == []
    assert 'The response was empty' in capsys.readouterr().out


def test_download_file_write_interrupted_leaves_no_final_file(
    fake_get: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A write that fails part way leaves nothing under the final name, so the next run fetches it again."""

    def partial_write(self: Path, data: bytes) -> int:
        with self.open('wb') as file:
            file.write(data[:3])
        raise OSError('disk full')

    monkeypatch.setattr(Path, 'write_bytes', partial_write)

    with pytest.raises(OSError, match='disk full'):
        barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert not (tmp_path / 'a.csv').exists()


def test_download_file_success_leaves_no_part_file(fake_get: list[str], tmp_path: Path) -> None:
    """A finished download is renamed into place, so no .part file remains."""
    barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert [path.name for path in tmp_path.iterdir()] == ['a.csv']


def test_download_file_overwrites_part_left_by_killed_run(fake_get: list[str], tmp_path: Path) -> None:
    """A .part file from a killed run is replaced by the next download."""
    (tmp_path / 'a.csv.part').write_bytes(b'half')

    barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path)

    assert [path.name for path in tmp_path.iterdir()] == ['a.csv']
    assert (tmp_path / 'a.csv').read_bytes() == b'time,ua50m\n1,2.0\n'


# endregion


# region _check_cache
@pytest.mark.parametrize('fileout_type', ['csv_file', 'netcdf4'])
def test_check_cache_point_matching_request_is_skipped(fileout_type: str, fake_get: list[str], tmp_path: Path) -> None:
    """Cached point files made for the requested point are reused, not fetched."""
    pairs = _point_pairs(FIXTURE_LAT, FIXTURE_LON, fileout_type)
    _seed_cache(tmp_path, pairs)
    before = _snapshot(tmp_path)

    barra2_dl.download.download_serial(pairs, tmp_path)

    assert fake_get == []
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('fileout_type', ['csv_file', 'netcdf4'])
def test_check_cache_point_within_tolerance_is_skipped(fileout_type: str, fake_get: list[str], tmp_path: Path) -> None:
    """A request 0.0004 degrees away is the same point at the 3 decimals NCSS writes."""
    pairs = _point_pairs(FIXTURE_LAT - 0.0004, FIXTURE_LON, fileout_type)
    _seed_cache(tmp_path, pairs)

    barra2_dl.download.download_serial(pairs, tmp_path)

    assert fake_get == []


@pytest.mark.parametrize('fileout_type', ['csv_file', 'netcdf4'])
@pytest.mark.parametrize('download', ['download_serial', 'download_multithread'])
def test_check_cache_point_moved_raises_before_any_request(
    download: str, fileout_type: str, fake_get: list[str], tmp_path: Path
) -> None:
    """A point 0.1 degrees away raises, naming the file and both locations; nothing is fetched or changed."""
    pairs = _point_pairs(FIXTURE_LAT - 0.1, FIXTURE_LON, fileout_type)
    _seed_cache(tmp_path, pairs)
    before = _snapshot(tmp_path)

    with pytest.raises(barra2_dl.download.CacheMismatchError) as error:
        getattr(barra2_dl.download, download)(pairs, tmp_path)

    names = [name for _, name in pairs]
    assert [name for name, _ in error.value.problems] == names
    assert error.value.problems[0][1] == 'holds -23.550, 133.400; requested -23.650, 133.400'
    assert names[0] in str(error.value)
    assert fake_get == []
    assert _snapshot(tmp_path) == before


def test_check_cache_average4_point_inside_nodes_is_skipped(fake_get: list[str], tmp_path: Path) -> None:
    """A point moved inside the cached grid's nodes still has its four surrounding nodes."""
    pairs = _average4_pairs(-23.60, 133.40)
    _seed_cache(tmp_path, pairs)

    barra2_dl.download.download_serial(pairs, tmp_path)

    assert fake_get == []


def test_check_cache_average4_point_outside_nodes_raises(fake_get: list[str], tmp_path: Path) -> None:
    """A point outside the cached grid's nodes fails, naming the point its nodes don't surround."""
    pairs = _average4_pairs(-23.70, 133.40)
    _seed_cache(tmp_path, pairs)

    with pytest.raises(barra2_dl.download.CacheMismatchError) as error:
        barra2_dl.download.download_serial(pairs, tmp_path)

    assert error.value.problems[0][1] == "its nodes don't surround -23.700, 133.400"
    assert fake_get == []


def test_check_cache_area_inside_bounds_is_skipped(fake_get: list[str], tmp_path: Path) -> None:
    """A box inside the cached grid's geospatial bounds is covered."""
    pairs = _area_pairs(LatLonBBox(north=-23.4, south=-23.7, east=133.5, west=133.2))
    _seed_cache(tmp_path, pairs)

    barra2_dl.download.download_serial(pairs, tmp_path)

    assert fake_get == []


def test_check_cache_area_wider_than_bounds_raises(fake_get: list[str], tmp_path: Path) -> None:
    """A wider box than the cached grid covers fails."""
    pairs = _area_pairs(LatLonBBox(north=-23.0, south=-23.7, east=133.5, west=133.2))
    _seed_cache(tmp_path, pairs)

    with pytest.raises(barra2_dl.download.CacheMismatchError) as error:
        barra2_dl.download.download_serial(pairs, tmp_path)

    assert error.value.problems[0][1] == "doesn't cover the box"
    assert fake_get == []


@pytest.mark.parametrize('download', ['download_serial', 'download_multithread'])
def test_check_cache_one_mismatch_among_many_changes_nothing(
    download: str, fake_get: list[str], tmp_path: Path
) -> None:
    """One moved file among cached and missing ones raises one error listing only it, before any request."""
    pairs = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['tas', 'pr'], FIXTURE_LAT, FIXTURE_LON, '2023-01-01', '2023-02-28', 'fixture'
    )
    _seed_cache(tmp_path, pairs)
    # the fixtures cache only January, and its pr file was made for another point
    moved = tmp_path / 'fixture_AUS-11_1hr_pr_20230101_20230131.csv'
    moved.write_text(moved.read_text().replace('GridPointRequestedAt[23.550S', 'GridPointRequestedAt[24.550S'))
    before = _snapshot(tmp_path)

    with pytest.raises(barra2_dl.download.CacheMismatchError) as error:
        getattr(barra2_dl.download, download)(pairs, tmp_path)

    assert [name for name, _ in error.value.problems] == [moved.name]
    assert fake_get == []
    assert _snapshot(tmp_path) == before


def test_check_cache_fixed_field_is_checked_like_a_point(fake_get: list[str], tmp_path: Path) -> None:
    """The fixed orog file, which has one row, is checked against the requested point too."""
    pairs = _point_pairs(FIXTURE_LAT - 0.1, FIXTURE_LON)
    (tmp_path / 'fixture_AUS-11_fx_orog.csv').write_bytes((DATA_DIR / 'fixture_AUS-11_fx_orog.csv').read_bytes())

    with pytest.raises(barra2_dl.download.CacheMismatchError) as error:
        barra2_dl.download.download_serial(pairs, tmp_path)

    assert [name for name, _ in error.value.problems] == ['fixture_AUS-11_fx_orog.csv']


def test_check_cache_url_without_location_is_not_checked(fake_get: list[str], tmp_path: Path) -> None:
    """Urls that aren't BARRA2 requests keep today's behaviour: an existing file is skipped unread."""
    (tmp_path / 'a.csv').write_bytes(b'')

    barra2_dl.download.download_serial([('https://example.test/a', 'a.csv')], tmp_path)

    assert fake_get == []


# endregion


# region _cached_file_problem
POINT_URL = 'https://example.test/x?latitude={lat}&longitude={lon}&accept={accept}'


@pytest.mark.parametrize(
    ('station', 'lat', 'lon', 'expected'),
    [
        ('GridPointRequestedAt[33.880S_151.180E]', -33.88, 151.18, None),
        ('GridPointRequestedAt[33.880N_151.180W]', 33.88, -151.18, None),
        (
            'GridPointRequestedAt[33.880N_151.180W]',
            -33.88,
            151.18,
            'holds 33.880, -151.180; requested -33.880, 151.180',
        ),
        # AUS-11 reaches 207.39 E: the request may give it either way
        ('GridPointRequestedAt[23.550S_207.390E]', -23.55, 207.39, None),
        ('GridPointRequestedAt[23.550S_207.390E]', -23.55, -152.61, None),
        ('GridPointRequestedAt[23.550S_207.390E]', -23.55, 27.39, 'holds -23.550, 207.390; requested -23.550, 27.390'),
    ],
)
def test_cached_file_problem_station_hemispheres_and_longitude_wrap(
    station: str, lat: float, lon: float, expected: str | None, tmp_path: Path
) -> None:
    """The station value is parsed with south and west negative, and longitudes compared on -180 to 180."""
    path = tmp_path / 'a.csv'
    path.write_text(f'time,station,latitude,longitude,tas\n2023-01-01T00:00:00Z,{station},0,0,1\n')

    assert (
        barra2_dl.download._cached_file_problem(path, POINT_URL.format(lat=lat, lon=lon, accept='csv_file')) == expected
    )


@pytest.mark.parametrize(
    ('name', 'content', 'accept'),
    [
        ('empty.csv', b'', 'csv_file'),
        ('column_row_only.csv', b'time,station,latitude,longitude,tas\n', 'csv_file'),
        ('no_station_column.csv', b'time,latitude\n2023-01-01T00:00:00Z,-23.54\n', 'csv_file'),
        ('no_location.csv', b'time,station\n2023-01-01T00:00:00Z,somewhere\n', 'csv_file'),
        ('not_netcdf.nc', b'not netcdf', 'netcdf4'),
    ],
)
def test_cached_file_problem_unreadable_file(name: str, content: bytes, accept: str, tmp_path: Path) -> None:
    """An empty file, a csv without a data row or location, or a non-netCDF file can't be read."""
    path = tmp_path / name
    path.write_bytes(content)

    problem = barra2_dl.download._cached_file_problem(path, POINT_URL.format(lat=-23.55, lon=133.4, accept=accept))

    assert problem == "can't be read"


@live_network
@pytest.mark.parametrize('fileout_type', ['csv_file', 'netcdf4'])
@pytest.mark.parametrize('lon', [133.40, 190.0])
def test_cached_file_problem_live_station_format(fileout_type: str, lon: float, tmp_path: Path) -> None:
    """The server's GridPointRequestedAt format still parses, including a longitude above 180."""
    ((url, name),) = _point_pairs(-23.55, lon, fileout_type)[-1:]  # the fixed orog request: one small file
    tmp_path.mkdir(exist_ok=True)
    barra2_dl.download.download_serial([(url, name)], tmp_path)

    assert (tmp_path / name).exists()
    assert barra2_dl.download._cached_file_problem(tmp_path / name, url) is None


def test_cached_file_problem_netcdf_without_expected_variable(tmp_path: Path) -> None:
    """A netCDF file without station_description can't be read as a point."""
    path = tmp_path / 'a.nc'
    xr.Dataset({'tas': ('time', [1.0, 2.0])}).to_netcdf(path)

    problem = barra2_dl.download._cached_file_problem(path, POINT_URL.format(lat=-23.55, lon=133.4, accept='netcdf4'))

    assert problem == "can't be read"


def test_cached_file_problem_grid_without_axes(tmp_path: Path) -> None:
    """A netCDF grid without lat and lon axes can't be read."""
    path = tmp_path / 'grid_AUS-11_1hr_average4_tas.nc'
    xr.Dataset({'tas': ('time', [1.0, 2.0])}).to_netcdf(path)
    url = 'https://example.test/x?north=1&south=0&east=1&west=0'

    assert barra2_dl.download._cached_file_problem(path, url) == "can't be read"


# endregion
# endregion
