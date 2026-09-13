"""Polling coordinator for the ControlMySpa integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ControlMySpaAuthError,
    ControlMySpaClient,
    ControlMySpaError,
)
from .const import DOMAIN
from .models import SpaState

_LOGGER = logging.getLogger(__name__)

ControlMySpaConfigEntry = ConfigEntry["ControlMySpaCoordinator"]


class ControlMySpaCoordinator(DataUpdateCoordinator[SpaState]):
    """Fetches spa state on a fixed interval and shares it with all entities."""

    config_entry: ControlMySpaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ControlMySpaConfigEntry,
        client: ControlMySpaClient,
        scan_interval: int,
    ) -> None:
        """Set up the coordinator with the configured poll interval."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> SpaState:
        """Retrieve a fresh snapshot of spa state.

        Transport failures raise UpdateFailed so the coordinator retries on the
        next tick; only a genuine credential rejection tears the entry down and
        prompts the user to re-authenticate.
        """
        try:
            spa = await self.client.async_get_spa()
        except ControlMySpaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ControlMySpaError as err:
            raise UpdateFailed(str(err)) from err

        return SpaState.from_api(spa)
