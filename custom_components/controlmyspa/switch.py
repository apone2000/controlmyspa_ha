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
    """Set up Ready mode, and one switch per blower and per jet pump."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [ControlMySpaReadyModeSwitch(coordinator, READY_MODE)]
    for component_type, key in (("BLOWER", "blower"), ("PUMP", "jet")):
        entities.extend(
            ControlMySpaSwitch(coordinator, description, component)
            for description, component in describe_components(
                coordinator.data, component_type, key, SwitchEntityDescription
            )
        )
    async_add_entities(entities)


class ControlMySpaSwitch(ControlMySpaOnOffEntity, SwitchEntity):
    """A blower or jet pump as a plain on/off switch.

    A blower switches on at its strongest setting; a pump at its lowest,
    because a stopped pump ignores a request for its highest. Either way it
    reads on at any setting other than off, so a pump that answers LOW by
    running at HIGH still shows as on.

    One switch per component the spa reports, so a jet the spa advertises but
    the tub does not have can simply be disabled in Home Assistant.
    """


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
