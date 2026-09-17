"""Switch platform for the ControlMySpa integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ControlMySpaConfigEntry
from .entity import ControlMySpaEntity, ControlMySpaOnOffEntity, describe_components
from .models import settable_heater_mode

READY_MODE = SwitchEntityDescription(key="ready_mode", translation_key="ready_mode")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ControlMySpaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Ready mode switch and one switch per BLOWER component."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [ControlMySpaReadyModeSwitch(coordinator, READY_MODE)]
    entities.extend(
        ControlMySpaSwitch(coordinator, description, component)
        for description, component in describe_components(
            coordinator.data, "BLOWER", "blower", SwitchEntityDescription
        )
    )
    async_add_entities(entities)


class ControlMySpaSwitch(ControlMySpaOnOffEntity, SwitchEntity):
    """A spa blower as a plain on/off switch, on at its strongest setting."""


class ControlMySpaReadyModeSwitch(ControlMySpaEntity, SwitchEntity):
    """The heat mode as a one-tap toggle: on for Ready, off for Rest.

    Ready-in-Rest reads as off. The spa is still in Rest mode, heating for an
    hour because the jets were used, as the Heat mode select also shows.
    """

    @property
    def is_on(self) -> bool | None:
        """Return True in Ready mode."""
        mode = settable_heater_mode(self.spa.heater_mode)
        return None if mode is None else mode == "ready"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the heater to Ready."""
        await self.coordinator.async_set_heater_mode("READY")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the heater to Rest."""
        await self.coordinator.async_set_heater_mode("REST")
