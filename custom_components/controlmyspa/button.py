"""Button platform for the ControlMySpa integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity

REFRESH = ButtonEntityDescription(key="refresh", translation_key="refresh")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button platform."""
    async_add_entities([ControlMySpaRefreshButton(entry.runtime_data, REFRESH)])


class ControlMySpaRefreshButton(ControlMySpaEntity, ButtonEntity):
    """Re-reads the spa from the cloud without waiting for the next poll."""

    @property
    def available(self) -> bool:
        """Stay pressable while a poll has failed or the spa is offline.

        Those are exactly the times a manual refresh is wanted.
        """
        return True

    async def async_press(self) -> None:
        """Fetch the spa's state now."""
        await self.coordinator.async_refresh_now()
