"""The Ostrom integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

_LOGGER = logging.getLogger(__name__)
DOMAIN = "ostrom"
PLATFORMS = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ostrom from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Ostrom component."""
    _LOGGER.info("Setting up Ostrom integration")
    hass.states.async_set("ostrom.status", "running")
    hass.data.setdefault(DOMAIN, {})
    return True 