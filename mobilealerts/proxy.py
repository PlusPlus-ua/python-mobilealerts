"""MobileAlerts proxy."""

from typing import Any, Dict, List, Optional

import logging
import socket
import struct
import time

from aiohttp import web

from .gateway import Gateway, SensorHandler

_LOGGER = logging.getLogger(__name__)


class Proxy:
    """Proxy server to read PUT requests of Mobile Alerts/WeatherHub sensors."""

    def __init__(
        self,
        handler: Optional[SensorHandler],
        local_ip_address: str = "",
        local_port: int = 0,
    ) -> None:
        self._handler: Optional[SensorHandler] = handler
        self._gateways: Dict[str, Gateway] = dict()
        self._local_ip_address = local_ip_address
        self._local_port = local_port

    async def _start(
        self,
    ) -> None:
        """Internal start proxy server."""
        self._site = web.TCPSite(self._runner, self._local_ip_address, self._local_port)
        await self._site.start()
        server: Any = self._site._server
        sockets: List[socket.socket] = server._sockets
        address = sockets[0].getsockname()
        self._host = str(address[0])
        self._port = int(address[1])
        _LOGGER.debug("Proxy started on address %s:%s", self._host, self._port)

    async def start(
        self,
    ) -> None:
        """Start proxy server."""
        self._server = web.Server(self.request_handler)
        self._runner = web.ServerRunner(self._server)
        await self._runner.setup()
        await self._start()

    async def stop(
        self,
    ) -> None:
        """Stop proxy server and detach all attached gateways."""
        await self._site.stop()
        self.detach_all_gateways()

    async def restart(
        self,
        local_ip_address: str = "",
        local_port: int = 0,
    ) -> None:
        """Restart proxy server on new IP address and port."""
        await self._site.stop()
        self._local_ip_address = local_ip_address
        self._local_port = local_port
        await self._start()

    async def request_handler(self, request: web.BaseRequest) -> web.StreamResponse:
        response = await self.send_response_to_gateway(request)
        if request.method == "PUT":
            headers = request.headers
            if (
                ("Content-Type" in headers)
                and (headers["Content-Type"] == "application/octet-stream")
                and ("Content-Length" in headers)
            ):
                if "HTTP_IDENTIFY" in headers:
                    identify = headers["HTTP_IDENTIFY"].split(":")
                    if len(identify) == 3:
                        gateway: Gateway = self._gateways[identify[1]]
                        content = await request.content.read(
                            int(request.headers["Content-Length"])
                        )
                        await gateway.handle_update(identify[2], content)
                        await gateway.resend_data_to_cloud(
                            request.rel_url, headers, content
                        )
                    else:
                        _LOGGER.error(
                            "Invalid HTTP_IDENTIFY header in gateway's PUT request"
                        )
                else:
                    _LOGGER.error("No HTTP_IDENTIFY header in gateway's PUT request")
            else:
                _LOGGER.error("Invalid content in gateway's PUT request")
        else:
            _LOGGER.error("Invalid gateway's request method %s", request.method)
        return response

    async def send_response_to_gateway(
        self, request: web.BaseRequest
    ) -> web.StreamResponse:
        response = web.StreamResponse(
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": "24",
                "Connection": "close",
            }
        )
        await response.prepare(request)
        content = struct.pack(">IIIIII", 1, 0, int(time.time()), 1, 0x1761D480, 1)
        await response.write_eof(content)
        _LOGGER.debug("Response to gateway: %s", content.hex().upper())
        return response

    def attach_gateway(self, gateway: Gateway) -> None:
        """Attach the gateway to proxy server."""
        if gateway.gateway_id not in self._gateways:
            self._gateways[gateway.gateway_id] = gateway
            gateway.attach_to_proxy(self._host, self._port, self._handler)

    def detach_gateway(self, gateway: Gateway) -> None:
        """Detach the gateway from proxy server."""
        if gateway.gateway_id in self._gateways:
            gateway.detach_from_proxy()
            self._gateways.pop(gateway.gateway_id)

    def detach_all_gateways(self) -> None:
        """Detach from proxy server all attached gateways."""
        for gateway in self._gateways.values():
            gateway.detach_from_proxy()
        self._gateways.clear()

    def __del__(self) -> None:
        self.detach_all_gateways()

    def set_handler(self, handler: Optional[SensorHandler]) -> None:
        self._handler = handler

    def get_gateway_by_id(self, gateway_id: str) -> Gateway:
        return self._gateways[gateway_id]

    @property
    def gateways(self):
        return self._gateways.values()

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port
