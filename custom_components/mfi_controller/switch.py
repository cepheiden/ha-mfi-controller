"""Outlet switches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MFiConfigEntry
from .entity import MFiPortEntity
from .hub import CommandError
from .sensor import port_numbers


async def async_setup_entry(hass: HomeAssistant, entry: MFiConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(MFiOutlet(entry, port) for port in port_numbers(entry))


class MFiOutlet(MFiPortEntity, SwitchEntity):
    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_translation_key = "outlet"

    def __init__(self, entry: MFiConfigEntry, port: int) -> None:
        super().__init__(entry, port, "output")

    @property
    def is_on(self) -> bool | None:
        state = self.port_state
        return None if state is None else state.output

    async def _set(self, on: bool) -> None:
        try:
            await self.device.async_set_output(self.port, on)
        except CommandError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
