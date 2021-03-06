"""Tests for MobileAlerts Sensor class."""
from typing import List

import pytest

from mobilealerts import Sensor


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (
            "E0618FBA0D241829EFCB988D403D1300FC26282100FC2628210203030404040101010101014000000000000000000000000000000000000000000000000000",
            "id: 1829EFCB988D (battery good, last event: 2021-11-13 13:13:49)\n"
            "Temperature: 25.2°C; previous: 25.2°C\n"
            "Humidity: 38%; previous: 38%\n"
            "Air pressure: 1027.3 hPa; previous: 1027.3 hPa",
        ),
        (
            "CE618FBA69120215C1B2E3EF3697003300351A2F00C813AA0A2F1A020202020102020203064000000000000000000000000000000000000000000000000000",
            "id: 0215C1B2E3EF (battery good, last seen: 2021-11-13 13:15:21)\n"
            "Temperature: 5.1°C; previous: 5.3°C",
        ),
        (
            "D2618FBA9116036ADF5B1C8A1BBE00C40A3000C40A301A00000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "id: 036ADF5B1C8A (battery good, last seen: 2021-11-13 13:16:01)\n"
            "Temperature: 19.6°C; previous: 19.6°C\n"
            "Humidity: 48%; previous: 48%",
        ),
        (
            "D6618FBBFE1A065526A17A61342A00C813AA0A2F00C913AA0A2F1A000000000000000000000000000000000000000000000000000000000000000000000000",
            "id: 065526A17A61 (battery good, last seen: 2021-11-13 13:22:06)\n"
            "Temperature: 20.0°C; previous: 20.1°C\n"
            "Humidity: 47%; previous: 47%\n"
            "Pool temperature: error; previous: error",
        ),
        (
            "E161950AB225083F2CAA2B4203FF400900E095189BAD83E58C6AC515C3F3D642C41EC607C2AC00000000000000000000000000000000000000000000000000",
            "id: 083F2CAA2B42 (battery good, last seen: 2021-11-17 13:59:14)\n"
            "Temperature: 0.9°C\n"
            "Rain: 56.0 mm\n"
            "Time span: 3 days, 18:00:00; previous: [4 days, 22:05:00; 16:37:00; 2 days, 4:58:00]",
        ),
    ],
)
def test_sensor(data: str, expected: str) -> None:
    """Example test with parametrization."""
    _data = bytes.fromhex(data)
    sensor = Sensor(None, _data[6:12].hex().upper())
    sensor.last_update = _data
    assert sensor.str_utc() == expected
