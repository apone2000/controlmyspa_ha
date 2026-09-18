"""Polling coordinator for the ControlMySpa integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ControlMySpaAuthError,
    ControlMySpaClient,
    ControlMySpaError,
)
from .const import COMMAND_REFRESH_DELAY, DOMAIN, HEATER_MODE_SETTLE_DELAY
from .models import (
    Component,
    SpaState,
    WaterReading,
    command_temperature,
    command_time,
)

_LOGGER = logging.getLogger(__name__)

ControlMySpaConfigEntry = ConfigEntry["ControlMySpaCoordinator"]

WATER_READING_STORAGE_VERSION = 1


def water_reading_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Return the store that keeps a spa's water temperature across restarts."""
    return Store(
        hass, WATER_READING_STORAGE_VERSION, f"{DOMAIN}.{entry_id}.water_temperature"
    )


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
        self._water_store = water_reading_store(hass, config_entry.entry_id)
        self._water_reading: WaterReading | None = None

    async def _async_setup(self) -> None:
        """Load the water temperature saved before the last restart.

        The spa has no water reading until its pump runs, which can be hours
        away, so without this the temperature is unknown after every restart.
        """
        self._water_reading = WaterReading.from_dict(
            await self._water_store.async_load()
        )

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
        state = SpaState.from_api(spa, current_state).holding_water_temperature_from(
            self._water_reading
        )
        await self._async_keep_water_reading(state.water_reading)
        return state

    async def _async_keep_water_reading(self, reading: WaterReading | None) -> None:
        """Remember the latest water reading, saving it when it has changed.

        A poll that could not hold the reading over leaves the last one in
        place rather than forgetting it. The file is only written when a new
        measurement arrives, not on every poll that holds the old one.
        """
        if reading is None or reading == self._water_reading:
            return
        self._water_reading = reading
        await self._water_store.async_save(reading.as_dict())

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

    async def async_refresh_now(self) -> None:
        """Re-read the spa immediately, telling the user if that fails.

        Unlike async_request_refresh this is not debounced, so it always
        fetches. It can only return what the cloud already holds: the spa
        itself uplinks every two to three minutes.
        """
        await self.async_refresh()
        if not self.last_update_success:
            raise HomeAssistantError(
                f"Could not refresh from ControlMySpa: {self.last_exception}"
            )

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

    async def async_set_target_temperature(
        self, temperature: float, celsius: bool
    ) -> None:
        """Set the target, given in the unit the entity shows, and show it."""
        spa = self.data
        limits = (spa.min_temp, spa.max_temp) if spa.fahrenheit else (None, None)
        value = command_temperature(temperature, celsius, *limits)
        await self._async_send(
            self.client.async_set_target_temperature(spa.spa_id, value)
        )
        # The snapshot holds the API's own unit, which for a Fahrenheit spa is
        # exactly what was just sent.
        shown = value if spa.fahrenheit else temperature
        self.async_set_updated_data(replace(spa, target_temp=shown))
        self._schedule_confirmation()

    async def async_set_heater_mode(self, mode: str) -> None:
        """Switch the heater mode and show the result without waiting for a poll.

        The service treats this endpoint as a toggle rather than a setter, so
        asking for the mode the spa is already in answers HTTP 200 with
        ``success: false`` and the message "Heater mode toggled successfully".
        Nothing needs doing in that case, so nothing is sent.

        Ending Ready-in-Rest is accepted like any other change, but the spa
        carries it out as a toggle: it passes through Ready and only settles in
        Rest about 35 seconds later. Confirming at the usual five would read
        that Ready and show it until the next poll, so every mode change is
        given the longer wait.
        """
        wanted = mode.upper()
        if (self.data.heater_mode or "").upper() == wanted:
            return

        await self._async_send(
            self.client.async_set_heater_mode(self.data.spa_id, wanted)
        )
        self.async_set_updated_data(replace(self.data, heater_mode=wanted))
        self._schedule_confirmation(HEATER_MODE_SETTLE_DELAY)

    async def async_set_panel_lock(self, locked: bool) -> None:
        """Lock or unlock the spa's control panel and show it straight away."""
        await self._async_send(
            self.client.async_set_panel_state(
                self.data.spa_id, "LOCK_PANEL" if locked else "UNLOCK_PANEL"
            )
        )
        self.async_set_updated_data(replace(self.data, panel_lock=locked))
        self._schedule_confirmation()

    async def async_set_temp_range(self, temp_range: str) -> None:
        """Switch between HIGH and LOW, showing the new range's limits at once."""
        await self._async_send(
            self.client.async_set_temperature_range(self.data.spa_id, temp_range)
        )
        self.async_set_updated_data(self.data.with_temp_range(temp_range))
        self._schedule_confirmation()

    async def async_set_spa_time(self, value: time) -> None:
        """Set the spa's own clock and show the new reading at once.

        The 12/24-hour display setting travels with every call, so the spa's
        current one is sent back unchanged rather than altered as a side effect
        of setting the time.
        """
        spa = self.data
        military = True if spa.spa_military is None else spa.spa_military
        await self._async_send(
            self.client.async_set_spa_time(spa.spa_id, command_time(value), military)
        )
        self.async_set_updated_data(spa.with_spa_time(value))
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
    def _schedule_confirmation(self, delay: int = COMMAND_REFRESH_DELAY) -> None:
        """Re-read shortly after a command to confirm or correct what we showed.

        ``delay`` is longer for commands the spa takes its time over, so the
        re-read does not catch a state it is only passing through.
        """
        if self._unsub_confirmation is not None:
            self._unsub_confirmation()
        self._unsub_confirmation = async_call_later(
            self.hass, delay, self._async_confirm
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
