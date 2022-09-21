"""Tests for MobileAlerts Gateway class."""
from types import coroutine
from typing import List, Optional

import asyncio

import pytest

from mobilealerts import Gateway, Sensor, SensorHandler

_sensor: Optional[Sensor] = None


class SensorDiscoveredHandler(SensorHandler):
    async def sensor_added(self, sensor: Sensor) -> None:
        assert (sensor is not None) and (sensor.sensor_id == "1829EFCB988D")


def test_sensor_discovered() -> None:
    global _sensor
    _sensor = None
    my_loop = asyncio.new_event_loop()
    try:
        gateway: Gateway = Gateway("001D8C0EA927")
        gateway.set_handler(SensorDiscoveredHandler())
        my_loop.run_until_complete(
            gateway.handle_update(
                "C0",
                bytes.fromhex(
                    "E0618FBA0D241829EFCB988D"
                    "403D1300FC26282100FC2628210203030404040101010101014"
                    "0000000000000000000000000000000000000000000000000001B"
                ),
            )
        )

    finally:
        my_loop.close()


class SensorAddedHandler(SensorHandler):
    async def sensor_updated(self, sensor: Sensor) -> None:
        global _sensor
        assert _sensor == sensor


def test_sensor_added() -> None:
    global _sensor
    my_loop = asyncio.new_event_loop()
    try:
        gateway: Gateway = Gateway("001D8C0EA927")
        _sensor = Sensor(gateway, "1829EFCB988D")
        gateway.add_sensor(_sensor)
        gateway.set_handler(SensorAddedHandler())
        my_loop.run_until_complete(
            gateway.handle_update(
                "C0",
                bytes.fromhex(
                    "E0618FBA0D241829EFCB988D"
                    "403D1300FC26282100FC2628210203030404040101010101014"
                    "0000000000000000000000000000000000000000000000000001B"
                ),
            )
        )
    finally:
        my_loop.close()


if __name__ == "__main__":
    test_sensor_discovered()
    test_sensor_added()
