"""Shared entity base for the ControlMySpa integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import ControlMySpaCoordinator
from .models import SpaState


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
