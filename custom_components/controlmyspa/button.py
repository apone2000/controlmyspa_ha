"""Button platform for the ControlMySpa integration."""

from __future__ import annotations

from datetime import time

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity

REFRESH = ButtonEntityDescription(key="refresh", translation_key="refresh")
SYNC_TIME = ButtonEntityDescription(
    key="sync_time",
    translation_key="sync_time",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ControlMySpaRefreshButton(coordinator, REFRESH),
            ControlMySpaSyncTimeButton(coordinator, SYNC_TIME),
        ]
    )


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


class ControlMySpaSyncTimeButton(ControlMySpaEntity, ButtonEntity):
    """Sets the spa's clock from Home Assistant's own local time.

    The spa keeps no seconds and no date, so its clock drifts and a daylight
    saving change leaves it an hour out. Pressing this corrects it; a daily
    automation calling it keeps the filter cycles running when they should.
    """

    @property
    def available(self) -> bool:
        """Match the clock: unavailable only when the controller says so."""
        return super().available and self.spa.rs485_active is not False

    async def async_press(self) -> None:
        """Send Home Assistant's local time to the spa."""
        now = dt_util.now()
        await self.coordinator.async_set_spa_time(time(now.hour, now.minute))
