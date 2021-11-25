"""MobileAlerts sensors."""

from typing import Any, List, Optional, Union

import datetime
import logging
import time
from enum import IntEnum, auto

_LOGGER = logging.getLogger(__name__)


class MeasurementType(IntEnum):
    """Types of measurments."""

    TEMPERATURE = auto()
    HUMIDITY = auto()
    WETNESS = auto()
    AIR_QUALITY = auto()
    AIR_PRESSURE = auto()
    RAIN = auto()
    TIME_SPAN = auto()
    ALARM = auto()
    WIND_SPEED = auto()
    GUST = auto()
    WIND_DIRECTION = auto()
    DOOR_WINDOW = auto()
    KEY_PRESSED = auto()
    KEY_PRESS_TYPE = auto()


MEASUREMENT_TYPES = [
    "Temperature",
    "Humidity",
    "Wetness",
    "Air quality",
    "Air pressure",
    "Rain",
    "Time span",
    "Alarm",
    "Wind speed",
    "Gust",
    "Wind direction",
    "Door/Window",
    "Key pressed",
    "Key press type",
]


class MeasurementError(IntEnum):
    """Measurment errors."""

    ERROR = auto()
    OVERFLOW = auto()
    NOT_CALCULATED = auto()


MEASUREMENT_ERRORS = [
    "error",
    "overflow",
    "not calculcated",
]


class WindDirection(IntEnum):
    """Directions of wind."""

    N = 0
    NNE = 1
    NE = 2
    ENE = 3
    E = 4
    ESE = 5
    SE = 6
    SSE = 7
    S = 8
    SSW = 9
    SW = 10
    WSW = 11
    W = 12
    WNW = 13
    NW = 14
    NNW = 15


WIND_DIRECTIONS = [
    "North",
    "North-northeast",
    "Northeast",
    "East-northeast",
    "East",
    "East-southeast",
    "Southeast",
    "South-Southeast",
    "South",
    "South-southwest",
    "Southwest",
    "West-southwest",
    "West",
    "West-northwest",
    "Northwest",
    "Northnorthwest",
]


def _parse_temperature(
    value: bytes,
    attr: bool,
) -> Union[float, MeasurementError]:
    if len(value) != 2:
        raise ValueError("Invalid temperature value")
    result: int = int.from_bytes(value, "big")
    if attr:
        if result & (1 << 12) != 0:
            return MeasurementError.ERROR
        if result & (1 << 13) != 0:
            return MeasurementError.OVERFLOW
    negative = result & (1 << 10) != 0
    result &= 0x3FF
    if negative:
        result -= 1024
    return result * 0.1


def _parse_humidity(
    value: int,
    average: bool = False,
) -> Union[float, MeasurementError]:
    if average and value & 0x80 != 0:
        return MeasurementError.NOT_CALCULATED
    return value & 0x7F


def _parse_humidity_hr(
    value: bytes,
) -> float:
    if len(value) != 2:
        raise ValueError("Invalid air humidity value")
    result: int = int.from_bytes(value, "big")
    return (result & 0x1FF) / 10


def _parse_air_preasure(
    value: bytes,
) -> float:
    if len(value) != 2:
        raise ValueError("Invalid air preasure value")
    result: int = int.from_bytes(value, "big")
    return result / 10


def _parse_rain_time_span(value: int) -> int:
    time_unit = (value & 0xC000) >> 14
    if time_unit == 1:  # hours
        time_mult = 60 * 60
    elif time_unit == 2:  # minutes
        time_mult = 60
    else:  # seconds
        time_mult = 1
    return (value & 0x3FFF) * time_mult


def _parse_wind_direction(value: int) -> int:
    return WindDirection((value & 0xF0000000) >> 28)


def _parse_wind_speed(
    value: int,
    hibit: int,
    himask: int,
) -> float:
    return ((value & 0xFF) & (0x100 if (hibit & himask != 0) else 0)) / 10


def _parse_wind_time_span(value: int) -> int:
    return (value & 0xFF) * 2


def _parse_door_window_time_span(value: int) -> int:
    time_unit = (value & 0x6000) >> 13
    if time_unit == 1:  # hours
        time_mult = 60 * 60
    elif time_unit == 2:  # minutes
        time_mult = 60
    else:  # seconds
        time_mult = 1
    return (value & 0x1FFF) * time_mult


