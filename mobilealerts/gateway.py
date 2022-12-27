"""MobileAlerts internet gataway."""

from typing import Any, Awaitable, Callable, Dict, List, Optional

import asyncio
import logging
import re
import socket
import struct
import time
from ipaddress import IPv4Address

import aiohttp
from multidict import CIMultiDictProxy
from yarl import URL

from .sensor import Sensor

_LOGGER = logging.getLogger(__name__)

# SensorHandler = Callable[[Any, Sensor], Awaitable[None]]
#

#: all communication with the gateways are broadcasts
BROADCAST_ADDR = "255.255.255.255"

#: UDP port used by the gateway for comunnications
PORT = 8003

# Commands which acceps gateway via UDP:
DISCOVER_GATEWAYS = 1
#: Find any available gateway in the local network
FIND_GATEWAY = 2
#: Find a single available gateway in the local network
GET_CONFIG = 3
#: Request the configuration of the gateway
SET_CONFIG = 4
#: Set a new configuration. Gateway takes a few seconds to do the update
REBOOT = 5
#: A reboot takes about 10s for the gateway to be back up again

ORIG_PROXY_BYTE1 = 0x19
#: 'Magic' byte #1 to mark preserved original proxy settings
ORIG_PROXY_BYTE2 = 0x74
#: 'Magic' byte #2 to mark preserved original proxy settings


class SensorHandler:
    """Abstract class of MobileAlerts senso's handler."""

    async def sensor_added(self, sensor: Sensor) -> None:
        pass

    async def sensor_updated(self, sensor: Sensor) -> None:
        pass


