"""mFi Controller: a local replacement for the Ubiquiti mFi controller for mPower strips.

Devices push their state ("inform") to Home Assistant every few seconds; outlets are
switched by waking the device up over UDP and answering its next inform with a command.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_AUTHKEY,
    CONF_INFORM_PORT,
    CONF_MAC,
    CONF_STUN_PORT,
    DATA_HUB,
    DEFAULT_INFORM_PORT,
    DEFAULT_STUN_PORT,
    DOMAIN,
    INFORM_INTERVAL,
)
from .hub import InformHub, MFiDevice

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.SWITCH]


@dataclass
class MFiRuntimeData:
    hub: InformHub
    device: MFiDevice


type MFiConfigEntry = ConfigEntry[MFiRuntimeData]


async def async_get_hub(hass: HomeAssistant, inform_port: int, stun_port: int) -> InformHub:
    """Return the shared inform server, starting it on first use."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    hub: InformHub | None = domain_data.get(DATA_HUB)
    if hub is not None:
        if (hub.inform_port, hub.stun_port) != (inform_port, stun_port):
            _LOGGER.warning(
                "mFi inform server already runs on tcp/%s udp/%s; ignoring tcp/%s udp/%s of another entry",
                hub.inform_port, hub.stun_port, inform_port, stun_port,
            )
        return hub
    hub = InformHub(inform_port, stun_port)
    await hub.start()
    domain_data[DATA_HUB] = hub

    async def _stop(_event: Event) -> None:
        await hub.stop()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop)
    return hub


async def async_setup_entry(hass: HomeAssistant, entry: MFiConfigEntry) -> bool:
    try:
        hub = await async_get_hub(
            hass,
            entry.data.get(CONF_INFORM_PORT, DEFAULT_INFORM_PORT),
            entry.data.get(CONF_STUN_PORT, DEFAULT_STUN_PORT),
        )
    except OSError as err:
        raise ConfigEntryNotReady(f"cannot open the inform port: {err}") from err

    device = hub.register(entry.data[CONF_MAC], entry.data[CONF_AUTHKEY], INFORM_INTERVAL)
    entry.runtime_data = MFiRuntimeData(hub, device)

    @callback
    def _update_device_registry() -> None:
        info = device.info
        if info is None:
            return
        dev_reg = dr.async_get(hass)
        dev = dev_reg.async_get_device_by_identifier((DOMAIN, device.mac), entry.entry_id) if hasattr(
            dev_reg, "async_get_device_by_identifier"
        ) else dev_reg.async_get_device(identifiers={(DOMAIN, device.mac)})
        if dev and info.version and dev.sw_version != info.version:
            dev_reg.async_update_device(dev.id, sw_version=info.version)

    entry.async_on_unload(device.add_listener(_update_device_registry))
    # re-evaluate availability even when the device stops talking
    entry.async_on_unload(
        async_track_time_interval(hass, lambda _now: device._notify(), timedelta(seconds=INFORM_INTERVAL))  # noqa: SLF001
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MFiConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hub = entry.runtime_data.hub
        hub.unregister(entry.data[CONF_MAC])
        others = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.state.recoverable
        ]
        if not hub.devices and not others:
            await hub.stop()
            hass.data.get(DOMAIN, {}).pop(DATA_HUB, None)
    return unloaded
