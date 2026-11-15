"""Inform (TCP) + STUN/wake-up (UDP) server shared by all mFi devices of one Home Assistant instance."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from .protocol import (
    MASTER_KEY,
    WAKEUP_PACKET,
    DeviceInfo,
    InformError,
    InformPacket,
    PortState,
    encode_packet,
    noop_response,
    output_command,
    parse_ports,
    stun_response,
)

_LOGGER = logging.getLogger(__name__)

WAKEUP_RETRY = 2.0  # s between wake-up packets while a command is pending
COMMAND_DELIVERY_TIMEOUT = 15.0  # s until the device must have fetched the command
COMMAND_CONFIRM_TIMEOUT = 15.0  # s until an inform must show the new state


class CommandError(Exception):
    """Device did not fetch or apply a command in time."""


@dataclass
class _PendingCommand:
    port: int
    on: bool
    delivered: asyncio.Future[None]
    confirmed: asyncio.Future[None]


class MFiDevice:
    """State of one adopted device, fed by its informs."""

    def __init__(self, hub: InformHub, mac: str, key: str, interval: int) -> None:
        self.hub = hub
        self.mac = mac
        self.key = key
        self.interval = interval
        self.ports: dict[int, PortState] = {}
        self.info: DeviceInfo | None = None
        self.last_inform: float | None = None  # monotonic
        self.last_remote: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self._pending: list[_PendingCommand] = []
        self._first_inform = asyncio.get_running_loop().create_future()

    # ---- listeners
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("listener failed")

    @property
    def online(self) -> bool:
        if self.last_inform is None:
            return False
        return time.monotonic() - self.last_inform < max(3 * self.interval + 5, 35)

    async def wait_first_inform(self, timeout: float) -> None:
        await asyncio.wait_for(asyncio.shield(self._first_inform), timeout)

    # ---- inform handling (called by the hub)
    def handle_inform(self, payload: dict[str, Any], remote: str | None) -> dict[str, Any]:
        self.last_inform = time.monotonic()
        self.last_remote = remote
        self.info = DeviceInfo.from_payload(self.mac, payload)
        ports = parse_ports(payload)
        if ports:
            self.ports = ports
        # confirm delivered commands whose target state is now reported
        for cmd in list(self._pending):
            if cmd.delivered.done():
                state = self.ports.get(cmd.port)
                if state is not None and state.output is cmd.on:
                    if not cmd.confirmed.done():
                        cmd.confirmed.set_result(None)
                    self._pending.remove(cmd)
        if not self._first_inform.done():
            self._first_inform.set_result(None)
        self._notify()
        # next undelivered command, else noop
        for cmd in self._pending:
            if not cmd.delivered.done():
                cmd.delivered.set_result(None)
                state = self.ports.get(cmd.port)
                sensor_id = state.sensor_id if state else None
                if state is not None:  # optimistic; the device confirms with its next inform (~1 s)
                    state.output = cmd.on
                    self._notify()
                return output_command(self.mac, cmd.port, sensor_id, cmd.on)
        return noop_response(self.interval)

    # ---- commands
    def wakeup_target(self) -> tuple[str, int] | None:
        info = self.info
        if info and info.connect_request_port:
            return (info.connect_request_ip or info.ip or self.last_remote or "", info.connect_request_port)
        return None

    async def async_set_output(self, port: int, on: bool) -> None:
        loop = asyncio.get_running_loop()
        # a newer command for the same port supersedes an undelivered older one
        for old in list(self._pending):
            if old.port == port and not old.delivered.done():
                old.delivered.cancel()
                old.confirmed.cancel()
                self._pending.remove(old)
        cmd = _PendingCommand(port, on, loop.create_future(), loop.create_future())
        self._pending.append(cmd)
        try:
            deadline = loop.time() + COMMAND_DELIVERY_TIMEOUT
            while not cmd.delivered.done():
                self.hub.send_wakeup(self)
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise CommandError(f"device {self.mac} did not fetch the command (offline?)")
                try:
                    await asyncio.wait_for(asyncio.shield(cmd.delivered), min(WAKEUP_RETRY, remaining))
                except TimeoutError:
                    continue
            try:
                await asyncio.wait_for(asyncio.shield(cmd.confirmed), COMMAND_CONFIRM_TIMEOUT)
            except TimeoutError as err:
                raise CommandError(f"device {self.mac} did not confirm port {port}") from err
        finally:
            if cmd in self._pending:
                self._pending.remove(cmd)


class _StunProtocol(asyncio.DatagramProtocol):
    def __init__(self, hub: InformHub) -> None:
        self.hub = hub
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        reply = stun_response(data, addr[:2], self.hub.stun_port)
        if reply and self.transport:
            self.transport.sendto(reply, addr)


class InformHub:
    """Owns the listening sockets and routes informs to registered devices by MAC."""

    def __init__(self, inform_port: int, stun_port: int, host: str = "0.0.0.0") -> None:
        self.host = host
        self.inform_port = inform_port
        self.stun_port = stun_port
        self.devices: dict[str, MFiDevice] = {}
        self._runner: web.AppRunner | None = None
        self._stun: asyncio.DatagramTransport | None = None
        self._wakeup_sock: asyncio.DatagramTransport | None = None
        self._unknown_logged: set[str] = set()
        self.stun_error: str | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/inform", self._handle_http)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.inform_port, reuse_address=True)
        try:
            await site.start()
        except OSError:
            await runner.cleanup()
            raise
        self._runner = runner
        loop = asyncio.get_running_loop()
        try:
            self._stun, _ = await loop.create_datagram_endpoint(
                lambda: _StunProtocol(self), local_addr=(self.host, self.stun_port)
            )
        except OSError as err:
            # wake-ups still work from an ephemeral port; only the device's STUN check fails
            self.stun_error = str(err)
            _LOGGER.warning("Cannot bind STUN port udp/%s (%s); using an ephemeral port for wake-ups", self.stun_port, err)
            self._wakeup_sock, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=(self.host, 0))
        _LOGGER.debug("mFi inform server listening on tcp/%s", self.inform_port)

    async def stop(self) -> None:
        for transport in (self._stun, self._wakeup_sock):
            if transport:
                transport.close()
        self._stun = self._wakeup_sock = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    def register(self, mac: str, key: str, interval: int) -> MFiDevice:
        device = self.devices.get(mac)
        if device is None:
            device = MFiDevice(self, mac, key, interval)
            self.devices[mac] = device
        else:
            device.key, device.interval = key, interval
        return device

    def unregister(self, mac: str) -> None:
        self.devices.pop(mac, None)

    def send_wakeup(self, device: MFiDevice) -> None:
        target = device.wakeup_target()
        transport = self._stun or self._wakeup_sock
        if target and target[0] and transport:
            transport.sendto(WAKEUP_PACKET, target)

    async def _handle_http(self, request: web.Request) -> web.Response:
        raw = await request.read()
        try:
            packet = InformPacket.parse(raw)
        except InformError as err:
            _LOGGER.debug("Ignoring malformed inform from %s: %s", request.remote, err)
            return web.Response(status=400)
        device = self.devices.get(packet.mac)
        if device is None:
            self._log_unknown(packet, request.remote)
            return web.Response(status=404)
        try:
            payload = packet.decrypt(device.key)
        except InformError as err:
            _LOGGER.warning("Inform from %s (%s) could not be decrypted: %s", packet.mac, request.remote, err)
            return web.Response(status=403)
        reply = device.handle_inform(payload, request.remote)
        body = encode_packet(packet.mac, device.key, reply)
        return web.Response(body=body, content_type="application/x-binary")

    def _log_unknown(self, packet: InformPacket, remote: str | None) -> None:
        if packet.mac in self._unknown_logged:
            return
        self._unknown_logged.add(packet.mac)
        state = "unknown"
        try:
            packet.decrypt(MASTER_KEY)
            state = "un-adopted (default key)"
        except InformError:
            pass
        _LOGGER.info("Inform from %s device %s at %s; add it via the mFi Controller integration", state, packet.mac, remote)
