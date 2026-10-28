"""This module contains the barra2.download test function(s)."""

import io
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
import requests
from pandas import Timestamp

import barra2_dl.download
import barra2_dl.globals
from barra2_dl.globals import (
    BARRA2_FREQS,
    BARRA2_URL,
    BARRA2_URL_AUS11_1HR,
    BARRA2_URL_AUST04_1HR,
    BARRA2_VAR_WIND_50,
    BARRA2_VAR_WIND_DEFAULT,
    BARRA2_WIND_VARS,
)
from barra2_dl.mapping import LatLonPoint

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


@pytest.fixture
def fake_get(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace requests.get with a recorder returning a 200 response; the list collects requested URLs."""
    requested: list[str] = []

    def _get(url: str, **_kwargs) -> _FakeResponse:
        requested.append(url)
        return _FakeResponse()

    monkeypatch.setattr(barra2_dl.download.requests, 'get', _get)
    return requested


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
    """Only csv_file output is supported."""
    with pytest.raises(ValueError, match='not supported'):
        barra2_dl.download.point_data_urlfilenames(
            BARRA2_URL, ['ua50m'], -23.5, 133.4, '2023-01-01', '2023-01-31', 'demo', fileout_type='netcdf'
        )


def test_point_data_urlfilenames_leap_february() -> None:
    """February in a leap year runs to the 29th."""
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL, ['ua50m'], -23.5, 133.4, '2024-02-01', '2024-02-29', 'demo'
    )

    assert [name for _, name in urlfilenames] == ['demo_AUS-11_1hr_ua50m_20240201_20240229.csv']
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
        )
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


@pytest.mark.parametrize('cpus', [1, 2, 8])
def test_download_multithread_pool_size(cpus: int, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Downloads every file whatever the cpu count, including a single-cpu machine."""
    downloaded: list[tuple[str, str, str]] = []

    def fake_download_file(url: str, file_name: str, folder_path) -> None:
        downloaded.append((url, file_name, str(folder_path)))

    monkeypatch.setattr(barra2_dl.download, 'cpu_count', lambda: cpus)
    monkeypatch.setattr(barra2_dl.download, '_download_file', fake_download_file)
    urlfilenames = [(f'https://example.test/{i}', f'file_{i}.csv') for i in range(5)]

    barra2_dl.download.download_multithread(urlfilenames, tmp_path)

    assert sorted(downloaded) == sorted((url, name, str(tmp_path)) for url, name in urlfilenames)


def test_download_multithread_offline(fake_get: list[str], tmp_path: Path) -> None:
    """Every pair is fetched and saved in parallel, without touching the network."""
    urlfilenames = [(f'https://example.test/{i}', f'file_{i}.csv') for i in range(5)]

    barra2_dl.download.download_multithread(urlfilenames, tmp_path)

    assert sorted(fake_get) == sorted(url for url, _ in urlfilenames)
    assert len(list(tmp_path.iterdir())) == 5


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


def test_download_file_missing_folder(fake_get: list[str], tmp_path: Path) -> None:
    """A missing folder raises before any request is made."""
    with pytest.raises(FileNotFoundError):
        barra2_dl.download._download_file('https://example.test/a', 'a.csv', tmp_path / 'missing')

    assert fake_get == []


# endregion
# endregion
