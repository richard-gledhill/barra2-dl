"""This module contains the barra2.download test function(s)."""

import os
from datetime import datetime

import pytest
from pandas import Timestamp

import barra2_dl.download
import barra2_dl.globals
from barra2_dl.globals import (
    BARRA2_URL_AUS11_1HR,
    BARRA2_URL_AUST04_1HR,
    BARRA2_VAR_WIND_50,
)
from barra2_dl.mapping import LatLonPoint


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


def test_point_data_urlfilenames_mid_month_start() -> None:
    """A mid-month start date still downloads the file for the start month."""
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        BARRA2_URL_AUS11_1HR,
        ['ua50m'],
        -23.5527472,
        133.3961111,
        datetime(2023, 1, 15),
        datetime(2023, 2, 10),
        'demo',
    )
    assert [filename for _, filename in urlfilenames] == [
        'demo_ua50m_20230101_20230131.csv',
        'demo_ua50m_20230201_20230228.csv',
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
            BARRA2_URL_AUS11_1HR,
            BARRA2_VAR_WIND_50,
            LatLonPoint(-23.5527472, 133.3961111).lat,
            LatLonPoint(-23.5527472, 133.3961111).lon,
            datetime.strptime('2023-01-01T00:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            datetime.strptime('2023-03-31T23:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            'demo',
            [
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ua50m/latest/ua50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202301-202301.nc?var=ua50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-01-01T00:00:00Z&time_end=2023-01-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_ua50m_20230101_20230131.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ua50m/latest/ua50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202302-202302.nc?var=ua50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-02-01T00:00:00Z&time_end=2023-02-28T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_ua50m_20230201_20230228.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ua50m/latest/ua50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202303-202303.nc?var=ua50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-03-01T00:00:00Z&time_end=2023-03-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_ua50m_20230301_20230331.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/va50m/latest/va50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202301-202301.nc?var=va50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-01-01T00:00:00Z&time_end=2023-01-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_va50m_20230101_20230131.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/va50m/latest/va50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202302-202302.nc?var=va50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-02-01T00:00:00Z&time_end=2023-02-28T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_va50m_20230201_20230228.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/va50m/latest/va50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202303-202303.nc?var=va50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-03-01T00:00:00Z&time_end=2023-03-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_va50m_20230301_20230331.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ta50m/latest/ta50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202301-202301.nc?var=ta50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-01-01T00:00:00Z&time_end=2023-01-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_ta50m_20230101_20230131.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ta50m/latest/ta50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202302-202302.nc?var=ta50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-02-01T00:00:00Z&time_end=2023-02-28T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_ta50m_20230201_20230228.csv',
                ),
                (
                    'https://thredds.nci.org.au/thredds/ncss/grid/ob53/output/reanalysis/AUS-11/BOM/ERA5/historical/hres/BARRA-R2/v1/1hr/ta50m/latest/ta50m_AUS-11_ERA5_historical_hres_BOM_BARRA-R2_v1_1hr_202303-202303.nc?var=ta50m&latitude=-23.5527472&longitude=133.3961111&time_start=2023-03-01T00:00:00Z&time_end=2023-03-31T23:00:00Z&timeStride=&vertCoord=&accept=csv_file',
                    'demo_ta50m_20230301_20230331.csv',
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


@pytest.mark.parametrize(
    (
        'barra2_url',
        'barra2_vars',
        'latitude',
        'longitude',
        'start_datetime',
        'end_datetime',
        'fileout_prefix',
    ),
    [
        (
            BARRA2_URL_AUS11_1HR,
            BARRA2_VAR_WIND_50,
            LatLonPoint(-23.5527472, 133.3961111).lat,
            LatLonPoint(-23.5527472, 133.3961111).lon,
            datetime.strptime('2023-01-01T00:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            datetime.strptime('2023-03-31T23:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            'barra2_aus11_1hr',
        ),
        (
            BARRA2_URL_AUST04_1HR,
            BARRA2_VAR_WIND_50,
            LatLonPoint(-23.5527472, 133.3961111).lat,
            LatLonPoint(-23.5527472, 133.3961111).lon,
            datetime.strptime('2023-01-01T00:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            datetime.strptime('2023-03-31T23:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            'barra2_aust04_1hr',
        ),
    ],
)
def test_download_serial(
    barra2_url, barra2_vars, latitude, longitude, start_datetime, end_datetime, fileout_prefix, tmp_path
) -> None:
    """Test with parametrization."""
    download_folder = tmp_path / 'cache'
    download_folder.mkdir()
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        barra2_url,
        barra2_vars,
        latitude,
        longitude,
        start_datetime,
        end_datetime,
        fileout_prefix,
    )

    barra2_dl.download.download_serial(urlfilenames, download_folder)

    for item in [item[1] for item in urlfilenames]:
        filename = download_folder / os.path.basename(item)
        assert filename.exists()


@pytest.mark.parametrize(
    (
        'barra2_url',
        'barra2_vars',
        'latitude',
        'longitude',
        'start_datetime',
        'end_datetime',
        'fileout_prefix',
    ),
    [
        (
            BARRA2_URL_AUS11_1HR,
            BARRA2_VAR_WIND_50,
            LatLonPoint(-23.5527472, 133.3961111).lat,
            LatLonPoint(-23.5527472, 133.3961111).lon,
            datetime.strptime('2023-01-01T00:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            datetime.strptime('2023-03-31T23:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            'barra2_aus11_1hr',
        ),
        (
            BARRA2_URL_AUST04_1HR,
            BARRA2_VAR_WIND_50,
            LatLonPoint(-23.5527472, 133.3961111).lat,
            LatLonPoint(-23.5527472, 133.3961111).lon,
            datetime.strptime('2023-01-01T00:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            datetime.strptime('2023-03-31T23:00:00Z', '%Y-%m-%dT%H:%M:%SZ'),
            'barra2_aust04_1hr',
        ),
    ],
)
def test_download_multithread(
    barra2_url, barra2_vars, latitude, longitude, start_datetime, end_datetime, fileout_prefix, tmp_path
) -> None:
    """Test with parametrization."""
    download_folder = tmp_path / 'cache'
    download_folder.mkdir()
    urlfilenames = barra2_dl.download.point_data_urlfilenames(
        barra2_url,
        barra2_vars,
        latitude,
        longitude,
        start_datetime,
        end_datetime,
        fileout_prefix,
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
