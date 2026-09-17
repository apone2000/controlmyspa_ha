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
from .entity import ControlMySpaComponentEntity, ControlMySpaEntity
from .models import HEATER_MODES, SpaState, display_temperature, heater_mode_state


@dataclass(frozen=True, kw_only=True)
class ControlMySpaSensorDescription(SensorEntityDescription):
    """Describes a ControlMySpa sensor and how to read its value."""

    value_fn: Callable[[SpaState], Any]
    attributes_fn: Callable[[SpaState], dict[str, Any]] | None = None
    # Temperature units are resolved per-reading from the payload.
    is_temperature: bool = False
    # A temperature left in the API's own unit, unconverted and unrounded. It
    # has no device class, so Home Assistant does not convert it either.
    api_unit: bool = False
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
        # The value may be held from an earlier reading; this says when it was
        # actually measured.
        attributes_fn=lambda spa: {"measured_at": spa.current_temp_at},
    ),
    ControlMySpaSensorDescription(
        key="current_temp_raw",
        translation_key="current_temp_raw",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        api_unit=True,
        value_fn=lambda spa: spa.current_temp_raw,
    ),
    ControlMySpaSensorDescription(
        key="spa_clock",
        translation_key="spa_clock",
        # The same reading as time.spa_time, without the control. The spa keeps
        # no seconds and no date, so this is HH:MM text rather than a timestamp:
        # a timestamp would need a date invented for it.
        value_fn=lambda spa: (
            None if spa.spa_time is None else spa.spa_time.strftime("%H:%M")
        ),
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
    entities: list[SensorEntity] = [
        ControlMySpaSensor(coordinator, description) for description in SENSORS
    ]
    # One pair per filter cycle the spa reports, numbered from the port the way
    # the spa's own panel and the filter reminders count them.
    for component in coordinator.data.components_of("FILTER"):
        port = component.port or 0
        entities.append(
            ControlMySpaFilterSensor(
                coordinator,
                SensorEntityDescription(
                    key=f"filter_{port}_start_time",
                    translation_key="filter_start_time",
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
                component,
            )
        )
        entities.append(
            ControlMySpaFilterSensor(
                coordinator,
                SensorEntityDescription(
                    key=f"filter_{port}_duration",
                    translation_key="filter_duration",
                    device_class=SensorDeviceClass.DURATION,
                    native_unit_of_measurement=UnitOfTime.MINUTES,
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
                component,
            )
        )
    async_add_entities(entities)


class ControlMySpaSensor(ControlMySpaEntity, SensorEntity):
    """A single read-only value drawn from the polled spa state."""

    entity_description: ControlMySpaSensorDescription

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the value is given in.

        A Celsius Home Assistant gets Celsius directly, with the portal's
        half-degree rounding, instead of an exact conversion of the Fahrenheit
        reading that would disagree with the spa's own panel.
        """
        if self.entity_description.is_temperature:
            return (
                UnitOfTemperature.CELSIUS
                if self.display_celsius
                else UnitOfTemperature.FAHRENHEIT
            )
        if self.entity_description.api_unit:
            return (
                UnitOfTemperature.FAHRENHEIT
                if self.spa.fahrenheit
                else UnitOfTemperature.CELSIUS
            )
        return self.entity_description.native_unit_of_measurement

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        value = self.entity_description.value_fn(self.spa)
        if self.entity_description.is_temperature:
            return display_temperature(value, self.spa.fahrenheit, self.display_celsius)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes, for sensors whose description defines them."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.spa)

    @property
    def available(self) -> bool:
        """Keep offline-relevant diagnostics reporting while the spa is down."""
        if self.entity_description.always_available:
            return self.coordinator.last_update_success
        return super().available


class ControlMySpaFilterSensor(ControlMySpaComponentEntity, SensorEntity):
    """One reading from a filter cycle's schedule: its start, or its length.

    Read-only by design. ControlMySpa accepts a schedule change and then either
    ignores it or applies a different one -- the portal does the same to itself
    -- so a writable control here would lie about what it had done.

    The value reported is the schedule, not whether the cycle is running now:
    a cycle reads ON whenever it is enabled, hours outside its own window. The
    spa gives no field for "filtering right now"; it can only be worked out
    from this start and duration against the spa's own clock.
    """

    @property
    def native_value(self) -> Any:
        """Return the start time as HH:MM, or the length in minutes."""
        component = self.component
        if component is None:
            return None
        if self.entity_description.device_class == SensorDeviceClass.DURATION:
            return component.duration_minutes
        start = component.start_time
        return None if start is None else start.strftime("%H:%M")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Report whether the cycle is switched on at all.

        Without this a disabled cycle still shows a start and a length, which
        reads as a schedule that runs. ON means enabled, not running.
        """
        component = self.component
        if component is None:
            return None
        return {"status": component.value}
