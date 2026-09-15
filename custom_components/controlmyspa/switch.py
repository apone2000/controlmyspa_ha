"""Switch platform for the ControlMySpa integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaComponentEntity, describe_components


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one switch per BLOWER component the spa reports."""
    coordinator = entry.runtime_data
    async_add_entities(
        ControlMySpaSwitch(coordinator, description, component)
        for description, component in describe_components(
            coordinator.data, "BLOWER", "blower", SwitchEntityDescription
        )
    )


class ControlMySpaSwitch(ControlMySpaComponentEntity, SwitchEntity):
    """A spa blower as a plain on/off switch, on at its strongest setting."""
