"""Number platform for the ControlMySpa integration."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaComponentEntity
from .models import FILTER_INTERVAL_MINUTES

# The longest filter cycle the slider offers: 6 hours, which covers the 5-hour
# cycles seen live. The portal allows up to 24 hours; a longer cycle set there
# or on the panel still shows its real length.
FILTER_DURATION_MAX_MINUTES = 360


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a duration for each filter cycle the spa reports."""
    coordinator = entry.runtime_data
    async_add_entities(
        ControlMySpaFilterDuration(
            coordinator,
            NumberEntityDescription(
                key=f"filter_duration_{component.port}",
                translation_key="filter_duration",
                entity_category=EntityCategory.CONFIG,
                device_class=NumberDeviceClass.DURATION,
                native_unit_of_measurement=UnitOfTime.MINUTES,
                native_min_value=FILTER_INTERVAL_MINUTES,
                native_max_value=FILTER_DURATION_MAX_MINUTES,
                native_step=FILTER_INTERVAL_MINUTES,
                mode=NumberMode.SLIDER,
            ),
            component,
        )
        for component in coordinator.data.components_of("FILTER")
        if component.port is not None
    )


class ControlMySpaFilterDuration(ControlMySpaComponentEntity, NumberEntity):
    """How long a filter cycle runs, in 15-minute steps."""

    @property
    def native_value(self) -> int | None:
        """Return the length the spa reports, in minutes."""
        component = self.component
        return component.duration_minutes if component is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Change the filter cycle's length, keeping its start."""
        await self.coordinator.async_set_filter_schedule(
            self._port, duration_minutes=value
        )
