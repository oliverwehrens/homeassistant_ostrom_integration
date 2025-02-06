from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import logging

DOMAIN = "ostrom_integration"
PLATFORMS = ["sensor"]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        # Attempt to set up the integration
        # This could include network calls or other setup tasks
        # If any of these fail, raise ConfigEntryNotReady
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as e:
        _LOGGER.error("Error setting up entry: %s", e)
        raise ConfigEntryNotReady from e

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Ostrom component."""
    _LOGGER.info("Setting up Ostrom integration")
    hass.states.async_set("ostrom_integration.status", "running")
    return True 