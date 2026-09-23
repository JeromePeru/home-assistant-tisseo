"""Tisséo Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ROUTE_IDS, CONF_STOP_AREA_ID, DOMAIN, PLATFORMS
from .coordinator import TisseoCoordinator
from .feed import TisseoClient


@dataclass
class TisseoRuntimeData:
    """Runtime state for a configured stop."""

    client: TisseoClient
    coordinator: TisseoCoordinator


type TisseoConfigEntry = ConfigEntry[TisseoRuntimeData]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_STOP_AREA_ID): str,
                vol.Optional(CONF_ROUTE_IDS, default=[]): [str],
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Import an optional YAML seed into the UI-managed integration."""
    if yaml_config := config.get(DOMAIN):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=dict(yaml_config),
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TisseoConfigEntry) -> bool:
    """Set up a Tisséo stop."""
    client = TisseoClient()
    coordinator = TisseoCoordinator(hass, entry, client)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = TisseoRuntimeData(client, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TisseoConfigEntry) -> bool:
    """Unload a Tisséo stop."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: TisseoConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
