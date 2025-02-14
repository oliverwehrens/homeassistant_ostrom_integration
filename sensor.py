from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  
import logging
from typing import Optional, Dict
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
    UpdateFailed,
)
from homeassistant.const import CURRENCY_EURO
from .auth import get_access_token

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(hours=1)

class PowerPriceData:
    """Stores power price data for forecasting."""
    def __init__(self):
        self.prices = {}  # Dictionary of datetime -> price
        self._min_price = None
        self._max_price = None
        self._avg_price = None
        self.current_price = None
        self.next_price = None
        self.lowest_price_time = None
        self.highest_price_time = None

    def add_entry(self, timestamp: datetime, price: float) -> None:
        """Add a price entry and update statistics."""
        clean_timestamp = timestamp.replace(minute=0, second=0, microsecond=0)
        self.prices[clean_timestamp] = price
        self._update_statistics()

    def _update_statistics(self) -> None:
        """Update price statistics."""
        if self.prices:
            prices = list(self.prices.values())
            self._min_price = min(prices)
            self._max_price = max(prices)
            self._avg_price = sum(prices) / len(prices)
            
            # Get current price using local time
            now = datetime.now(ZoneInfo("UTC")).replace(minute=0, second=0, microsecond=0)
            self.current_price = self.prices.get(now)
            
            # Get next hour's price
            next_hour = now + timedelta(hours=1)
            self.next_price = self.prices.get(next_hour)
            
            # Find times for min/max prices
            for time, price in self.prices.items():
                if price == self._min_price:
                    self.lowest_price_time = time
                if price == self._max_price:
                    self.highest_price_time = time

    def get_current_price(self) -> Optional[float]:
        """Get the current hour's price."""
        now = datetime.now(ZoneInfo("UTC")).replace(minute=0, second=0, microsecond=0)
        return self.prices.get(now)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = OstromDataCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    
    entities = [
        OstromForecastSensor(coordinator, entry),
        OstromAveragePriceSensor(coordinator, entry),
        OstromMinPriceSensor(coordinator, entry),
        OstromMaxPriceSensor(coordinator, entry),
        OstromNextPriceSensor(coordinator, entry),
        OstromLowestPriceTimeSensor(coordinator, entry),
        OstromHighestPriceTimeSensor(coordinator, entry),
    ]
    
    async_add_entities(entities)

class OstromDataCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch Ostrom price data."""
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
        self._token_expiration = None
        self._env_prefix = "sandbox.ostrom-api.io" if self.environment == "sandbox" else "production.ostrom-api.io"
        self.local_tz = ZoneInfo(hass.config.time_zone)

    async def _async_update_data(self) -> PowerPriceData:
        """Fetch and process price data with proper error handling."""
        try:
            # Check token expiration in UTC
            if not self._access_token or datetime.now(ZoneInfo("UTC")) >= self._token_expiration:
                await self._get_access_token()

            raw_data = await self._fetch_prices()
            return self._process_price_data(raw_data)
        except Exception as err:
            _LOGGER.error("Error updating price data: %s", err)
            raise UpdateFailed(f"Error fetching data: {err}") from err

    def _process_price_data(self, prices) -> PowerPriceData:
        """Process the raw price data into PowerPriceData structure."""
        price_data = PowerPriceData()
        missing_hours = []

        for price_entry in prices:
            try:
                # Convert UTC timestamp to local time
                utc_time = datetime.fromisoformat(price_entry["date"].replace('Z', '+00:00'))
                local_time = utc_time.astimezone(self.local_tz)
                
                # Calculate total price in EUR/kWh
                total_price = (price_entry["grossKwhPrice"] + price_entry["grossKwhTaxAndLevies"]) / 100
                
                price_data.add_entry(
                    timestamp=local_time,
                    price=round(total_price, 4)
                )
            except KeyError as e:
                _LOGGER.warning("Missing data in price entry: %s", e)
                missing_hours.append(local_time)
            except Exception as e:
                _LOGGER.error("Error processing price entry: %s", e)

        if missing_hours:
            _LOGGER.warning("Missing price data for hours: %s", missing_hours)

        return price_data

    async def _get_access_token(self):
        """Get access token with explicit UTC handling."""
        try:
            token_data = await get_access_token(self.client_id, self.client_secret, self.environment)
            self._access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self._token_expiration = datetime.now(ZoneInfo("UTC")) + timedelta(seconds=expires_in)
        except Exception as e:
            _LOGGER.error("Failed to get access token: %s", str(e))
            raise

    async def _fetch_prices(self):
        # Round to the nearest hour with milliseconds
        now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        url = f"https://{self._env_prefix}/spot-prices"
        
        headers = {
            "Authorization": f"Bearer {self._access_token}"
        }
        
        params = {
            "startDate": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00.000Z"),
            "endDate": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:00:00.000Z"),
            "resolution": "HOUR",
            "zip": self.zip_code
        }
        
        async with aiohttp.ClientSession() as session:
            _LOGGER.error(f"Fetching prices from {params['startDate']} to {params['endDate']}")
            _LOGGER.error(f"URL: {url}")
            _LOGGER.error(f"Headers: {headers}")
            _LOGGER.error(f"Params: {params}")
            async with session.get(url, headers=headers, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data["data"]

class OstromForecastSensor(CoordinatorEntity, SensorEntity):
    """Sensor for price forecasting."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "Ostrom Spot Price"
        self._attr_unique_id = f"ostrom_spot_price_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = "EUR/kWh"
        self._attr_should_poll = False
        self._attr_suggested_display_precision = 5

    @property
    def native_value(self) -> Optional[float]:
        """Return the current price."""
        if not self.coordinator.data:
            return None
        current_price = self.coordinator.data.get_current_price()
        return round(current_price, 4) if current_price is not None else None

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        
        # Add all prices (including future) as attributes
        attributes = {
            "prices": {
                k.isoformat(): round(v, 4) 
                for k, v in sorted(data.prices.items())  # Sort by timestamp
            },
            "average_price": round(data._avg_price, 4),
            "min_price": round(data._min_price, 4),
            "max_price": round(data._max_price, 4),
            "next_price": round(data.next_price, 4) if data.next_price else None,
            "lowest_price_time": data.lowest_price_time.isoformat() if data.lowest_price_time else None,
            "highest_price_time": data.highest_price_time.isoformat() if data.highest_price_time else None,
            "state_class": "measurement",
        }

        return attributes

class OstromAveragePriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for average price."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "Ostrom Average Price"
        self._attr_unique_id = f"ostrom_average_price_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "EUR/kWh"
        self._attr_suggested_display_precision = 5

    @property
    def native_value(self) -> Optional[float]:
        if not self.coordinator.data:
            return None
        return round(self.coordinator.data._avg_price, 4) if self.coordinator.data._avg_price else None

class OstromMinPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for minimum price."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "Ostrom Minimum Price"
        self._attr_unique_id = f"ostrom_min_price_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "EUR/kWh"
        self._attr_suggested_display_precision = 5

    @property
    def native_value(self) -> Optional[float]:
        if not self.coordinator.data:
            return None
        return round(self.coordinator.data._min_price, 4) if self.coordinator.data._min_price else None

class OstromMaxPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for maximum price."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "Ostrom Maximum Price"
        self._attr_unique_id = f"ostrom_max_price_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "EUR/kWh"
        self._attr_suggested_display_precision = 5

    @property
    def native_value(self) -> Optional[float]:
        if not self.coordinator.data:
            return None
        return round(self.coordinator.data._max_price, 4) if self.coordinator.data._max_price else None

class OstromNextPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for next hour's price."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "Ostrom Next Hour Price"
        self._attr_unique_id = f"ostrom_next_price_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "EUR/kWh"
        self._attr_suggested_display_precision = 5

    @property
    def native_value(self) -> Optional[float]:
        if not self.coordinator.data:
            return None
        return round(self.coordinator.data.next_price, 4) if self.coordinator.data.next_price else None

class OstromLowestPriceTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for lowest price time."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "Ostrom Lowest Price Time"
        self._attr_unique_id = f"ostrom_lowest_price_time_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> Optional[datetime]:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.lowest_price_time

class OstromHighestPriceTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for highest price time."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "Ostrom Highest Price Time"
        self._attr_unique_id = f"ostrom_highest_price_time_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> Optional[datetime]:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.highest_price_time