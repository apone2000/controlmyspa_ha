"""Climate platform for the ControlMySpa integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    PRECISION_WHOLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity
from .models import SETTABLE_HEATER_MODES, display_temperature, settable_heater_mode

# Translation key only drives the preset names; the entity takes the device's
# own name.
THERMOSTAT = ClimateEntityDescription(key="thermostat", translation_key="thermostat")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate platform."""
    async_add_entities([ControlMySpaClimate(entry.runtime_data, THERMOSTAT)])


class ControlMySpaClimate(ControlMySpaEntity, ClimateEntity):
    """Water temperature, the target it heats to, and Ready or Rest.

    The heater cannot be switched off through the API, only moved between
    Ready and Rest, so HEAT is the only mode and those two are presets. That
    also puts them in the thermostat's own row, e.g. "Idle (Heat - Rest)".
    Ready-in-Rest is reported as Rest, as on the heat mode select.

    In a Celsius Home Assistant this works in Celsius itself, with the
    portal's half-degree rounding, rather than leaving Home Assistant to
    convert Fahrenheit exactly: 100F reads 37.5 as it does on the spa.
    """

    _attr_name = None
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_preset_modes = [mode.lower() for mode in SETTABLE_HEATER_MODES]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )

    @property
    def temperature_unit(self) -> str:
        """Return the unit this entity works in."""
        if self.display_celsius:
            return UnitOfTemperature.CELSIUS
        return UnitOfTemperature.FAHRENHEIT

    @property
    def precision(self) -> float:
        """Match the portal: half degrees Celsius, whole degrees Fahrenheit."""
        return PRECISION_HALVES if self.display_celsius else PRECISION_WHOLE

    @property
    def target_temperature_step(self) -> float:
        """Step the target as the portal does."""
        return 0.5 if self.display_celsius else 1.0

    @property
    def current_temperature(self) -> float | None:
        """Return the water temperature."""
        return self._shown(self.spa.current_temp)

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature the spa heats to."""
        return self._shown(self.spa.target_temp)

    @property
    def min_temp(self) -> float:
        """Return the lowest target the active range allows."""
        shown = self._shown(self.spa.min_temp)
        return super().min_temp if shown is None else shown

    @property
    def max_temp(self) -> float:
        """Return the highest target the active range allows."""
        shown = self._shown(self.spa.max_temp)
        return super().max_temp if shown is None else shown

    @property
    def hvac_action(self) -> HVACAction:
        """Return whether the heater is running."""
        return HVACAction.HEATING if self.spa.heating else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Return Ready or Rest."""
        return settable_heater_mode(self.spa.heater_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_set_target_temperature(
            float(temperature), self.display_celsius
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Switch the heater between Ready and Rest."""
        await self.coordinator.async_set_heater_mode(preset_mode.upper())

    def _shown(self, value: float | None) -> float | None:
        """Convert a reading into the unit this entity works in."""
        return display_temperature(value, self.spa.fahrenheit, self.display_celsius)
