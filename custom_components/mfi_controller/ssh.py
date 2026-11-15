"""Provision an mFi device over SSH: read its identity and point its inform URL at Home Assistant.

mFi firmware (2.1.x) ships Dropbear 0.51, which only offers legacy algorithms
(diffie-hellman-group1-sha1, ssh-rsa, aes128-cbc). They are enabled for this
connection only. Host keys are not checked, the device has no stable way to
present one to the user.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

import asyncssh

from .protocol import normalize_key, normalize_mac

LEGACY_OPTIONS = {
    "known_hosts": None,
    "kex_algs": ["diffie-hellman-group14-sha1", "diffie-hellman-group1-sha1"],
    "server_host_key_algs": ["ssh-rsa"],
    "encryption_algs": ["aes128-ctr", "aes128-cbc", "aes256-cbc", "3des-cbc"],
    "mac_algs": ["hmac-sha1", "hmac-md5"],
    "compression_algs": None,
    "connect_timeout": 60,
    "login_timeout": 60,
}
MGMT = "/etc/persistent/cfg/mgmt"
BACKUP = "/etc/persistent/cfg/mgmt.before-homeassistant"


class ProvisionError(Exception):
    """SSH provisioning failed."""


class ProvisionAuthError(ProvisionError):
    """SSH login rejected."""


@dataclass
class DeviceIdentity:
    mac: str
    model: str
    port_count: int
    authkey: str | None
    is_default: bool
    inform_url: str | None
    labels: dict[int, str] = field(default_factory=dict)


def _parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse_identity(board: str, mgmt: str, config: str) -> DeviceIdentity:
    board_vals = dict(re.findall(r'^\$(\w+)="?([^";]*)"?;', board, re.M))
    hwaddr = board_vals.get("board_hwaddr")
    if not hwaddr:
        raise ProvisionError("could not read the device MAC address (/etc/board.inc)")
    mgmt_vals = _parse_kv(mgmt)
    cfg = _parse_kv(config)
    labels: dict[int, str] = {}
    for key, value in cfg.items():
        m = re.fullmatch(r"port\.(\d+)\.label", key)
        if m and value:
            labels[int(m.group(1)) + 1] = value  # config_file counts from 0, vpower from 1
    key = mgmt_vals.get("mgmt.authkey")
    try:
        key = normalize_key(key) if key else None
    except ValueError:
        key = None
    try:
        ports = int(board_vals.get("feature_power", "0"))
    except ValueError:
        ports = 0
    return DeviceIdentity(
        mac=normalize_mac(hwaddr),
        model=board_vals.get("board_shortname") or board_vals.get("board_name") or "mFi",
        port_count=ports,
        authkey=key,
        is_default=mgmt_vals.get("mgmt.is_default", "true") != "false",
        inform_url=mgmt_vals.get("mgmt.servers.1.url"),
        labels=labels,
    )


async def _connect(host: str, username: str, password: str) -> asyncssh.SSHClientConnection:
    try:
        return await asyncssh.connect(host, username=username, password=password, **LEGACY_OPTIONS)
    except asyncssh.PermissionDenied as err:
        raise ProvisionAuthError("SSH login rejected") from err
    except (OSError, asyncssh.Error, TimeoutError) as err:
        raise ProvisionError(f"SSH connection failed: {err}") from err


async def _run(conn: asyncssh.SSHClientConnection, cmd: str, stdin: str | None = None) -> str:
    result = await conn.run(cmd, input=stdin, check=False, timeout=90)
    if result.exit_status not in (0, None):
        raise ProvisionError(f"command failed ({result.exit_status}): {cmd.split()[0]}: {result.stderr!s}"[:300])
    return str(result.stdout or "")


async def async_read_identity(host: str, username: str, password: str) -> DeviceIdentity:
    conn = await _connect(host, username, password)
    async with conn:
        board = await _run(conn, "cat /etc/board.inc")
        mgmt = await _run(conn, f"cat {MGMT}")
        config = await _run(conn, "cat /etc/persistent/cfg/config_file 2>/dev/null; true")
    return parse_identity(board, mgmt, config)


async def async_provision(host: str, username: str, password: str, inform_url: str, key: str) -> DeviceIdentity:
    """Persist the inform URL and authkey on the device and make it connect right away."""
    key = normalize_key(key)
    conn = await _connect(host, username, password)
    async with conn:
        board = await _run(conn, "cat /etc/board.inc")
        mgmt = await _run(conn, f"cat {MGMT}")
        config = await _run(conn, "cat /etc/persistent/cfg/config_file 2>/dev/null; true")
        ident = parse_identity(board, mgmt, config)

        lines = [line for line in mgmt.splitlines() if line.strip()]
        new = []
        seen = set()
        for line in lines:
            name = line.split("=", 1)[0]
            if name == "mgmt.servers.1.url":
                line = f"mgmt.servers.1.url={inform_url}"
            elif name == "mgmt.authkey":
                line = f"mgmt.authkey={key.upper()}"
            elif name == "mgmt.is_default":
                line = "mgmt.is_default=false"
            seen.add(name)
            new.append(line)
        for name, value in (("mgmt.servers.1.url", inform_url), ("mgmt.authkey", key.upper()), ("mgmt.is_default", "false")):
            if name not in seen:
                new.append(f"{name}={value}")
        content = "\n".join(new) + "\n"

        url = shlex.quote(inform_url)
        script = (
            f"[ -f {BACKUP} ] || cp {MGMT} {BACKUP}\n"
            f"cat > {MGMT}.new && mv {MGMT}.new {MGMT}\n"
            "cfgmtd -w -p /etc/ >/dev/null 2>&1\n"
        )
        await _run(conn, f"sh -c {shlex.quote(script)}", stdin=content)
        # key via stdin -> not visible in the process list of the device
        await _run(conn, f"read k; mca-ctrl -t connect -s {url} -k \"$k\" >/dev/null 2>&1; true", stdin=key.upper() + "\n")
    return ident
