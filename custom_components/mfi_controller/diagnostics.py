"""Diagnostics (secrets redacted)."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import MFiConfigEntry
from .const import CONF_AUTHKEY

TO_REDACT = {CONF_AUTHKEY, "password"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: MFiConfigEntry) -> dict[str, Any]:
    hub = entry.runtime_data.hub
    device = entry.runtime_data.device
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "hub": {"inform_port": hub.inform_port, "stun_port": hub.stun_port, "stun_error": hub.stun_error},
        "device": {
            "online": device.online,
            "seconds_since_inform": None if device.last_inform is None else round(time.monotonic() - device.last_inform, 1),
            "info": asdict(device.info) if device.info else None,
            "ports": {n: asdict(p) for n, p in device.ports.items()},
        },
    }
