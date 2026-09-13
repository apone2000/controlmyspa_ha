"""Binary sensor platform for the ControlMySpa integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity
from .models import SpaState


@dataclass(frozen=True, kw_only=True)
class ControlMySpaBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a ControlMySpa binary sensor and how to read its state."""

    value_fn: Callable[[SpaState], bool | None]
    # Connectivity and staleness must keep reporting while the spa is offline.
    always_available: bool = False
    # Only create the entity when the spa reports the hardware as fitted.
    requires_lighting: bool = False


BINARY_SENSORS: tuple[ControlMySpaBinarySensorDescription, ...] = (
    ControlMySpaBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        value_fn=lambda spa: spa.online,
    ),
    ControlMySpaBinarySensorDescription(
        key="stale_data",
        translation_key="stale_data",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        always_available=True,
        value_fn=lambda spa: spa.is_stale,
    ),
    ControlMySpaBinarySensorDescription(
        key="heating",
        translation_key="heating",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda spa: spa.heating,
    ),
    ControlMySpaBinarySensorDescription(
        key="temperature_reached",
        translation_key="temperature_reached",
        value_fn=lambda spa: spa.temperature_reached,
    ),
    ControlMySpaBinarySensorDescription(
        key="error",
        translation_key="error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        # errorCode is 0 when healthy; treat an unreadable code as no fault.
        value_fn=lambda spa: bool(spa.error_code),
    ),
    ControlMySpaBinarySensorDescription(
        key="light",
        translation_key="light",
        device_class=BinarySensorDeviceClass.LIGHT,
        requires_lighting=True,
        value_fn=lambda spa: spa.light_on,
    ),
    ControlMySpaBinarySensorDescription(
        key="eco_mode",
        translation_key="eco_mode",
        value_fn=lambda spa: spa.eco_mode,
    ),
    ControlMySpaBinarySensorDescription(
        key="soak_mode",
        translation_key="soak_mode",
        value_fn=lambda spa: spa.soak_mode,
    ),
    ControlMySpaBinarySensorDescription(
        key="cleanup_cycle",
        translation_key="cleanup_cycle",
        value_fn=lambda spa: spa.cleanup_cycle,
    ),
    ControlMySpaBinarySensorDescription(
        key="priming_mode",
        translation_key="priming_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda spa: spa.priming_mode,
    ),
    ControlMySpaBinarySensorDescription(
        key="panel_lock",
        translation_key="panel_lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda spa: spa.panel_lock,
    ),
    ControlMySpaBinarySensorDescription(
        key="temp_lock",
        translation_key="temp_lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda spa: spa.temp_lock,
    ),
    ControlMySpaBinarySensorDescription(
        key="settings_lock",
        translation_key="settings_lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda spa: spa.settings_lock,
    ),
    ControlMySpaBinarySensorDescription(
        key="maintenance_locked",
        translation_key="maintenance_locked",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda spa: spa.maintenance_locked,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = entry.runtime_data
    lighting_fitted = coordinator.data.light_present

    async_add_entities(
        ControlMySpaBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
        if lighting_fitted or not description.requires_lighting
    )


class ControlMySpaBinarySensor(ControlMySpaEntity, BinarySensorEntity):
    """A single boolean drawn from the polled spa state."""

    entity_description: ControlMySpaBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.spa)

    @property
    def available(self) -> bool:
        """Keep offline-relevant diagnostics reporting while the spa is down."""
        if self.entity_description.always_available:
            return self.coordinator.last_update_success
        return super().available
