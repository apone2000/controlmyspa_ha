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
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity

THERMOSTAT = ClimateEntityDescription(key="thermostat")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate platform."""
    async_add_entities([ControlMySpaClimate(entry.runtime_data, THERMOSTAT)])


class ControlMySpaClimate(ControlMySpaEntity, ClimateEntity):
    """Water temperature and the target it heats to.

    The heater cannot be switched off through the API, only moved between
    Ready and Rest, so HEAT is the only mode here and those live on the heat
    mode select.
    """

    # The spa's main entity takes the device's own name.
    _attr_name = None
    # Readings are whole degrees Fahrenheit. Home Assistant rounds converted
    # values to the entity's precision, which would otherwise show 101F as 38C
    # rather than 38.3C. The target step is left unset so the frontend picks
    # one for the display unit -- 0.5 for Celsius, 1 for Fahrenheit -- as the
    # portal does.
    _attr_precision = PRECISION_TENTHS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def temperature_unit(self) -> str:
        """Return the unit the API reports; Home Assistant converts for display."""
        if self.spa.fahrenheit:
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self) -> float | None:
        """Return the water temperature."""
        return self.spa.current_temp

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature the spa heats to."""
        return self.spa.target_temp

    @property
    def min_temp(self) -> float:
        """Return the lowest target the active range allows."""
        if self.spa.min_temp is None:
            return super().min_temp
        return self.spa.min_temp

    @property
    def max_temp(self) -> float:
        """Return the highest target the active range allows."""
        if self.spa.max_temp is None:
            return super().max_temp
        return self.spa.max_temp

    @property
    def hvac_action(self) -> HVACAction:
        """Return whether the heater is running."""
        return HVACAction.HEATING if self.spa.heating else HVACAction.IDLE

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_set_target_temperature(float(temperature))