class Measurement:
    """Hold value of one measurment done by the sensor."""

    def __init__(
        self,
        parent: "Sensor",
        type: MeasurementType,
        prefix: str = "",
        index: int = 0,
    ) -> None:
        """Create a new instance of the Measurement."""
        self._parent = parent
        self._type = type
        self._prefix = prefix
        self._index = index
        self._value: Any = None
        self._prior: Any = None

    @property
    def parent(self) -> "Sensor":
        return self._parent

    @property
    def type(self) -> MeasurementType:
        return self._type

    @property
    def name(self) -> str:
        name: str = MEASUREMENT_TYPES[int(self._type) - 1]
        return ((self._prefix + " " + name.lower()) if self._prefix else name) + (
            (" " + str(self._index)) if self._index > 0 else ""
        )

    @property
    def value(self):
        return self._value

    @property
    def has_prior_value(self) -> bool:
        return self._prior is not None

    @property
    def prior_value(self):
        return self._prior

    def __repr__(self) -> str:
        """Return a formal representation of the measurement."""
        return (
            "%s.%s, "
            "type=%s, "
            'prefix="%s", '
            "index=%s, "
            "value=%r, "
            "prior_value=%r)"
        ) % (
            self.__class__.__module__,
            self.__class__.__qualname__,
            self._type,
            self._prefix,
            self._index,
            self._value,
            self._prior,
        )

    def unit(self) -> Union[str, List[str]]:
        if self._type == MeasurementType.TEMPERATURE:
            return "°C"
        elif self._type == MeasurementType.HUMIDITY:
            return "%"
        elif self._type == MeasurementType.WETNESS:
            return ["dry", "wet"]
        elif self._type == MeasurementType.AIR_QUALITY:
            return "ppm"
        elif self._type == MeasurementType.AIR_PRESSURE:
            return "hPa"
        elif self._type == MeasurementType.RAIN:
            return "mm"
        elif self._type == MeasurementType.TIME_SPAN:
            return "s"
        elif self._type == MeasurementType.ALARM:
            return ["calm", "alarm"]
        elif (
            self._type == MeasurementType.WIND_SPEED
            or self._type == MeasurementType.GUST
        ):
            return "m/s"
        elif self._type == MeasurementType.WIND_DIRECTION:
            return WIND_DIRECTIONS
        elif self._type == MeasurementType.DOOR_WINDOW:
            return ["closed", "opened"]
        elif self._type == MeasurementType.KEY_PRESSED:
            return ["none", "green", "orange", "red", "yellow"]
        elif self._type == MeasurementType.KEY_PRESS_TYPE:
            return ["none", "short", "double", "long"]
        else:
            return ""

    def _value_to_str(self, value: Any) -> str:
        if value is None:
            return "unknown"
        elif type(value) is MeasurementError:
            return MEASUREMENT_ERRORS[int(value) - 1]
        elif self._type in [
            MeasurementType.TEMPERATURE,
            MeasurementType.HUMIDITY,
        ]:
            return str(round(value, 1)) + str(self.unit())
        elif self._type in [
            MeasurementType.RAIN,
            MeasurementType.AIR_PRESSURE,
            MeasurementType.AIR_QUALITY,
            MeasurementType.WIND_SPEED,
            MeasurementType.GUST,
        ]:
            return str(round(value, 1)) + " " + str(self.unit())
        elif self._type == MeasurementType.TIME_SPAN:
            return str(datetime.timedelta(seconds=value))
        elif self._type in [
            MeasurementType.WETNESS,
            MeasurementType.ALARM,
            MeasurementType.WIND_DIRECTION,
            MeasurementType.DOOR_WINDOW,
            MeasurementType.KEY_PRESSED,
            MeasurementType.KEY_PRESS_TYPE,
        ]:
            return self.unit()[int(value)]
        else:
            return "unknown"

    @property
    def value_str(self) -> str:
        return self._value_to_str(self._value)

    @property
    def prior_value_str(self) -> str:
        if self._prior is not None and hasattr(self._prior, "__len__"):
            result: str = "["
            i: int = 0
            l: int = len(self._prior)
            while True:
                result += self._value_to_str(self._prior[i])
                i += 1
                if i < l:
                    result += "; "
                else:
                    break
            return result + "]"
        else:
            return self._value_to_str(self._prior)

    def __str__(self) -> str:
        """Return a readable representation of the measurement."""
        result: str = ("%s: %s") % (self.name, self.value_str)
        if self.has_prior_value:
            result += ("; previous: %s") % (self.prior_value_str)
        return result

    def _set_temperature(
        self,
        value: bytes,
        prior: Optional[bytes] = None,
        attr: bool = True,
    ) -> None:
        self._value = _parse_temperature(value, attr)
        if prior is None:
            self._prior = None
        else:
            self._prior = _parse_temperature(prior, attr)

    def _add_prior_temperature(self, value: bytes) -> None:
        if self._prior is None:
            self._prior = []
        else:
            self._prior = [self._prior]
        self._prior.append(_parse_temperature(value, True))

    def _set_humidity(
        self,
        value: int,
        prior: Optional[int] = None,
        average: bool = False,
    ) -> None:
        self._value = _parse_humidity(value, average)
        if prior is None:
            self._prior = None
        else:
            self._prior = _parse_humidity(prior, average)

    def _set_humidity_hr(
        self,
        value: bytes,
        prior1: bytes,
        prior2: bytes,
    ) -> None:
        self._value = _parse_humidity_hr(value)
        self._prior = [_parse_humidity_hr(prior1), _parse_humidity_hr(prior2)]

    def _set_wetness(
        self,
        value: int,
    ) -> None:
        self._value = ((value & 0x02) != 0) or ((value & 0x01) == 0)

    def _set_air_quality(
        self,
        value: bytes,
    ) -> None:
        if len(value) != 2:
            raise ValueError("Invalid air quality value")
        result: int = int.from_bytes(value, "big")
        if result & 0x100 != 0:
            self._value = MeasurementError.OVERFLOW
        else:
            self._value = (result & 0xFF) * 50

    def _set_air_preasure(
        self,
        value: bytes,
        prior: Optional[bytes] = None,
    ) -> None:
        self._value = _parse_air_preasure(value)
        if prior is None:
            self._prior = None
        else:
            self._prior = _parse_air_preasure(prior)

    def _set_rain(
        self,
        value: bytes,
    ) -> None:
        if len(value) != 2:
            raise ValueError("Invalid rain level value")
        result: int = int.from_bytes(value, "big")
        self._value = result * 0.25

    def _set_rain_time_span(
        self,
        values: bytes,
    ) -> None:
        if len(values) < 2:
            raise ValueError("Invalid timespan value")
        value = int.from_bytes(values[0:2], "big")
        self._value = _parse_rain_time_span(value)
        self._prior = None
        if len(values) > 2:
            index = 4
            while index < len(values):
                value = int.from_bytes(values[index - 2 : index], "big")
                if value == 0:
                    break
                value = _parse_rain_time_span(value)
                if value == 0:
                    break
                if self._prior is None:
                    self._prior = []
                self._prior.append(value)
                index += 2

    def _set_boolean(
        self,
        value: bytes,
        bitmask: int,
    ) -> None:
        if len(value) != 2:
            raise ValueError("Invalid value")
        result = int.from_bytes(value, "big")
        self._value = result & bitmask != 0

    def _add_wind_direction(
        self,
        index: int,
        value: int,
    ) -> None:
        if index == 0:
            self._value = _parse_wind_direction(value)
            self._prior = []
        else:
            self._prior.append(_parse_wind_direction(value))

    def _add_wind_speed(
        self,
        index: int,
        value: int,
        hibit: int,
        himask: int,
    ) -> None:
        if index == 0:
            self._value = _parse_wind_speed(value, hibit, himask)
            self._prior = []
        else:
            self._prior.append(_parse_wind_speed(value, hibit, himask))

    def _add_wind_time_span(
        self,
        index: int,
        value: int,
    ) -> None:
        if index == 0:
            self._value = _parse_wind_time_span(value)
            self._prior = []
        else:
            self._prior.append(_parse_wind_time_span(value))

    def _set_door_window_time_span(
        self,
        values: bytes,
    ) -> None:
        if len(values) < 2:
            raise ValueError("Invalid timespan value")
        value = int.from_bytes(values[0:2], "big")
        self._value = _parse_door_window_time_span(value)
        self._prior = None
        if len(values) > 2:
            index = 4
            while index < len(values):
                value = int.from_bytes(values[index - 2 : index], "big")
                if value == 0:
                    break
                value = _parse_door_window_time_span(value)
                if value == 0:
                    break
                if self._prior is None:
                    self._prior = []
                self._prior.append(value)
                index += 2

    def _set_key_pressed(
        self,
        value: int,
    ) -> None:
        self._value = value & 0xF0 >> 4

    def _set_key_press_type(
        self,
        value: int,
    ) -> None:
        self._value = value & 0xF


