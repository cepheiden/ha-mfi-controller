"""Outlet measurements, total power and diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MFiConfigEntry
from .const import CONF_PORT_COUNT
from .entity import MFiEntity, MFiPortEntity
from .protocol import PortState


@dataclass(frozen=True, kw_only=True)
class PortSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PortState], float | None]


PORT_SENSORS: tuple[PortSensorDescription, ...] = (
    PortSensorDescription(
        key="power", translation_key="power", device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1, value_fn=lambda p: p.power,
    ),
    PortSensorDescription(
        key="energy", translation_key="energy", device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3, value_fn=lambda p: p.energy_this_month,
    ),
    PortSensorDescription(
        key="current", translation_key="current", device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3, value_fn=lambda p: p.current,
    ),
    PortSensorDescription(
        key="voltage", translation_key="voltage", device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1, value_fn=lambda p: p.voltage,
    ),
    PortSensorDescription(
        key="power_factor", translation_key="power_factor", device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda p: None if p.power_factor is None else round(p.power_factor * 100, 1),
    ),
    PortSensorDescription(
        key="energy_last_month", translation_key="energy_last_month", device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, suggested_display_precision=3,
        entity_registry_enabled_default=False, value_fn=lambda p: p.energy_last_month,
    ),
)


def port_numbers(entry: MFiConfigEntry) -> list[int]:
    count = entry.data.get(CONF_PORT_COUNT) or len(entry.runtime_data.device.ports) or 0
    known = set(entry.runtime_data.device.ports)
    return sorted(set(range(1, int(count) + 1)) | known)


async def async_setup_entry(hass: HomeAssistant, entry: MFiConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    entities: list[SensorEntity] = [
        MFiPortSensor(entry, port, desc) for port in port_numbers(entry) for desc in PORT_SENSORS
    ]
    entities += [MFiTotalPower(entry), MFiIpSensor(entry)]
    async_add_entities(entities)


class MFiPortSensor(MFiPortEntity, SensorEntity):
    entity_description: PortSensorDescription

    def __init__(self, entry: MFiConfigEntry, port: int, desc: PortSensorDescription) -> None:
        super().__init__(entry, port, desc.key)
        self.entity_description = desc

    @property
    def native_value(self) -> float | None:
        state = self.port_state
        return None if state is None else self.entity_description.value_fn(state)


class MFiTotalPower(MFiEntity, SensorEntity):
    _attr_translation_key = "total_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, entry: MFiConfigEntry) -> None:
        super().__init__(entry, "total_power")

    @property
    def native_value(self) -> float | None:
        values = [p.power for p in self.device.ports.values() if p.power is not None]
        return round(sum(values), 2) if values else None


class MFiIpSensor(MFiEntity, SensorEntity):
    _attr_translation_key = "ip_address"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: MFiConfigEntry) -> None:
        super().__init__(entry, "ip_address")

    @property
    def native_value(self) -> str | None:
        return self.device.info.ip if self.device.info else None

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        info = self.device.info
        if info is None:
            return {}
        return {"ssid": info.essid, "bssid": info.bssid, "firmware": info.version, "uptime_s": info.uptime}
