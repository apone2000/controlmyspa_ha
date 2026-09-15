"""Lock platform for the ControlMySpa integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity

PANEL_LOCK = LockEntityDescription(key="panel_lock", translation_key="panel_lock")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the lock platform."""
    async_add_entities([ControlMySpaPanelLock(entry.runtime_data, PANEL_LOCK)])


class ControlMySpaPanelLock(ControlMySpaEntity, LockEntity):
    """Locks the spa's own control panel, so its buttons do nothing."""

    @property
    def is_locked(self) -> bool:
        """Return True while the panel is locked."""
        return self.spa.panel_lock

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the panel."""
        await self.coordinator.async_set_panel_lock(True)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the panel."""
        await self.coordinator.async_set_panel_lock(False)
