"""Select platform for the ControlMySpa integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity
from .models import SETTABLE_HEATER_MODES, settable_heater_mode, settable_temp_range

HEAT_MODE = SelectEntityDescription(
    key="heat_mode",
    translation_key="heat_mode",
    options=[mode.lower() for mode in SETTABLE_HEATER_MODES],
)
TEMP_RANGE = SelectEntityDescription(
    key="temp_range",
    translation_key="temp_range",
    options=["high", "low"],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ControlMySpaHeatModeSelect(coordinator, HEAT_MODE),
            ControlMySpaTempRangeSelect(coordinator, TEMP_RANGE),
        ]
    )


class ControlMySpaHeatModeSelect(ControlMySpaEntity, SelectEntity):
    """Chooses between Ready and Rest.

    Ready-in-Rest is Rest mode heating for an hour because the jets were used.
    The spa enters and leaves it by itself, so it is not offered here and reads
    as Rest; the heater mode sensor still reports it.
    """

    @property
    def current_option(self) -> str | None:
        """Return the selected heat mode."""
        return settable_heater_mode(self.spa.heater_mode)

    async def async_select_option(self, option: str) -> None:
        """Switch the heater to the chosen mode."""
        await self.coordinator.async_set_heater_mode(option.upper())


class ControlMySpaTempRangeSelect(ControlMySpaEntity, SelectEntity):
    """Chooses between the High and Low temperature ranges.

    Each range has its own target limits, so the thermostat's minimum and
    maximum follow the choice.
    """

    @property
    def current_option(self) -> str | None:
        """Return the active temperature range."""
        return settable_temp_range(self.spa.temp_range)

    async def async_select_option(self, option: str) -> None:
        """Switch the spa to the chosen range."""
        await self.coordinator.async_set_temp_range(option.upper())
