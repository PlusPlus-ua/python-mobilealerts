#!/usr/bin/env python3

from typing import Optional

import asyncio
import logging
import socket
import sys

from mobilealerts import Gateway, Proxy, Sensor

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

gateway_id: Optional[str] = None  # "001D8C0EA927"


async def sensor_handler(sensor: Sensor) -> None:
    print(sensor)
    print("")


proxy: Proxy


async def start():
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    global proxy
    proxy = Proxy(sensor_handler, local_ip)
    await proxy.start()
    print(("Proxy started on %s:%s") % (proxy.host, proxy.port))
    print("Press Ctrl+C to stop, reaction may take a while")
    print("")

    if gateway_id is None:
        gateways = await Gateway.discover(local_ip)
    else:
        gateways = [Gateway(gateway_id, local_ip)]

    print("Gateways:")
    for gateway in gateways:
        await gateway.init()
        print(gateway)
        print("")
        proxy.attach_gateway(gateway)


async def stop():
    global proxy
    await proxy.stop()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("Interrupted")
    finally:
        print("Stopping")
        loop.run_until_complete(stop())
    print("Stopped")
