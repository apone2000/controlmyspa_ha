"""Time platform for the ControlMySpa integration."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity

SPA_TIME = TimeEntityDescription(
    key="spa_time",
    translation_key="spa_time",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the time platform."""
    async_add_entities([ControlMySpaTime(entry.runtime_data, SPA_TIME)])


class ControlMySpaTime(ControlMySpaEntity, TimeEntity):
    """The spa's own clock, which is what schedules its filter cycles.

    The controller keeps the time, so the portal disables its own dialog while
    the RS485 link is down and this follows it. The spa reports no seconds and
    no date, so the clock is only ever accurate to the minute, it drifts, and a
    daylight saving change leaves it an hour out until it is set again.
    """

    @property
    def available(self) -> bool:
        """Withhold the clock while the controller cannot be reached.

        Only an explicit False counts: a spa that never reports the RS485 flag
        must keep its clock rather than lose the entity.
        """
        return super().available and self.spa.rs485_active is not False

    @property
    def native_value(self) -> time | None:
        """Return the time the spa is keeping."""
        return self.spa.spa_time

    async def async_set_value(self, value: time) -> None:
        """Set the spa's clock, keeping its 12/24-hour display setting."""
        await self.coordinator.async_set_spa_time(value)
