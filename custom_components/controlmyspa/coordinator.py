"""Polling coordinator for the ControlMySpa integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ControlMySpaAuthError,
    ControlMySpaClient,
    ControlMySpaError,
)
from .const import COMMAND_REFRESH_DELAY, DOMAIN
from .models import Component, SpaState, command_temperature

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
        self._unsub_confirmation: CALLBACK_TYPE | None = None

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

        current_state = await self._async_get_current_state(str(spa.get("_id") or ""))
        return SpaState.from_api(spa, current_state)

    async def _async_get_current_state(self, spa_id: str) -> dict[str, Any] | None:
        """Read component state, tolerating a failure after setup.

        Controls depend on it but readings do not, so a later outage here
        leaves the light and blower unavailable rather than every entity. At
        first refresh it is required: entities are created from what it lists,
        and a spa set up without it would lose its controls until a restart.
        """
        try:
            if not spa_id:
                raise ControlMySpaError("The spa record carried no id")
            return await self.client.async_get_current_state(spa_id)
        except ControlMySpaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ControlMySpaError as err:
            if self.data is None:
                raise UpdateFailed(f"Could not read component state: {err}") from err
            _LOGGER.debug("Component state unavailable this poll: %s", err)
            return None

    async def async_set_component(self, component: Component, state: str) -> None:
        """Command one component and show the result without waiting for a poll."""
        command_type = component.command_type
        if command_type is None:
            raise HomeAssistantError(
                f"{component.component_type} cannot be controlled"
            )
        await self._async_send(
            self.client.async_set_component_state(
                self.data.spa_id, command_type, state, component.device_number
            )
        )
        self.async_set_updated_data(
            self.data.with_component_value(
                component.component_type, component.port, state
            )
        )
        self._schedule_confirmation()

    async def async_set_target_temperature(self, temperature: float) -> None:
        """Set the target, given in the unit the spa reports, and show it."""
        value = command_temperature(temperature, self.data.fahrenheit)
        await self._async_send(
            self.client.async_set_target_temperature(self.data.spa_id, value)
        )
        # A Celsius target arrives here already converted, e.g. 38.5C as
        # 101.3F. Show what was actually sent, not what was asked for.
        shown = value if self.data.fahrenheit else temperature
        self.async_set_updated_data(replace(self.data, target_temp=shown))
        self._schedule_confirmation()

    async def async_set_heater_mode(self, mode: str) -> None:
        """Switch the heater mode and show the result without waiting for a poll."""
        await self._async_send(
            self.client.async_set_heater_mode(self.data.spa_id, mode)
        )
        self.async_set_updated_data(replace(self.data, heater_mode=mode))
        self._schedule_confirmation()

    async def _async_send(self, command: Awaitable[None]) -> None:
        """Await a command, turning a refusal into an error the user sees."""
        try:
            await command
        except ControlMySpaError as err:
            raise HomeAssistantError(
                f"ControlMySpa did not carry out the command: {err}"
            ) from err

    @callback
    def _schedule_confirmation(self) -> None:
        """Re-read shortly after a command to confirm or correct what we showed."""
        if self._unsub_confirmation is not None:
            self._unsub_confirmation()
        self._unsub_confirmation = async_call_later(
            self.hass, COMMAND_REFRESH_DELAY, self._async_confirm
        )

    async def _async_confirm(self, _now: datetime) -> None:
        """Refresh once the service has had time to reflect a command."""
        self._unsub_confirmation = None
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Cancel any pending confirmation before shutting down."""
        if self._unsub_confirmation is not None:
            self._unsub_confirmation()
            self._unsub_confirmation = None
        await super().async_shutdown()
