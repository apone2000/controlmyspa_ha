"""Time platform for the ControlMySpa integration."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaComponentEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a start time for each filter cycle the spa reports."""
    coordinator = entry.runtime_data
    async_add_entities(
        ControlMySpaFilterStartTime(
            coordinator,
            TimeEntityDescription(
                key=f"filter_start_{component.port}",
                translation_key="filter_start",
                entity_category=EntityCategory.CONFIG,
            ),
            component,
        )
        for component in coordinator.data.components_of("FILTER")
        if component.port is not None
    )


class ControlMySpaFilterStartTime(ControlMySpaComponentEntity, TimeEntity):
    """The time of day a filter cycle starts."""

    @property
    def native_value(self) -> time | None:
        """Return the start time the spa reports."""
        component = self.component
        return component.start_time if component is not None else None

    async def async_set_value(self, value: time) -> None:
        """Move the filter cycle's start, keeping its length."""
        await self.coordinator.async_set_filter_schedule(self._port, start=value)
