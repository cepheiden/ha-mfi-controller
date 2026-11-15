"""Ubiquiti inform protocol as spoken by mFi mPower devices (pure Python, no Home Assistant imports).

Packet layout (big endian)::

    magic  "TNBU"      4 bytes
    version            4 bytes  (0)
    mac                6 bytes
    flags              2 bytes  (0x01 encrypted, 0x02 zlib, 0x04 snappy)
    iv                16 bytes  (AES-128-CBC)
    data version       4 bytes  (1 = JSON)
    data length        4 bytes
    payload            n bytes
"""

from __future__ import annotations

import json
import os
import secrets
import struct
import time
import zlib
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"TNBU"
MASTER_KEY = "ba86f2bbe107c7c57eb5f2690775c712"  # public default key of un-adopted devices
FLAG_ENCRYPTED = 0x01
FLAG_ZLIB = 0x02
FLAG_SNAPPY = 0x04
HEADER = struct.Struct(">4sI6sH16sII")

# UDP "connection request" sent by the controller to make the device inform immediately.
WAKEUP_PACKET = b"\x88\x88" + b"\x00" * 18


class InformError(Exception):
    """Malformed or undecryptable inform packet."""


@dataclass
class InformPacket:
    mac: str
    flags: int
    version: int
    data_version: int
    iv: bytes
    payload: bytes  # still encrypted / compressed

    @classmethod
    def parse(cls, raw: bytes) -> InformPacket:
        if len(raw) < HEADER.size:
            raise InformError("packet too short")
        magic, version, mac, flags, iv, data_version, length = HEADER.unpack_from(raw)
        if magic != MAGIC:
            raise InformError("bad magic")
        payload = raw[HEADER.size:HEADER.size + length]
        if len(payload) != length:
            raise InformError("truncated payload")
        return cls(mac.hex(":"), flags, version, data_version, iv, payload)

    def decrypt(self, key: str) -> dict[str, Any]:
        data = self.payload
        if self.flags & FLAG_ENCRYPTED:
            try:
                decryptor = Cipher(algorithms.AES(bytes.fromhex(key)), modes.CBC(self.iv)).decryptor()
                padded = decryptor.update(data) + decryptor.finalize()
                unpadder = padding.PKCS7(128).unpadder()
                data = unpadder.update(padded) + unpadder.finalize()
            except ValueError as err:
                raise InformError("decryption failed (wrong key?)") from err
        if self.flags & FLAG_SNAPPY:
            raise InformError("snappy compression is not supported")
        if self.flags & FLAG_ZLIB:
            try:
                data = zlib.decompress(data)
            except zlib.error as err:
                raise InformError("zlib decompression failed") from err
        try:
            obj = json.loads(data)
        except ValueError as err:
            raise InformError("payload is not JSON (wrong key?)") from err
        if not isinstance(obj, dict):
            raise InformError("payload is not a JSON object")
        return obj


def encode_packet(mac: str, key: str, obj: dict[str, Any], iv: bytes | None = None) -> bytes:
    """Encrypt a JSON object the way the mFi controller does (flags = encrypted, uncompressed)."""
    iv = iv or os.urandom(16)
    padder = padding.PKCS7(128).padder()
    plain = padder.update(json.dumps(obj, separators=(",", ":")).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(bytes.fromhex(key)), modes.CBC(iv)).encryptor()
    payload = encryptor.update(plain) + encryptor.finalize()
    return HEADER.pack(MAGIC, 0, bytes.fromhex(mac.replace(":", "")), FLAG_ENCRYPTED, iv, 1, len(payload)) + payload


def _now_ms() -> int:
    return int(time.time() * 1000)


def noop_response(interval: int) -> dict[str, Any]:
    return {"_type": "noop", "interval": interval, "server_time_in_utc": str(_now_ms())}


def output_command(mac: str, port: int, sensor_id: str | None, on: bool, model: str = "Outlet") -> dict[str, Any]:
    now = _now_ms()
    cmd: dict[str, Any] = {
        "_type": "cmd",
        "_id": secrets.token_hex(12),
        "cmd": "mfi-output",
        "mac": mac,
        "model": model,
        "port": port,
        "val": 1 if on else 0,
        "volt": 0,
        "timer": 0,
        "time": now,
        "server_time_in_utc": str(now),
        "datetime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now / 1000)),
    }
    if sensor_id:
        cmd["sId"] = sensor_id
    return cmd


