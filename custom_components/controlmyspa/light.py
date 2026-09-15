"""Light platform for the ControlMySpa integration."""

from __future__ import annotations

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaOnOffEntity, describe_components


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one light per LIGHT component the spa reports."""
    coordinator = entry.runtime_data
    async_add_entities(
        ControlMySpaLight(coordinator, description, component)
        for description, component in describe_components(
            coordinator.data, "LIGHT", "light", LightEntityDescription
        )
    )


class ControlMySpaLight(ControlMySpaOnOffEntity, LightEntity):
    """A spa light, switched on at its strongest setting.

    Ordinary spa lights offer only OFF and HIGH, so no brightness is exposed.
    """

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