class Sensor:
    """Receive data from Mobile Alerts/WeatherHub sensor."""

    def __init__(self, parent: Any, sensor_id: str) -> None:
        self._id = sensor_id
        self._type_id = int(sensor_id[0:2], 16)

        self._parent = parent

        self._counter = -1
        self._low_battery = False
        self._by_event = False
        self._timestamp = time.time()
        self._last_update: Optional[bytes] = None

        self._measurements: List[Measurement] = []

        self._three_byte_counter = False
        if self._type_id == 0x01 or self._type_id == 0x0F:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.TEMPERATURE, "Cable")
        elif self._type_id == 0x02:
            self._append(MeasurementType.TEMPERATURE)
        elif self._type_id == 0x03 or self._type_id == 0x0E:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.HUMIDITY)
        elif self._type_id == 0x04:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.HUMIDITY)
            self._append(MeasurementType.WETNESS)
        elif self._type_id == 0x05:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.HUMIDITY)
            self._append(MeasurementType.AIR_QUALITY)
            self._append(MeasurementType.TEMPERATURE, "Outdoor")
        elif self._type_id == 0x06:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.HUMIDITY)
            self._append(MeasurementType.TEMPERATURE, "Pool")
        elif self._type_id == 0x07:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.HUMIDITY)
            self._append(MeasurementType.TEMPERATURE, "Outdoor")
            self._append(MeasurementType.HUMIDITY, "Outdoor")
        elif self._type_id == 0x08:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.RAIN)
            self._append(MeasurementType.TIME_SPAN)
        elif self._type_id == 0x09:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.HUMIDITY)
            self._append(MeasurementType.TEMPERATURE, "External")
        elif self._type_id == 0x0A:
            self._append(MeasurementType.ALARM, "", 1)
            self._append(MeasurementType.ALARM, "", 2)
            self._append(MeasurementType.ALARM, "", 3)
            self._append(MeasurementType.ALARM, "", 4)
            self._append(MeasurementType.TEMPERATURE)
        elif self._type_id == 0x0B:
            self._three_byte_counter = True
            self._append(MeasurementType.WIND_DIRECTION)
            self._append(MeasurementType.WIND_SPEED)
            self._append(MeasurementType.GUST)
            self._append(MeasurementType.TIME_SPAN)
        elif self._type_id == 0x10:
            self._append(MeasurementType.DOOR_WINDOW)
            self._append(MeasurementType.TIME_SPAN)
        elif self._type_id == 0x11:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.HUMIDITY)
            self._append(MeasurementType.TEMPERATURE, "External", 1)
            self._append(MeasurementType.HUMIDITY, "External", 1)
            self._append(MeasurementType.TEMPERATURE, "External", 2)
            self._append(MeasurementType.HUMIDITY, "External", 2)
            self._append(MeasurementType.TEMPERATURE, "External", 3)
            self._append(MeasurementType.HUMIDITY, "External", 3)
        elif self._type_id == 0x12:
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.HUMIDITY)
            self._append(MeasurementType.HUMIDITY, "3h average")
            self._append(MeasurementType.HUMIDITY, "24h average")
            self._append(MeasurementType.HUMIDITY, "7d average")
            self._append(MeasurementType.HUMIDITY, "30d average")
        elif self._type_id == 0x15:
            self._append(MeasurementType.KEY_PRESSED)
            self._append(MeasurementType.KEY_PRESS_TYPE)
        elif self._type_id == 0x18:
            self._three_byte_counter = True
            self._append(MeasurementType.TEMPERATURE)
            self._append(MeasurementType.HUMIDITY)
            self._append(MeasurementType.AIR_PRESSURE)
        else:
            _LOGGER.error("Unknow sensor type: %s", self._type_id)

    def __len__(self) -> int:
        return len(self._measurements)

    def __getitem__(self, key: int) -> Measurement:
        return self._measurements[key]

    def __repr__(self) -> str:
        """Return a formal representation of the sensor."""
        result: str = (
            "%s.%s(%s), "
            "counter = %s, "
            "low_battery = %s, "
            "by_event = %s, "
            "timestamp = %s,"
            "last_update = %s"
        ) % (
            self.__class__.__module__,
            self.__class__.__qualname__,
            self._id,
            self._counter,
            self._low_battery,
            self._by_event,
            time.ctime(self._timestamp),
            self._last_update.hex().upper() if self._last_update is not None else None,
        )
        first = True
        for measurement in self._measurements:
            result += (", measurements: %r" if first else ", %r") % (measurement)
            first = False
        return result

    def __str__(self) -> str:
        """Return a readable representation of the sensor."""
        result: str = ("id: %s (battery %s, last %s: %s)") % (
            self._id,
            "low" if self._low_battery else "good",
            "event" if self._by_event else "seen",
            time.ctime(self._timestamp),
        )
        for measurement in self._measurements:
            result += "\n" + str(measurement)
        return result

    def str_utc(self) -> str:
        """Return a readable representation of the sensor. Timestamp is formatted as UTC datetime"""
        timestamp_struct: time.struct_time = time.gmtime(self._timestamp)

        result: str = ("id: %s (battery %s, last %s: %s)") % (
            self._id,
            "low" if self._low_battery else "good",
            "event" if self._by_event else "seen",
            time.strftime("%Y-%m-%d %H:%M:%S", timestamp_struct),
        )
        for measurement in self._measurements:
            result += "\n" + str(measurement)
        return result

    def _append(
        self,
        type: MeasurementType,
        prefix: str = "",
        index: int = 0,
    ) -> None:
        self._measurements.append(Measurement(self, type, prefix, index))

    def _parse_packet_header(self, packet: bytes) -> bool:
        self._timestamp = int.from_bytes(packet[1:5], "big")
        if self._three_byte_counter:
            counter = int.from_bytes(packet[12:15], "big")
            self._low_battery = (counter & 0x800000) != 0
            self._by_event = (counter & 0x400000) != 0
            counter &= 0x3FFFFF
        else:
            counter = int.from_bytes(packet[12:14], "big")
            self._low_battery = (counter & 0x8000) != 0
            self._by_event = (counter & 0x4000) != 0
            counter &= 0x3FFF

        result = self._counter != counter
        if result:
            self._counter = counter

        return result

    def parse_packet(self, packet: bytes) -> None:
        if not self._parse_packet_header(packet):
            return
        if self._type_id == 0x01 or self._type_id == 0x0F:
            self[0]._set_temperature(packet[14:16], packet[18:20])
            self[1]._set_temperature(packet[16:18], packet[20:22])
        elif self._type_id == 0x02:
            self[0]._set_temperature(packet[14:16], packet[16:18])
        elif self._type_id == 0x03:
            self[0]._set_temperature(packet[14:16], packet[18:20])
            self[1]._set_humidity(packet[17], packet[21])
        elif self._type_id == 0x04:
            self[0]._set_temperature(packet[14:16], packet[19:21])
            self[1]._set_humidity(packet[17], packet[23])
            self[2]._set_wetness(packet[18])
        elif self._type_id == 0x05:
            self[0]._set_temperature(packet[16:18], packet[24:26])
            self[1]._set_humidity(packet[19], packet[27])
            self[2]._set_air_quality(packet[20:22])
            self[3]._set_temperature(packet[14:16], packet[22:24])
        elif self._type_id == 0x06:
            self[0]._set_temperature(packet[14:16], packet[20:22])
            self[1]._set_humidity(packet[19], packet[25])
            self[2]._set_temperature(packet[16:18], packet[22:24])
        elif self._type_id == 0x07:
            self[0]._set_temperature(packet[14:16], packet[22:24])
            self[1]._set_humidity(packet[17], packet[25])
            self[2]._set_temperature(packet[18:20], packet[26:28])
            self[3]._set_humidity(packet[21], packet[29])
        elif self._type_id == 0x08:
            self[0]._set_temperature(packet[14:16], None, False)
            self[1]._set_rain(packet[16:18])
            self[2]._set_rain_time_span(packet[18:28])
        elif self._type_id == 0x09:
            self[0]._set_temperature(packet[14:16], packet[20:22])
            self[2]._set_humidity(packet[19], packet[25])
            self[1]._set_temperature(packet[16:18], packet[22:24])
        elif self._type_id == 0x0A:
            self[0]._set_boolean(packet[14:16], 0x8000)
            self[1]._set_boolean(packet[14:16], 0x4000)
            self[2]._set_boolean(packet[14:16], 0x2000)
            self[3]._set_boolean(packet[14:16], 0x1000)
            self[4]._set_temperature(packet[16:18], None, False)
        elif self._type_id == 0x0B:
            pos = 15
            for n in range(0, 5):
                self[0]._add_wind_direction(n, packet[pos + 3])
                self[1]._add_wind_speed(n, packet[pos + 2], packet[pos + 3], 0x02)
                self[2]._add_wind_speed(n, packet[pos + 1], packet[pos + 3], 0x01)
                self[3]._add_wind_time_span(n, packet[pos])
                pos += 4
        elif self._type_id == 0x0E:
            self[0]._set_temperature(packet[14:16], packet[19:21])
            self[0]._add_prior_temperature(packet[24:26])
            self[1]._set_humidity_hr(packet[16:18], packet[21:23], packet[26:28])
            self[0]._set_temperature(packet[14:16], packet[18:20])
            self[1]._set_temperature(packet[16:18], packet[20:22])
        elif self._type_id == 0x10:
            self[0]._set_boolean(packet[14:16], 0x8000)
            self[1]._set_door_window_time_span(packet[14:22])
        elif self._type_id == 0x11:
            self[2]._set_temperature(packet[14:16], packet[30:32])
            self[3]._set_humidity(packet[17], packet[33])
            self[4]._set_temperature(packet[18:20], packet[34:36])
            self[5]._set_humidity(packet[21], packet[37])
            self[6]._set_temperature(packet[22:24], packet[38:40])
            self[7]._set_humidity(packet[25], packet[41])
            self[0]._set_temperature(packet[26:28], packet[42:44])
            self[1]._set_humidity(packet[29], packet[45])
        elif self._type_id == 0x12:
            self[0]._set_temperature(packet[18:20], packet[25:27])
            self[1]._set_humidity(packet[20], packet[27])
            self[2]._set_humidity(packet[14], packet[21], True)
            self[3]._set_humidity(packet[15], packet[22], True)
            self[4]._set_humidity(packet[16], packet[23], True)
            self[5]._set_humidity(packet[17], packet[24], True)
        elif self._type_id == 0x15:
            self[0]._set_key_pressed(packet[14])
            self[1]._set_key_press_type(packet[14])
        elif self._type_id == 0x18:
            self[0]._set_temperature(packet[15:17], packet[20:22])
            self[1]._set_humidity(packet[17], packet[22])
            self[2]._set_air_preasure(packet[18:20], packet[23:25])
        else:
            _LOGGER.error("Unknow sensor update package %s", packet.hex().upper())
            return
        self._last_update = packet
        _LOGGER.debug("Sensor updated: %r", self)

    @property
    def sensor_id(self) -> str:
        return self._id

    @property
    def last_update(self) -> Optional[bytes]:
        return self._last_update

    @last_update.setter
    def last_update(self, value: Optional[bytes]) -> None:
        if value is not None:
            self.parse_packet(value)
        else:
            self._last_update = None

    @property
    def parent(self) -> Any:
        return self._parent

    @property
    def counter(self) -> int:
        return self._counter

    @property
    def low_battery(self) -> bool:
        return self._low_battery

    @property
    def by_event(self) -> bool:
        return self._by_event

    @property
    def timestamp(self) -> float:
        return self._timestamp

    @property
    def measurements(self) -> List[Measurement]:
        return self._measurements
