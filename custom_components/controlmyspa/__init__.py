"""The ControlMySpa integration."""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ControlMySpaClient
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .coordinator import ControlMySpaConfigEntry, ControlMySpaCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ControlMySpaConfigEntry
) -> bool:
    """Set up ControlMySpa from a config entry."""
    client = ControlMySpaClient(
        session=async_get_clientsession(hass),
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
    )

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = ControlMySpaCoordinator(hass, entry, client, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ControlMySpaConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant, entry: ControlMySpaConfigEntry
) -> None:
    """Reload the entry so a changed poll interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)
