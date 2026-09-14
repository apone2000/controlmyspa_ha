"""Sensor platform for the ControlMySpa integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity
from .models import HEATER_MODES, SpaState, heater_mode_state


@dataclass(frozen=True, kw_only=True)
class ControlMySpaSensorDescription(SensorEntityDescription):
    """Describes a ControlMySpa sensor and how to read its value."""

    value_fn: Callable[[SpaState], Any]
    # Temperature units are resolved per-reading from the payload.
    is_temperature: bool = False
    # Diagnostics that stay meaningful while the spa is unreachable.
    always_available: bool = False


SENSORS: tuple[ControlMySpaSensorDescription, ...] = (
    ControlMySpaSensorDescription(
        key="current_temp",
        translation_key="current_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        is_temperature=True,
        value_fn=lambda spa: spa.current_temp,
    ),
    ControlMySpaSensorDescription(
        key="target_temp",
        translation_key="target_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        is_temperature=True,
        value_fn=lambda spa: spa.target_temp,
    ),
    ControlMySpaSensorDescription(
        key="ambient_temp",
        translation_key="ambient_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_temperature=True,
        value_fn=lambda spa: spa.ambient_temp,
    ),
    ControlMySpaSensorDescription(
        key="high_limit_temp",
        translation_key="high_limit_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_temperature=True,
        value_fn=lambda spa: spa.high_limit_temp,
    ),
    ControlMySpaSensorDescription(
        key="heater_mode",
        translation_key="heater_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[mode.lower() for mode in HEATER_MODES],
        value_fn=lambda spa: heater_mode_state(spa.heater_mode),
    ),
    ControlMySpaSensorDescription(
        key="temp_range",
        translation_key="temp_range",
        value_fn=lambda spa: spa.temp_range,
    ),
    ControlMySpaSensorDescription(
        key="run_mode",
        translation_key="run_mode",
        value_fn=lambda spa: spa.run_mode,
    ),
    ControlMySpaSensorDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda spa: spa.error_code,
    ),
    ControlMySpaSensorDescription(
        key="wifi_health",
        translation_key="wifi_health",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda spa: spa.wifi_health,
    ),
    ControlMySpaSensorDescription(
        key="last_uplink",
        translation_key="last_uplink",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Reported even when offline: this is how you see how long it has been.
        always_available=True,
        value_fn=lambda spa: spa.uplink_timestamp,
    ),
    ControlMySpaSensorDescription(
        key="reminder_filter1",
        translation_key="reminder_filter1",
        native_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda spa: spa.reminder_filter1,
    ),
    ControlMySpaSensorDescription(
        key="reminder_filter2",
        translation_key="reminder_filter2",
        native_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda spa: spa.reminder_filter2,
    ),
    ControlMySpaSensorDescription(
        key="reminder_water",
        translation_key="reminder_water",
        native_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda spa: spa.reminder_water,
    ),
    ControlMySpaSensorDescription(
        key="reminder_clearray",
        translation_key="reminder_clearray",
        native_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda spa: spa.reminder_clearray,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data
    async_add_entities(
        ControlMySpaSensor(coordinator, description) for description in SENSORS
    )


class ControlMySpaSensor(ControlMySpaEntity, SensorEntity):
    """A single read-only value drawn from the polled spa state."""

    entity_description: ControlMySpaSensorDescription

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the API actually sends.

        Home Assistant converts to whatever the user's system prefers, so the
        job here is to declare the payload's own unit honestly rather than to
        convert anything.
        """
        if self.entity_description.is_temperature:
            return (
                UnitOfTemperature.FAHRENHEIT
                if self.spa.fahrenheit
                else UnitOfTemperature.CELSIUS
            )
        return self.entity_description.native_unit_of_measurement

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        return self.entity_description.value_fn(self.spa)

    @property
    def available(self) -> bool:
        """Keep offline-relevant diagnostics reporting while the spa is down."""
        if self.entity_description.always_available:
            return self.coordinator.last_update_success
        return super().available