class Gateway:
    """Controls MobileAlerts internet gataway."""

    def __init__(
        self,
        gateway_id: str,
        local_ip_address: Optional[str] = None,
    ) -> None:
        self._id: bytes = bytes.fromhex(gateway_id)
        self._local_ip_address: Optional[str] = local_ip_address
        self._handler: Optional[SensorHandler] = None
        self._version = "1.50"
        self._last_seen: Optional[float] = None
        self._attached = False
        self._orig_use_proxy: Any = None
        self._orig_proxy: Any = None
        self._orig_proxy_port: Any = None
        self._dhcp_ip: Any = None
        self._use_dhcp: Any = None
        self._fixed_ip: Any = None
        self._fixed_netmask: Any = None
        self._fixed_gateway: Any = None
        self._name: Any = None
        self._server: Any = None
        self._use_proxy: Any = None
        self._proxy: Any = None
        self._proxy_port: Any = None
        self._fixed_dns: Any = None
        self._send_data_to_cloud = True
        self._sensors: Dict[str, Sensor] = dict()
        self._initialized = False
        self._is_online = False

    async def init(
        self,
        config: Optional[bytes] = None,
    ) -> bool:
        if config is None:
            config = await self.get_config()
        if config is not None:
            return self.parse_config(config)
        else:
            return False

    def _check_init(self) -> None:
        if not self._initialized:
            raise Exception("Gateway is not initialized")

    @staticmethod
    def prepare_socket(
        timeout: int,
        local_ip_address: Optional[str],
    ) -> socket.socket:
        """Prepares UDP socket to comunicate with the gateway."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        sock.settimeout(timeout)
        if local_ip_address:
            sock.bind((local_ip_address, 0))
        else:
            sock.bind(("", 0))
        return sock

    @staticmethod
    def prepare_command(command: int, gateway_id: bytes) -> bytes:
        """Prepares command UDP packet to send."""
        packet = struct.pack(">H6sH", command, gateway_id, 10)
        return packet

    async def send_command(
        self, command: int, wait_for_result: bool = False, timeout: int = 2
    ) -> Optional[bytes]:
        """Sends command and optional data to the gateway."""
        packet = self.prepare_command(command, self._id)

        sock = self.prepare_socket(timeout, self._local_ip_address)
        try:
            sock.sendto(packet, (BROADCAST_ADDR, PORT))
            if wait_for_result:
                loop = asyncio.get_event_loop()
                config = await asyncio.wait_for(loop.sock_recv(sock, 256), timeout)
                self._last_seen = time.time()
                return config
            else:
                return None
        finally:
            sock.close()

    async def get_config(self, timeout: int = 30) -> Optional[bytes]:
        """Obtains configuration from the gateway."""
        _LOGGER.debug(
            "Gateway get_config for id=%s, timeout=%s", self.gateway_id, str(timeout)
        )
        result = None
        start_time = time.time()
        while True:
            if (time.time() - start_time) > timeout:
                break
            try:
                result = await self.send_command(FIND_GATEWAY, True, 5)
                break
            except socket.timeout:
                _LOGGER.debug("Gateway FIND_GATEWAY timeout")
                continue
            except asyncio.TimeoutError:
                _LOGGER.debug("Gateway FIND_GATEWAY timeout")
                continue

        self._is_online = result is not None
        return result

    @staticmethod
    def check_config(config: bytes) -> bool:
        return (
            config is not None
            and (len(config) >= 186)
            and (len(config) == int.from_bytes(config[8:10], "big"))
        )

    def parse_config(self, config: bytes) -> bool:
        """Parses configuration obtained from the gateway."""
        result = self.check_config(config) and (
            (self._id is None) or (self._id == config[2:8])
        )
        if result:
            orig_data = bytearray()
            self._id = config[2:8]
            self._dhcp_ip = IPv4Address(config[11:15])
            self._use_dhcp = config[15] != 0
            self._fixed_ip = IPv4Address(config[16:20])
            self._fixed_netmask = IPv4Address(config[20:24])
            self._fixed_gateway = IPv4Address(config[24:28])
            self._name = config[28 : config.find(0, 28, 49)].decode("utf-8")
            str_end_pos = config.find(0, 49, 114)
            if (
                config[str_end_pos + 1] == ORIG_PROXY_BYTE1
                and config[str_end_pos + 2] == ORIG_PROXY_BYTE2
            ):
                orig_data.extend(config[str_end_pos + 3 : 114])
            self._server = config[49:str_end_pos].decode("utf-8")
            self._use_proxy = config[114] != 0
            str_end_pos = config.find(0, 115, 180)
            self._proxy = config[115:str_end_pos].decode("utf-8")
            if (
                config[str_end_pos + 1] == ORIG_PROXY_BYTE1
                and config[str_end_pos + 2] == ORIG_PROXY_BYTE2
            ):
                orig_data.extend(config[str_end_pos + 3 : 180])
            self._proxy_port = int.from_bytes(config[180:182], "big")
            self._fixed_dns = IPv4Address(config[182:186])
            if len(orig_data) > 3:
                self._orig_use_proxy = orig_data[0]
                self._orig_proxy_port = int.from_bytes(orig_data[1:3], "big")
                str_end_pos = orig_data.find(0, 3)
                self._orig_proxy = orig_data[3:str_end_pos].decode("utf-8")
            self._last_seen = time.time()
            self._initialized = True
        return result

    async def update_config(self, timeout: int = 2) -> bool:
        """Updates configuration from the gateway."""
        config = await self.get_config(timeout)
        if config is not None:
            return self.parse_config(config)
        else:
            return False

    def set_config(self) -> None:
        """Set configuration to the gateway."""
        self._check_init()
        command = SET_CONFIG
        if self._orig_use_proxy is not None:
            orig_name_bytes = bytes(self._orig_proxy, "utf-8")
            orig_data_size = 3 + len(orig_name_bytes)
        else:
            orig_data_size = 0
        orig_data = bytearray(orig_data_size)
        if orig_data_size > 0:
            orig_data[0] = self._orig_use_proxy
            orig_data[1:3] = self._orig_proxy_port.to_bytes(2, "big")
            orig_data[3:orig_data_size] = orig_name_bytes
        orig_data_pos = 0
        packet_size = 181
        packet = bytearray(packet_size)
        packet[0:2] = command.to_bytes(2, "big")
        packet[2:8] = self._id
        packet[8:10] = packet_size.to_bytes(2, "big")
        packet[10] = self._use_dhcp
        packet[11:15] = self._fixed_ip.packed
        packet[15:19] = self._fixed_netmask.packed
        packet[19:23] = self._fixed_gateway.packed
        str_bytes = bytes(self._name, "utf-8")
        packet[23 : 23 + len(str_bytes)] = str_bytes
        str_bytes = bytes(21 - len(str_bytes))
        packet[44 - len(str_bytes) : 44] = str_bytes
        str_bytes = bytes(self._server, "utf-8")
        packet[44 : 44 + len(str_bytes)] = str_bytes
        str_bytes = bytearray(65 - len(str_bytes))
        if orig_data_pos < orig_data_size:
            str_bytes[1] = ORIG_PROXY_BYTE1
            str_bytes[2] = ORIG_PROXY_BYTE2
            orig_part_size = min(orig_data_size - orig_data_pos, len(str_bytes) - 3)
            str_bytes[3 : 3 + orig_part_size] = orig_data[
                orig_data_pos : orig_data_pos + orig_part_size
            ]
            orig_data_pos += orig_part_size
        packet[109 - len(str_bytes) : 109] = str_bytes
        packet[109] = self._use_proxy
        str_bytes = bytes(str(self._proxy), "utf-8")
        packet[110 : 110 + len(str_bytes)] = str_bytes
        str_bytes = bytearray(65 - len(str_bytes))
        if orig_data_pos < orig_data_size:
            str_bytes[1] = ORIG_PROXY_BYTE1
            str_bytes[2] = ORIG_PROXY_BYTE2
            orig_part_size = min(orig_data_size - orig_data_pos, len(str_bytes) - 3)
            str_bytes[3 : 3 + orig_part_size] = orig_data[
                orig_data_pos : orig_data_pos + orig_part_size
            ]
        packet[175 - len(str_bytes) : 175] = str_bytes
        packet[175:177] = self._proxy_port.to_bytes(2, "big")
        packet[177:181] = self._fixed_dns.packed

        sock = Gateway.prepare_socket(1, self._local_ip_address)
        try:
            sock.sendto(packet, (BROADCAST_ADDR, PORT))
        finally:
            sock.close()

    def reset_config(self) -> None:
        """Reset configuration of the gateway to default values."""
        self.name = "MOBILEALERTS-Gateway"
        self.use_dhcp = True
        self.fixed_ip = "192.168.1.222"
        self.fixed_netmask = "255.255.255.0"
        self.fixed_gateway = "192.168.1.254"
        self.fixed_dns = "192.168.1.253"
        self.server = "www.data199.com"
        self.use_proxy = False
        self.proxy = "192.168.1.1"
        self.proxy_port = 8080
        self.set_config()

    async def reboot(self, update_config: bool, timeout: int = 30) -> None:
        """Reboots the gateway and optional update configuration."""
        config = await self.send_command(REBOOT, update_config, timeout)
        if update_config and config is not None:
            self.parse_config(config)

    async def ping(self, reattach_to_proxy: bool, timeout: int = 30) -> bool:
        config = await self.get_config(timeout)
        if config:
            result: bool = self.check_config(config)
            if result:
                self._dhcp_ip = IPv4Address(config[11:15])
                self._use_dhcp = config[15] != 0
                self._fixed_ip = IPv4Address(config[16:20])
                if self._attached:
                    curr_use_proxy = config[114] != 0
                    str_end_pos = config.find(0, 115, 180)
                    curr_proxy = config[115:str_end_pos].decode("utf-8")
                    if (
                        (curr_use_proxy != self._use_proxy)
                        or (curr_proxy != self._proxy)
                    ) and reattach_to_proxy:
                        self.set_config()
            return result
        else:
            return False

    @staticmethod
    async def discover(
        local_ip_address: Optional[str] = None,
        timeout: int = 2,
    ) -> List["Gateway"]:
        """Broadcasts discover packet and yeld gateway objects created from resposes."""
        result = []
        discovered = []
        loop = asyncio.get_event_loop()

        sock = Gateway.prepare_socket(timeout, local_ip_address)
        packet = Gateway.prepare_command(DISCOVER_GATEWAYS, bytearray(6))

        try:
            sock.sendto(packet, (BROADCAST_ADDR, PORT))
            _LOGGER.debug("Gateways discovering packet sent")
            start_time = time.time()
            while True:
                try:
                    config = await asyncio.wait_for(loop.sock_recv(sock, 256), 1)
                    _LOGGER.debug("Gateways discovering response received %r", config)
                except socket.timeout:
                    break
                except asyncio.TimeoutError:
                    break
                if Gateway.check_config(config):
                    gateway_id = config[2:8]

                    if gateway_id in discovered:
                        continue
                    discovered.append(gateway_id)

                    gateway = Gateway(gateway_id.hex().upper(), local_ip_address)
                    await gateway.init(config)
                    result.append(gateway)
                if (time.time() - start_time) > timeout:
                    break
        finally:
            sock.close()

        return result

    def set_handler(
        self,
        handler: Optional[SensorHandler],
    ) -> None:
        self._handler = handler

    def attach_to_proxy(
        self,
        proxy: str,
        proxy_port: int,
        handler: Optional[SensorHandler],
    ) -> None:
        """Attachs the gateway to the proxy to read measuremnts.

        Existing proxy settings will be preserved
        """
        if self._orig_use_proxy is None:
            self._orig_use_proxy = self._use_proxy
            self._orig_proxy = self._proxy
            self._orig_proxy_port = self._proxy_port
        self._attached = True
        self._use_proxy = True
        self._proxy = IPv4Address(proxy)
        self._proxy_port = proxy_port
        self.set_handler(handler)
        self.set_config()

    def detach_from_proxy(self) -> None:
        """Detachs the gateway from the proxy and restore original settings."""
        if self._attached:
            self._use_proxy = self._orig_use_proxy
            self._proxy = self._orig_proxy
            self._proxy_port = self._orig_proxy_port
        self._attached = False
        self._orig_use_proxy = None
        self._orig_proxy = None
        self._orig_proxy_port = None
        self.set_handler(None)
        self.set_config()

    def handle_bootup_update(self, package: bytes) -> None:
        """Handle gateway's bootup update packet."""
        if (len(package) == 15) and (package[5:11] == self._id):
            _LOGGER.debug(
                "Gateway bootup timestamp %s",
                time.ctime(int.from_bytes(package[1:5], "big")),
            )
            self._version = (
                str(int.from_bytes(package[11:13], "big"))
                + "."
                + str(int.from_bytes(package[13:15], "big"))
            )
            self._last_seen = time.time()

    def add_sensor(self, sensor: Sensor) -> None:
        """Add sensor object."""
        self._sensors[sensor.sensor_id] = sensor

    @staticmethod
    async def get_sensor_name(sensor_id: str) -> Optional[str]:
        """Try to receive name of the sensor from the cloud."""
        try:
            url = (
                "https://measurements.mobile-alerts.eu/Home"
                + "/MeasurementDetails?deviceid=%s"
                + "&vendorid=9ac3a789-6f6a-47bf-8cf5-f076f532fe64"
                + "&appbundle=eu.mobile_alerts.mobilealerts"
            ) % (sensor_id)
            async with aiohttp.ClientSession() as session:
                async with session.get(str(url)) as response:
                    response_content: str = await response.text()
            match = re.search(r"<h3>(.*) [^ <]+<\/h3>", response_content)
            if match:
                name = match.group(1)
            else:
                name = None
            _LOGGER.debug("Discovered sensor name: %s", name)
            return name
        except Exception as e:
            _LOGGER.error("Error discovering sensor name: %r", e)
            return None

    async def create_sensor(self, sensor_id: str) -> Sensor:
        """Create new sensor object for given ID."""
        name: Optional[str] = await Gateway.get_sensor_name(sensor_id)
        result = Sensor(self, sensor_id, name)
        self.add_sensor(result)
        return result

    async def get_sensor(self, sensor_id: str) -> Sensor:
        """Return sensor object for given ID, creates the sensor if not exists."""
        result = self._sensors.get(sensor_id, None)
        if result is None:
            result = await self.create_sensor(sensor_id)
            _LOGGER.debug("New sensor is discovered: %r", result)
            if (
                result is not None
                and self._handler
                and callable(getattr(self._handler, "sensor_added", None))
            ):
                await self._handler.sensor_added(result)

        return result

    async def handle_sensor_update(self, package: bytes, package_checksum: int) -> None:
        """Handle update packet for one sensor."""
        _LOGGER.debug(
            "Update package %s, checksum %s",
            package.hex().upper(),
            hex(package_checksum),
        )

        checksum = 0
        for b in package:
            checksum += b
        checksum &= 0x7F

        if checksum == package_checksum:
            self._last_seen = time.time()
            sensor_id = package[6:12].hex().upper()
            sensor = await self.get_sensor(sensor_id)
            sensor.parse_packet(package)
            if self._handler and callable(
                getattr(self._handler, "sensor_updated", None)
            ):
                await self._handler.sensor_updated(sensor)
        else:
            _LOGGER.error(
                "Update package checksum error %s, checksum %s",
                package.hex().upper(),
                hex(package_checksum),
            )

    async def handle_sensors_update(self, packages: bytes) -> None:
        """Handle update packet for few sensors."""
        pos = 0
        packages_len = len(packages)

        while pos + 64 <= packages_len:
            await self.handle_sensor_update(
                packages[pos : pos + 63], packages[pos + 63]
            )
            pos += 64

    async def handle_update(
        self, code: str, packages: bytes, remote_ip: Optional[str] = None
    ) -> None:
        """Handle update packets."""
        _LOGGER.debug("Handling update from %s", remote_ip)
        self._is_online = True
        if self._use_dhcp and self._dhcp_ip != remote_ip:
            self._dhcp_ip = remote_ip
        if code == "00":
            self.handle_bootup_update(packages)
        elif code == "C0":
            await self.handle_sensors_update(packages)
        else:
            _LOGGER.error(
                "Unknnow update code %d, data %s",
                code,
                packages.hex().upper(),
            )

    async def resend_data_to_cloud(
        self,
        url: URL,
        headers: CIMultiDictProxy[str],
        content: bytes,
    ) -> None:
        """Resend gateway's PUT request to cloud server."""
        if self._send_data_to_cloud:
            try:
                proxy_to_use: Optional[str] = None
                if self.orig_use_proxy:
                    proxy_to_use = ("http://%s:%s") % (
                        self.orig_proxy,
                        self.orig_proxy_port,
                    )
                async with aiohttp.ClientSession() as session:
                    async with session.put(
                        str(url), proxy=proxy_to_use, headers=headers, data=content
                    ) as response:
                        response_content = await response.content.read()
                        _LOGGER.debug(
                            "Cloud response status: %s content: %s",
                            response.status,
                            response_content.hex().upper(),
                        )
            except Exception as e:
                _LOGGER.error("Error resending request to cloud: %r", e)

    @property
    def gateway_id(self) -> str:
        return self._id.hex().upper()

    @property
    def serial(self) -> str:
        return "80%s" % self._id[3:6].hex().upper()

    @property
    def version(self) -> str:
        return self._version

    @property
    def is_online(self) -> bool:
        return self._is_online

    @property
    def ip_address(self) -> Optional[str]:
        if self._is_online:
            return str(self._dhcp_ip) if self._use_dhcp else str(self._fixed_ip)
        else:
            return None

    @property
    def url(self) -> Optional[str]:
        if self._is_online:
            return "http://%s/" % self.ip_address
        else:
            return None

    @property
    def last_seen(self) -> Optional[float]:
        return self._last_seen

    @property
    def attached(self) -> bool:
        return self._attached

    @property
    def send_data_to_cloud(self) -> bool:
        return self._send_data_to_cloud

    @send_data_to_cloud.setter
    def send_data_to_cloud(self, value: bool) -> None:
        self._send_data_to_cloud = value

    @property
    def dhcp_ip(self) -> str:
        return str(self._dhcp_ip)

    @property
    def use_dhcp(self) -> bool:
        return bool(self._use_dhcp)

    @use_dhcp.setter
    def use_dhcp(self, value: bool) -> None:
        self._use_dhcp = value

    @property
    def fixed_ip(self) -> str:
        return str(self._fixed_ip)

    @fixed_ip.setter
    def fixed_ip(self, value: str) -> None:
        self._fixed_ip = IPv4Address(value)

    @property
    def fixed_netmask(self) -> str:
        return str(self._fixed_netmask)

    @fixed_netmask.setter
    def fixed_netmask(self, value: str) -> None:
        self._fixed_netmask = IPv4Address(value)

    @property
    def fixed_gateway(self) -> str:
        return str(self._fixed_gateway)

    @fixed_gateway.setter
    def fixed_gateway(self, value: str) -> None:
        self._fixed_gateway = IPv4Address(value)

    @property
    def name(self) -> str:
        return str(self._name)

    @name.setter
    def name(self, value: str) -> None:
        if len(bytes(value, "utf-8")) > 20:
            raise ValueError("Name is too long")
        self._name = value

    @property
    def server(self) -> str:
        return str(self._server)

    @server.setter
    def server(self, value: str) -> None:
        if len(bytes(value, "utf-8")) > 64:
            raise ValueError("Server address is too long")
        self._server = value

    @property
    def use_proxy(self) -> bool:
        return bool(self._use_proxy)

    @use_proxy.setter
    def use_proxy(self, value: bool) -> None:
        self._use_proxy = value

    @property
    def proxy(self) -> str:
        return str(self._proxy)

    @proxy.setter
    def proxy(self, value: str) -> None:
        if len(bytes(value, "utf-8")) > 64:
            raise ValueError("Proxy server address is too long")
        self._proxy = value

    @property
    def proxy_port(self) -> int:
        return int(self._proxy_port)

    @proxy_port.setter
    def proxy_port(self, value: int) -> None:
        if value < 0 or value >= 64 * 1024:
            raise ValueError("Invalid proxy port number")
        self._proxy_port = value

    @property
    def fixed_dns(self) -> str:
        return str(self._fixed_dns)

    @fixed_dns.setter
    def fixed_dns(self, value: str) -> None:
        self._fixed_dns = IPv4Address(value)

    @property
    def orig_use_proxy(self) -> bool:
        return bool(self._orig_use_proxy)

    @property
    def orig_proxy(self) -> str:
        return str(self._orig_proxy)

    @property
    def orig_proxy_port(self) -> int:
        return int(self._orig_proxy_port)

    @property
    def sensors(self) -> List[Sensor]:
        return [*self._sensors.values()]

    def __repr__(self) -> str:
        """Return a formal representation of the gateway."""
        return (
            "%s.%s(%s(%s), "
            "gateway_id=%s, "
            "version=%r, "
            "last_seen=%r, "
            "attached=%r, "
            "send_data_to_cloud=%r, "
            "dhcp_ip=%r, "
            "use_dhcp=%r, "
            "fixed_ip=%r, "
            "fixed_netmask=%r, "
            "fixed_gateway=%r, "
            "fixed_dns=%r, "
            "server=%r, "
            "use_proxy=%r, "
            "proxy=%r, "
            "proxy_port=%r, "
            "orig_use_proxy=%r, "
            "orig_proxy=%r, "
            "orig_proxy_port=%r"
            ")"
        ) % (
            self.__class__.__module__,
            self.__class__.__qualname__,
            self.name,
            self.serial,
            self.gateway_id,
            self.version,
            time.ctime(self.last_seen) if self.last_seen is not None else "never",
            self.attached,
            self.send_data_to_cloud,
            self.dhcp_ip,
            self.use_dhcp,
            self.fixed_ip,
            self.fixed_netmask,
            self.fixed_gateway,
            self.fixed_dns,
            self.server,
            self.use_proxy,
            self.proxy,
            self.proxy_port,
            self.orig_use_proxy,
            self.orig_proxy,
            self.orig_proxy_port,
        )

    def __str__(self) -> str:
        """Return a readable representation of the gateway."""
        return (
            "%s V%s, SerialNo: %s (id: %s)\n"
            "Use DHCP: %s\n"
            "DHCP IP: %s\n"
            "Fixed IP: %s\n"
            "Fixed Netmask: %s\n"
            "Fixed Gateway: %s\n"
            "Fixed DNS: %s\n"
            "Cloud Server: %s\n"
            "Use Proxy: %s\n"
            "Proxy Server: %s\n"
            "Proxy Port: %s\n"
            "Send data to cloud: %s\n"
            "Last Contact: %s"
        ) % (
            self.name,
            self.version,
            self.serial,
            self.gateway_id,
            "Yes" if self.use_dhcp else "No",
            self.dhcp_ip,
            self.fixed_ip,
            self.fixed_netmask,
            self.fixed_gateway,
            self.fixed_dns,
            self.server,
            "Yes" if self.use_proxy else "No",
            self.proxy,
            self.proxy_port,
            "Yes" if self.send_data_to_cloud else "No",
            time.ctime(self.last_seen) if self.last_seen is not None else "never",
        )
