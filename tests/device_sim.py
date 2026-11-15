"""A simulated mFi mPower that speaks the inform protocol like the real firmware."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp

from custom_components.mfi_controller.protocol import InformPacket, encode_packet


class _Udp(asyncio.DatagramProtocol):
    def __init__(self, sim: SimDevice) -> None:
        self.sim = sim

    def datagram_received(self, data: bytes, addr) -> None:
        self.sim.wakeups += 1
        if data.startswith(b"\x88\x88"):
            self.sim.trigger()


class SimDevice:
    def __init__(self, mac: str, key: str, hub_port: int, ports: int = 3) -> None:
        self.mac, self.key, self.hub_port = mac, key, hub_port
        self.outputs = {n: True for n in range(1, ports + 1)}
        self.power = {n: 10.0 * n for n in range(1, ports + 1)}
        self.wakeups = 0
        self.informs = 0
        self.commands: list[dict[str, Any]] = []
        self._udp: asyncio.DatagramTransport | None = None
        self.udp_port = 0
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.interval = 30.0  # long, so tests prove wake-ups work

    async def start(self, run_loop: bool = True) -> None:
        loop = asyncio.get_running_loop()
        self._udp, _ = await loop.create_datagram_endpoint(lambda: _Udp(self), local_addr=("127.0.0.1", 0))
        self.udp_port = self._udp.get_extra_info("sockname")[1]
        if run_loop:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._udp:
            self._udp.close()

    def trigger(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            try:
                await self.inform()
            except aiohttp.ClientError:
                pass
            try:
                await asyncio.wait_for(self._wake.wait(), self.interval)
            except TimeoutError:
                pass
            self._wake.clear()

    def payload(self) -> dict[str, Any]:
        alarm = []
        for n, on in self.outputs.items():
            alarm.append({
                "sId": f"sid{n}", "index": f"vpower{n}", "time": int(time.time() * 1000),
                "entries": [
                    {"type": "output", "tag": "output", "val": 1 if on else 0},
                    {"type": "analog", "tag": "pf", "val": 0.5},
                    {"type": "rmsSum", "tag": "energy_sum", "val": 0.3125},
                    {"type": "rms", "tag": "v_rms", "val": 230.1},
                    {"type": "analog", "tag": "i_rms", "val": 0.1 * n if on else 0.0},
                    {"type": "analog", "tag": "active_pwr", "val": self.power[n] if on else 0.0},
                    {"tag": "thismonth", "val": 1.5 * n},
                    {"tag": "lastmonth", "val": 3.0 * n},
                ],
            })
        return {
            "hostname": "ubnt", "mac": self.mac, "model": "P3E", "model_display": "mPower", "version": "2.1.12.1310",
            "uptime": 100, "ip": "127.0.0.1", "connect_request_ip": "127.0.0.1", "connect_request_port": str(self.udp_port),
            "inform_url": f"http://127.0.0.1:{self.hub_port}/inform",
            "vap_table": [{"essid": "TestNet", "bssid": "00:11:22:33:44:55"}], "alarm": alarm,
        }

    async def inform(self) -> dict[str, Any]:
        body = encode_packet(self.mac, self.key, self.payload())
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://127.0.0.1:{self.hub_port}/inform", data=body,
                                    headers={"Content-Type": "application/x-binary"}) as resp:
                resp.raise_for_status()
                reply = InformPacket.parse(await resp.read()).decrypt(self.key)
        self.informs += 1
        if reply.get("_type") == "cmd" and reply.get("cmd") == "mfi-output":
            self.commands.append(reply)
            self.outputs[int(reply["port"])] = bool(reply["val"])
            asyncio.get_running_loop().call_later(0.05, self.trigger)  # firmware informs again right away
        return reply
