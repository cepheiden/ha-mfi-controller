"""Entity base classes."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity

from . import MFiConfigEntry
from .const import CONF_LABELS, CONF_MODEL, DOMAIN
from .hub import MFiDevice


class MFiEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: MFiConfigEntry, key: str) -> None:
        self.device: MFiDevice = entry.runtime_data.device
        self._attr_unique_id = f"{self.device.mac}_{key}"
        model = entry.data.get(CONF_MODEL) or "mFi"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.device.mac)},
            connections={(CONNECTION_NETWORK_MAC, self.device.mac)},
            manufacturer="Ubiquiti",
            model=f"mFi mPower ({model})" if model.startswith("P") else f"mFi ({model})",
            name=entry.title.split(" (")[0] if entry.title else "mPower",
            sw_version=self.device.info.version if self.device.info else None,
        )

    @property
    def available(self) -> bool:
        return self.device.online

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.device.add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class MFiPortEntity(MFiEntity):
    def __init__(self, entry: MFiConfigEntry, port: int, key: str) -> None:
        super().__init__(entry, f"port{port}_{key}")
        self.port = port
        labels = entry.data.get(CONF_LABELS) or {}
        self._attr_translation_placeholders = {"label": labels.get(str(port)) or f"Port {port}"}

    @property
    def port_state(self):
        return self.device.ports.get(self.port)

    @property
    def available(self) -> bool:
        return super().available and self.port in self.device.ports