def new_authkey() -> str:
    return secrets.token_hex(16)


def normalize_key(key: str) -> str:
    key = key.strip().lower()
    if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("authkey must be 32 hex characters")
    return key


def normalize_mac(mac: str) -> str:
    raw = mac.strip().lower().replace(":", "").replace("-", "")
    if len(raw) != 12 or any(c not in "0123456789abcdef" for c in raw):
        raise ValueError("invalid MAC address")
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


# ---------------------------------------------------------------- payload parsing


@dataclass
class PortState:
    port: int
    sensor_id: str | None = None
    output: bool | None = None
    power: float | None = None  # W
    current: float | None = None  # A
    voltage: float | None = None  # V
    power_factor: float | None = None  # 0..1
    energy_this_month: float | None = None  # kWh
    energy_last_month: float | None = None  # kWh
    energy_sum: float | None = None  # Wh since previous report


_TAGS = {
    "active_pwr": "power",
    "i_rms": "current",
    "v_rms": "voltage",
    "pf": "power_factor",
    "thismonth": "energy_this_month",
    "lastmonth": "energy_last_month",
    "energy_sum": "energy_sum",
}


def parse_ports(payload: dict[str, Any]) -> dict[int, PortState]:
    """Extract mPower outlet readings from the ``alarm`` list of an inform payload."""
    ports: dict[int, PortState] = {}
    for item in payload.get("alarm") or []:
        index = str(item.get("index", ""))
        if not index.startswith("vpower"):
            continue
        try:
            number = int(index[len("vpower"):])
        except ValueError:
            continue
        state = PortState(port=number, sensor_id=item.get("sId"))
        for entry in item.get("entries") or []:
            tag, val = entry.get("tag"), entry.get("val")
            if tag == "output":
                try:
                    state.output = bool(int(val))
                except (TypeError, ValueError):
                    state.output = None
            elif tag in _TAGS:
                try:
                    setattr(state, _TAGS[tag], float(val))
                except (TypeError, ValueError):
                    pass
        ports[number] = state
    return ports


# ---------------------------------------------------------------- STUN (RFC 3489 subset)

STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101


def stun_response(request: bytes, addr: tuple[str, int], local_port: int) -> bytes | None:
    """Answer a classic STUN binding request with MAPPED/SOURCE/CHANGED-ADDRESS like the controller."""
    if len(request) < 20:
        return None
    msg_type, _length = struct.unpack(">HH", request[:4])
    if msg_type != STUN_BINDING_REQUEST:
        return None
    transaction = request[4:20]

    def address(attr: int, ip: str, port: int) -> bytes:
        return struct.pack(">HHBBH4s", attr, 8, 0, 1, port, bytes(int(x) for x in ip.split(".")))

    attrs = address(0x0001, addr[0], addr[1]) + address(0x0004, "0.0.0.0", local_port) + address(0x0005, "0.0.0.0", local_port)
    return struct.pack(">HH", STUN_BINDING_RESPONSE, len(attrs)) + transaction + attrs


@dataclass
class DeviceInfo:
    mac: str
    model: str | None = None
    model_display: str | None = None
    version: str | None = None
    hostname: str | None = None
    ip: str | None = None
    uptime: int | None = None
    essid: str | None = None
    bssid: str | None = None
    inform_url: str | None = None
    connect_request_ip: str | None = None
    connect_request_port: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, mac: str, payload: dict[str, Any]) -> DeviceInfo:
        vap = (payload.get("vap_table") or [{}])[0] or {}
        try:
            crp = int(payload.get("connect_request_port")) if payload.get("connect_request_port") else None
        except (TypeError, ValueError):
            crp = None
        try:
            uptime = int(payload["uptime"]) if "uptime" in payload else None
        except (TypeError, ValueError):
            uptime = None
        return cls(
            mac=mac,
            model=payload.get("model"),
            model_display=payload.get("model_display"),
            version=payload.get("version"),
            hostname=payload.get("hostname"),
            ip=payload.get("ip"),
            uptime=uptime,
            essid=vap.get("essid"),
            bssid=vap.get("bssid"),
            inform_url=payload.get("inform_url"),
            connect_request_ip=payload.get("connect_request_ip"),
            connect_request_port=crp,
        )
