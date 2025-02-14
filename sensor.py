from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  
import logging
from typing import Optional
import aiohttp
from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from .auth import get_access_token

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=15)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = OstromDataCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    
    async_add_entities([
        OstromPriceSensor(coordinator, entry)
    ])

class OstromDataCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name="Ostrom Price Data",
            update_interval=SCAN_INTERVAL,
        )
        self.client_id = entry.data["client_id"]
        self.client_secret = entry.data["client_secret"]
        self.zip_code = entry.data["zip_code"]
        self.environment = entry.data["environment"]
        self._access_token = None
        self._token_expiration = None  # Store token expiration time
        self._env_prefix = "sandbox.ostrom-api.io" if self.environment == "sandbox" else "production.ostrom-api.io"

    async def _async_update_data(self):
        # Check if the token is still valid before fetching prices
        if not self._access_token or datetime.utcnow() >= self._token_expiration:
            await self._get_access_token()

        try:
            return await self._fetch_prices()
        except Exception as err:
            _LOGGER.error("Error fetching price data: %s", err)
            raise

    async def _get_access_token(self):
        try:
            token_data = await get_access_token(self.client_id, self.client_secret, self.environment)
            self._access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)  # Default to 3600 seconds if not provided
            self._token_expiration = datetime.utcnow() + timedelta(seconds=expires_in)
        except Exception as e:
            _LOGGER.error("Failed to get access token: %s", str(e))
            raise

    async def _fetch_prices(self):
        now = datetime.utcnow()
        url = f"https://{self._env_prefix}/spot-prices"
        
        headers = {
            "Authorization": f"Bearer {self._access_token}"
        }
        
        params = {
            "startDate": now.isoformat() + "Z",
            "endDate": (now + timedelta(days=1)).isoformat() + "Z",
            "resolution": "HOUR",
            "zip": self.zip_code
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data["data"]

class OstromPriceSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "Ostrom Energy Price"
        self._attr_unique_id = f"ostrom_price_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "EUR/kWh"

    @property
    def native_value(self) -> Optional[float]:
        if self.coordinator.data:
            # Convert current time to the local timezone using zoneinfo
            local_tz = ZoneInfo(self.coordinator.hass.config.time_zone)
            local_time = datetime.now(local_tz)
            current_hour = local_time.strftime("%Y-%m-%dT%H:00:00.000Z")
            _LOGGER.error("Current hour: %s, local tz: %s, local time: %s", current_hour, local_tz, local_time)

            # Get current hour's price
            for price in self.coordinator.data:
                _LOGGER.error("Now %s: Price for %s: %s", current_hour, price["date"], price["grossKwhPrice"] + price["grossKwhTaxAndLevies"])
                
            current_price = next(
                (round(price["grossKwhPrice"] + price["grossKwhTaxAndLevies"], 2) for price in self.coordinator.data 
                 if price["date"] == current_hour),
                None
            )
            return current_price / 100 if current_price else None
        return None