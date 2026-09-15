"""Shared entity base for the ControlMySpa integration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import ControlMySpaCoordinator
from .models import Component, SpaState

_DescriptionT = TypeVar("_DescriptionT", bound=EntityDescription)


class ControlMySpaEntity(CoordinatorEntity[ControlMySpaCoordinator]):
    """Base entity binding all platforms to the one polled spa."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ControlMySpaCoordinator,
        description: EntityDescription,
    ) -> None:
        """Attach the entity to the spa device."""
        super().__init__(coordinator)
        self.entity_description = description

        spa = coordinator.data
        identifier = spa.serial_number or spa.spa_id
        self._attr_unique_id = f"{identifier}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            manufacturer=MANUFACTURER,
            name="Spa",
            model=spa.controller_type or "ControlMySpa",
            serial_number=spa.serial_number,
            sw_version=spa.controller_version,
        )

    @property
    def spa(self) -> SpaState:
        """Return the most recent snapshot."""
        return self.coordinator.data

    @property
    def available(self) -> bool:
        """Withhold readings while the spa is offline or reporting stale data."""
        return super().available and self.spa.available

    @property
    def display_celsius(self) -> bool:
        """Return True when temperatures should be given in Celsius.

        Always for an API reporting Celsius. Otherwise whenever Home Assistant
        itself uses Celsius, so a reading can carry the portal's half-degree
        rounding instead of Home Assistant converting it exactly.
        """
        return (
            not self.spa.fahrenheit
            or self.hass.config.units.temperature_unit == UnitOfTemperature.CELSIUS
        )


class ControlMySpaComponentEntity(ControlMySpaEntity):
    """An entity bound to one component from current-state.

    The component is looked up again on every read rather than held, because
    each poll replaces the snapshot it lives in.
    """

    def __init__(
        self,
        coordinator: ControlMySpaCoordinator,
        description: EntityDescription,
        component: Component,
    ) -> None:
        """Remember which component this entity controls."""
        super().__init__(coordinator, description)
        self._component_type = component.component_type
        self._port = component.port
        self._attr_translation_placeholders = {"number": str((component.port or 0) + 1)}

    @property
    def component(self) -> Component | None:
        """Return the component in the latest snapshot, if reported."""
        return self.spa.component(self._component_type, self._port)

    @property
    def available(self) -> bool:
        """Go unavailable while component state cannot be read."""
        return super().available and self.component is not None


class ControlMySpaOnOffEntity(ControlMySpaComponentEntity):
    """A component switched on at its strongest setting, or off."""

    @property
    def is_on(self) -> bool | None:
        """Return True at any setting other than off."""
        component = self.component
        return component.is_on if component is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the component on at its strongest setting."""
        component = self._require_component()
        await self.coordinator.async_set_component(component, component.on_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the component off."""
        await self.coordinator.async_set_component(self._require_component(), "OFF")

    def _require_component(self) -> Component:
        """Return the component, or explain why it cannot be commanded."""
        component = self.component
        if component is None:
            raise HomeAssistantError(
                f"The spa is not currently reporting its {self._component_type.lower()}"
            )
        return component


def describe_components(
    spa: SpaState,
    component_type: str,
    translation_key: str,
    description_type: Callable[..., _DescriptionT],
) -> list[tuple[_DescriptionT, Component]]:
    """Describe one entity per commandable component of a type.

    A spa with a single light gets an entity called "Light"; one with several
    gets "Light 1", "Light 2" and so on, numbered from the port.
    """
    components = [c for c in spa.components_of(component_type) if c.command_type]
    name_key = translation_key if len(components) == 1 else f"{translation_key}_numbered"
    return [
        (
            description_type(
                key=f"{translation_key}_{component.port or 0}",
                translation_key=name_key,
            ),
            component,
        )
        for component in components
    ]
