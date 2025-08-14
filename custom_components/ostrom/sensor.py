import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging
from typing import Optional, Dict, Any, cast
import aiohttp
from homeassistant.components.sensor import (
    SensorEntity, SensorStateClass, SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity, DataUpdateCoordinator, UpdateFailed,
)
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy
from homeassistant.util import dt
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData, StatisticMetaData, StatisticMeanType
)
from homeassistant.components.recorder.statistics import (
    async_import_statistics, async_add_external_statistics,
    get_last_statistics, statistics_during_period)

from . import DOMAIN
from .auth import get_access_token
from homeassistant.helpers.entity import DeviceInfo

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL_MIN = 10  # Update more frequently for better graphs
MAX_DAYS_PER_REQUEST = 30 # Max days to use when fetching historical usage data

class PowerPriceData:
    """Stores power price data for forecasting."""
    def __init__(self, local_tz):
        self.prices = {}  # Dictionary of datetime -> price (UTC)
        self._min_price = None
        self._max_price = None
        self._avg_price = None
        self.current_price = None
        self.next_price = None
        self.lowest_price_time = None
        self.highest_price_time = None
        self.local_tz = local_tz

    def add_entry(self, timestamp: datetime, price: float) -> None:
        """Add a price entry and update statistics."""
        # Ensure timestamp is in UTC
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=ZoneInfo("UTC"))
        else:
            timestamp = timestamp.astimezone(ZoneInfo("UTC"))
        
        # Round to the start of the hour
        clean_timestamp = timestamp.replace(minute=0, second=0, microsecond=0)
        self.prices[clean_timestamp] = price
        self._update_statistics()

    def _update_statistics(self) -> None:
        """Update price statistics."""
        if not self.prices:
            return

        now = datetime.now(ZoneInfo("UTC")).replace(minute=0, second=0, microsecond=0)
        
        # Calculate statistics for all prices
        prices = list(self.prices.values())
        self._min_price = min(prices)
        self._max_price = max(prices)
        self._avg_price = sum(prices) / len(prices)
        
        # Get current and next price
        self.current_price = self.prices.get(now)
        next_hour = now + timedelta(hours=1)
        self.next_price = self.prices.get(next_hour)
        
        # Find times for min/max prices, ensuring we keep timezone info
        self.lowest_price_time = None
        self.highest_price_time = None
        for time, price in self.prices.items():
            if price == self._min_price and (self.lowest_price_time is None or time < self.lowest_price_time):
                self.lowest_price_time = time 
            if price == self._max_price and (self.highest_price_time is None or time < self.highest_price_time):
                self.highest_price_time = time 

        # change highest and lowest price time to local timezone
        self.lowest_price_time = self.lowest_price_time.astimezone(self.local_tz)
        self.highest_price_time = self.highest_price_time.astimezone(self.local_tz)

    def get_current_price(self) -> Optional[float]:
        """Get the current hour's price."""
        now = datetime.now(ZoneInfo("UTC")).replace(minute=0, second=0, microsecond=0)
        return self.prices.get(now)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Ostrom sensor platform."""
    coordinator = OstromDataCoordinator(hass, entry)
    
    # Create entities first
    entities = [
        OstromForecastSensor(coordinator, entry),
        OstromAveragePriceSensor(coordinator, entry),
        OstromMinPriceSensor(coordinator, entry),
        OstromMaxPriceSensor(coordinator, entry),
        OstromNextPriceSensor(coordinator, entry),
        OstromLowestPriceTimeSensor(coordinator, entry),
        OstromHighestPriceTimeSensor(coordinator, entry),
    ]
    
    # Add entities before the first refresh
    async_add_entities(entities)
    
    # Schedule the first refresh instead of waiting for it
    await coordinator.async_refresh()

class OstromDataCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch Ostrom price data."""
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize coordinator."""
        # Calculate time until next hour
        now = dt.now()
        next_hour = (now + timedelta(minutes=SCAN_INTERVAL_MIN)).replace(minute=0, second=0, microsecond=0)
        # Set initial update interval to time until next hour
        initial_update_interval = (next_hour - now).total_seconds()

        super().__init__(
            hass,
            _LOGGER,
            name="Ostrom Price Data",
            update_interval=timedelta(seconds=initial_update_interval),
        )
        self.client_id = entry.data["client_id"]
        self.client_secret = entry.data["client_secret"]
        self.zip_code = entry.data["zip_code"]
        self.environment = entry.data["environment"]
        self._access_token = None
        self._token_expiration = None
        self._env_prefix = "sandbox.ostrom-api.io" if self.environment == "sandbox" else "production.ostrom-api.io"
        self.local_tz = ZoneInfo(hass.config.time_zone)
        
        # Add device info
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Ostrom Energy",
            manufacturer="Ostrom API",
            model="Price Monitoring",
            sw_version="0.8",
        )
        self.contract_id = None

    async def _async_update_data(self) -> PowerPriceData:
        """Fetch and process price data with proper error handling."""
        try:
            _LOGGER.debug("Starting data update for Ostrom integration")
            
            # After each update, set the update interval to 1 hour
            self.update_interval = timedelta(minutes=SCAN_INTERVAL_MIN)
            
            if not self._access_token or datetime.now(ZoneInfo("UTC")) >= self._token_expiration:
                _LOGGER.info("Access token expired or missing, requesting new token")
                await self._get_access_token()

            raw_data = await self._fetch_prices()
            processed_data = self._process_price_data(raw_data)
            
            if self.contract_id is None:
                self.contract_id = await self._fetch_contracts()
            
            await self._fetch_historical_data_if_needed()

            _LOGGER.debug("Successfully updated Ostrom price data")
            return processed_data
        except Exception as err:
            _LOGGER.error("Error updating Ostrom price data: %s", err, exc_info=True)
            raise UpdateFailed(f"Error fetching data: {err}") from err

    def _process_price_data(self, prices) -> PowerPriceData:
        """Process the raw price data into PowerPriceData structure."""
        price_data = PowerPriceData(self.local_tz)

        for price_entry in prices:
            try:
                # Parse timestamp and ensure UTC timezone
                timestamp = datetime.fromisoformat(price_entry["date"].replace('Z', '+00:00'))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=ZoneInfo("UTC"))
                else:
                    timestamp = timestamp.astimezone(ZoneInfo("UTC"))

                total_price = (price_entry["grossKwhPrice"] + price_entry["grossKwhTaxAndLevies"]) / 100
                
                price_data.add_entry(
                    timestamp=timestamp,
                    price=round(total_price, 4)
                )
            except Exception as e:
                _LOGGER.error("Error processing price entry: %s", e)

        return price_data

    async def _get_access_token(self):
        """Get access token."""
        try:
            token_data = await get_access_token(self.client_id, self.client_secret, self.environment)
            self._access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self._token_expiration = datetime.now(ZoneInfo("UTC")) + timedelta(seconds=expires_in)
        except Exception as e:
            _LOGGER.error("Failed to get access token: %s", str(e))
            raise

    async def _fetch_prices(self):
        """Fetch price data including future prices."""
        now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        url = f"https://{self._env_prefix}/spot-prices"
        
        headers = {"Authorization": f"Bearer {self._access_token}"}
        params = {
            "startDate": (now).strftime("%Y-%m-%dT%H:00:00.000Z"),  
            "endDate": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:00:00.000Z"),
            "resolution": "HOUR",
            "zip": self.zip_code
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data["data"]

    async def _fetch_contracts(self):
        """Fetch available contracts and get the first electricity contract ID."""
        url = f"https://{self._env_prefix}/contracts"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()

                # Find the first active electricity contract
                for contract in data.get("data", []):
                    if (
                        contract.get("type") == "ELECTRICITY"
                        and contract.get("status") == "ACTIVE"
                    ):
                        return contract.get("id")

                return None

    def _calculate_end_time(self, delta_hours: int = 24) -> datetime:
        """Calculate end time based on current time minus delta hours, rounded to hour."""
        now = datetime.now(self.local_tz)
        end_time = now - timedelta(hours=delta_hours)
        return end_time.replace(minute=0, second=0, microsecond=0)

    async def _fetch_consumption(self, start_datetime=None, end_datetime=None):
        """Fetch energy consumption data for a specific time range."""
        if not self.contract_id:
            _LOGGER.warning("No contract ID available for consumption data")
            return None

        # Calculate default start and end times if not provided
        if start_datetime is None or end_datetime is None:
            end_time = self._calculate_end_time(24)  # 24h ago from now
            start_time = end_time - timedelta(hours=1)  # 1 hour before end_time

            if start_datetime is None:
                start_datetime = start_time
            if end_datetime is None:
                end_datetime = end_time

        # Ensure both datetimes are in UTC
        if start_datetime.tzinfo is None:
            start_datetime = start_datetime.replace(tzinfo=self.local_tz)
        else:
            start_datetime = start_datetime.astimezone(self.local_tz)

        if end_datetime.tzinfo is None:
            end_datetime = end_datetime.replace(tzinfo=self.local_tz)
        else:
            end_datetime = end_datetime.astimezone(self.local_tz)

        url = f"https://{self._env_prefix}/contracts/{self.contract_id}/energy-consumption"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        params = {
            "startDate": start_datetime.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "endDate": end_datetime.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "resolution": "HOUR",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data

    async def _store_usage_to_stats(self, consumption_data, initial_sum = 0):
        """Process historical consumption data and add hourly statistics to recorder."""
        # if not isinstance(consumption_data, dict) or "data" not in consumption_data:
        #     return

        # hourly_data = consumption_data["data"]
        hourly_data = consumption_data
        if not isinstance(hourly_data, list) or len(hourly_data) == 0:
            return

        # Create statistics for hourly consumption
        statistic_id = f"{DOMAIN}:ostrom_hourly_consumption_energy"

        # Prepare statistics data - each hour is an individual measurement
        statistics = []
        sum_overall = initial_sum
        
        for entry in hourly_data:
            if not isinstance(entry, dict) or "date" not in entry or "kWh" not in entry:
                continue

            try:
                # Parse timestamp
                date_str = entry["date"]
                if date_str.endswith("Z"):
                    date_str = date_str[:-1] + "+00:00"
                timestamp = datetime.fromisoformat(date_str)
                # Ensure timestamp has timezone info
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=self.local_tz)
                else:
                    timestamp = timestamp.astimezone(self.local_tz)
                    
                # Each hour's consumption as individual statistic
                kwh = cast(float, entry["kWh"])
                sum_overall = sum_overall + (kwh * 1000)  # Convert kWh to Wh for statistics
                
                # Create statistic data point for this hour's consumption
                # _LOGGER.debug("Creating statistic data point for %s: %s kWh : %s Wh", timestamp, kwh, sum_overall)

                statistics.append(
                    StatisticData(
                        start=timestamp,
                        state=kwh,
                        sum=sum_overall,  # Use sum for energy consumption
                    )
                )

            except Exception as e:
                _LOGGER.warning("Error processing consumption entry: %s", e)

        if statistics:
            # Add statistics to recorder
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name="Ostrom Hourly Energy Consumption",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            )

            try:
                async_add_external_statistics(self.hass, metadata, statistics)
                _LOGGER.warning(
                    "Added %d hourly consumption statistics", len(statistics)
                )
            except Exception as e:
                _LOGGER.error("Failed to add hourly statistics: %s", e)

    async def _fetch_data_in_chunks(self, start_time, end_time, max_days_per_chunk):
        """Fetch data in chunks of maximum max_days_per_chunk days."""
        current_start = start_time
        consumption_data_all = []
        _LOGGER.warning("Fetching data in chunks from %s to %s", current_start, end_time)

        while current_start < end_time:
            # Calculate chunk end time (max_days_per_chunk days after current_start or end_time, whichever is smaller)
            chunk_end = min(
                (current_start + timedelta(days=max_days_per_chunk)).replace(hour=23, minute=59, second=59, microsecond=0), end_time
            )

            try:
                _LOGGER.warning("Fetching data chunk from %s to %s", current_start, chunk_end)
                # Fetch data for this chunk
                consumption_data = await self._fetch_consumption(
                    current_start, chunk_end
                )

                if consumption_data and consumption_data.get("data"):
                    # Count hours fetched
                    hourly_data = consumption_data["data"]
                    consumption_data_all.extend(hourly_data)

                    _LOGGER.warning(
                        "Fetched %d hours of delta data from %s to %s",
                        len(hourly_data),
                        current_start,
                        chunk_end,
                    )

                # Move to the next chunk
                current_start = chunk_end

            except Exception as e:
                _LOGGER.warning(
                    "Error fetching delta chunk from %s to %s: %s",
                    current_start,
                    chunk_end,
                    e,
                )
                # Move to next chunk even if this one failed
                current_start = chunk_end

            # Avoid throttling
            await asyncio.sleep(3)

        return consumption_data_all

    async def _fetch_historical_data_if_needed(self):
        """Check if historical data exists and fetch missing data walking backwards from yesterday."""
        if not self.contract_id:
            _LOGGER.warning("No contract ID available for historical data fetching")
            return

        try:
            _LOGGER.debug("Fetching historical data for %s", self.contract_id)

            # Check if we have any statistics for this sensor
            statistic_id = f"{DOMAIN}:ostrom_hourly_consumption_energy"

            # Get the last recorded statistic to see what data we already have
            recorder = get_instance(self.hass)
            last_stats = await recorder.async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, True, set()
            )
            
            end_time = self._calculate_end_time(24)  # 24h ago from now
            
            consumption_sum = 0.0
            last_stats_time = None
            consumption_data_all = []
            
            if not last_stats:
                _LOGGER.debug("Updating statistic for the first time")
                # usage = await self._async_get_energy_usage(meter)
                consumption_sum = 0.0
                last_stats_time = None
                
                # Start from end_time and go backwards in chunks
                current_end = end_time

                while True:
                    # Calculate chunk start time
                    chunk_start = current_end - timedelta(days=30) # 1 months chunks
                    
                    # Set always chunk_start to start of day
                    chunk_start = chunk_start.replace(hour=0, minute=0, second=0, microsecond=0)

                    try:
                        # Fetch data for this chunk
                        consumption_data = await self._fetch_data_in_chunks(
                            chunk_start, current_end, MAX_DAYS_PER_REQUEST
                        )
                        if len(consumption_data) == 0:
                            break;

                        consumption_data_all.extend(consumption_data)

                        _LOGGER.debug(
                            "Fetched %d hours of data from %s to %s",
                            len(consumption_data),
                            chunk_start,
                            current_end,
                        )

                        # Move to the next chunk (earlier time period)
                        current_end = chunk_start

                    except Exception as e:
                        _LOGGER.error(
                            "Error fetching historical chunk from %s to %s: %s",
                            chunk_start,
                            current_end,
                            e,
                        )
                        break
                # Sort consumption data by timestamp
                consumption_data_all.sort(key=lambda x: x["date"])
                
            else:
                last_stat_entry = list(last_stats.values())[0][
                    0
                ]  # First (and only) statistic entry
                last_stats_time = last_stat_entry["start"]
                
                # Convert timestamp to datetime if it's a float/int
                if isinstance(last_stats_time, (int, float)):
                    last_stats_time = datetime.fromtimestamp(last_stats_time, tz=self.local_tz)
                elif isinstance(last_stats_time, datetime):
                    # Convert to UTC for API call
                    if last_stats_time.tzinfo is None:
                        last_stats_time = last_stats_time.replace(tzinfo=self.local_tz)
                else:
                    # Fallback: parse as ISO string if it's a string
                    if isinstance(last_stats_time, str):
                        last_stats_time = datetime.fromisoformat(last_stats_time)
                        if last_stats_time.tzinfo is None:
                            last_stats_time = last_stats_time.replace(tzinfo=self.local_tz)
                _LOGGER.debug("Using last recorded time: %s", last_stats_time)
                # def statistics_during_period(
                #     hass: HomeAssistant,
                #     start_time: datetime,
                #     end_time: datetime | None,
                #     statistic_ids: set[str] | None,
                #     period: Literal["5minute", "day", "hour", "week", "month"],
                #     units: dict[str, str] | None,
                #     types: set[Literal["change", "last_reset", "max", "mean", "min", "state", "sum"]],
                # ) -> dict[str, list[StatisticsRow]]
                stats = await recorder.async_add_executor_job(
                    statistics_during_period,
                    self.hass,
                    last_stats_time,
                    None,
                    {statistic_id},
                    "hour",
                    None,
                    {"sum"},
                )
                consumption_sum = cast(float, stats[statistic_id][0]["sum"])
                start_time = last_stats_time.astimezone(self.local_tz) - timedelta(hours=1)
            
                # Fetch data from last recorded time to end_time in chunks
                consumption_data_all = await self._fetch_data_in_chunks(
                    start_time, end_time, MAX_DAYS_PER_REQUEST
                )
                
            # Store the fetched data
            await self._store_usage_to_stats(consumption_data_all, initial_sum=consumption_sum)

        except Exception as e:
            _LOGGER.error("Error in historical data fetching: %s", e)


class OstromForecastSensor(CoordinatorEntity, SensorEntity):
    """Sensor for price forecasting."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "ostrom_integration_spot_price"
        self._attr_unique_id = f"ostrom_spot_price_{entry.data['zip_code']}"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_should_poll = False
        self._attr_suggested_display_precision = 2
        self._attr_device_info = coordinator.device_info

    @property
    def force_update(self) -> bool:
        """Force update for every update interval."""
        return True

    @property
    def state_attributes(self):
        """Return the state attributes."""
        attrs = super().state_attributes or {}
        attrs["last_reset"] = None
        return attrs

    @property
    def native_value(self) -> Optional[float]:
        """Return the current price."""
        if not self.coordinator.data:
            return None
        current_price = self.coordinator.data.get_current_price()
        return round(current_price, 4) if current_price is not None else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        
        # Add all prices to attributes for easy querying
        prices = {}
        for timestamp, price in data.prices.items():
            # Convert UTC to local time for easier use in automations
            local_time = timestamp.astimezone(self.coordinator.local_tz)
            prices[local_time.isoformat()] = round(price, 4)

        attributes = {
            "average_price": round(data._avg_price, 4),
            "min_price": round(data._min_price, 4),
            "max_price": round(data._max_price, 4),
            "next_price": round(data.next_price, 4) if data.next_price else None,
            "lowest_price_time": data.lowest_price_time.astimezone(self.coordinator.local_tz).isoformat() if data.lowest_price_time else None,
            "highest_price_time": data.highest_price_time.astimezone(self.coordinator.local_tz).isoformat() if data.highest_price_time else None,
            "prices": prices,  # Add all prices
            "current_hour": datetime.now(self.coordinator.local_tz).strftime("%H:00"),
        }

        return attributes

    def get_price_at_time(self, time_str: str) -> Optional[float]:
        """Get price for a specific time (format: HH:MM)."""
        if not self.coordinator.data:
            return None

        try:
            # Parse the time string
            now = datetime.now(self.coordinator.local_tz)
            hour, minute = map(int, time_str.split(':'))
            target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # If the time is in the past for today, assume tomorrow
            if target_time < now:
                target_time += timedelta(days=1)

            # Convert to UTC for lookup
            utc_time = target_time.astimezone(ZoneInfo("UTC"))
            utc_time = utc_time.replace(minute=0)  # Round to hour

            return self.coordinator.data.prices.get(utc_time)
        except (ValueError, TypeError):
            return None

    def is_price_below(self, price_threshold: float, time_str: Optional[str] = None) -> bool:
        """Check if price is below threshold at given time or current time."""
        if time_str:
            price = self.get_price_at_time(time_str)
        else:
            price = self.native_value
            
        if price is None:
            return False
            
        return price <= price_threshold

class OstromAveragePriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for average price."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "ostrom_integration_average_price"
        self._attr_unique_id = f"ostrom_average_price_{entry.data['zip_code']}"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_suggested_display_precision = 2
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> Optional[float]:
        if not self.coordinator.data:
            return None
        return round(self.coordinator.data._avg_price, 4) if self.coordinator.data._avg_price else None

class OstromMinPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for minimum price."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "ostrom_integration_lowest_price"
        self._attr_unique_id = f"ostrom_min_price_{entry.data['zip_code']}"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_suggested_display_precision = 2
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> Optional[float]:
        if not self.coordinator.data:
            return None
        return round(self.coordinator.data._min_price, 4) if self.coordinator.data._min_price else None

class OstromMaxPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for maximum price."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "ostrom_integration_highest_price"
        self._attr_unique_id = f"ostrom_max_price_{entry.data['zip_code']}"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_suggested_display_precision = 2
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> Optional[float]:
        if not self.coordinator.data:
            return None
        return round(self.coordinator.data._max_price, 4) if self.coordinator.data._max_price else None

class OstromNextPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for next hour's price."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "ostrom_integration_next_hour_price"
        self._attr_unique_id = f"ostrom_next_price_{entry.data['zip_code']}"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_suggested_display_precision = 2
        self._attr_device_info = coordinator.device_info
        self.entity_id = f"sensor.{DOMAIN}_{self._attr_translation_key}"

    @property
    def native_value(self) -> Optional[float]:
        if not self.coordinator.data:
            return None
        return round(self.coordinator.data.next_price, 4) if self.coordinator.data.next_price else None

class OstromLowestPriceTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for lowest price time."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"ostrom_lowest_price_time_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = coordinator.device_info
        self._attr_entity_registry_enabled_default = True
        self._attr_has_entity_name = True
        self._attr_translation_key = "ostrom_integration_lowest_price_time"

    @property
    def native_value(self) -> Optional[datetime]:
        """Return the lowest price time in the device's local timezone."""
        if not self.coordinator.data or not self.coordinator.data.lowest_price_time:
            return None
        
        # Ensure UTC timezone if not set
        time = self.coordinator.data.lowest_price_time
        if time.tzinfo is None:
            time = time.replace(tzinfo=ZoneInfo("UTC"))
            
        # Convert to local timezone
        return time.astimezone(self.coordinator.local_tz)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return formatted time as an attribute."""
        if not self.native_value:
            return {}
            
        local_time = self.native_value
        return {
            "formatted_time": local_time.strftime("%I:%M %p"),
            "time_date": local_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "is_today": local_time.date() == datetime.now(self.coordinator.local_tz).date(),
            "is_tomorrow": local_time.date() == (datetime.now(self.coordinator.local_tz) + timedelta(days=1)).date()
        }

class OstromHighestPriceTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for highest price time."""
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"ostrom_highest_price_time_{entry.data['zip_code']}"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = coordinator.device_info
        self._attr_entity_registry_enabled_default = True
        self._attr_has_entity_name = True
        self._attr_translation_key = "ostrom_integration_highest_price_time"

    @property
    def native_value(self) -> Optional[datetime]:
        """Return the highest price time in the device's local timezone."""
        if not self.coordinator.data or not self.coordinator.data.highest_price_time:
            return None
        
        # Ensure UTC timezone if not set
        time = self.coordinator.data.highest_price_time
        if time.tzinfo is None:
            time = time.replace(tzinfo=ZoneInfo("UTC"))
            
        # Convert to local timezone
        return time.astimezone(self.coordinator.local_tz)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return formatted time as an attribute."""
        if not self.native_value:
            return {}
            
        local_time = self.native_value
        return {
            "formatted_time": local_time.strftime("%I:%M %p"),
            "time_date": local_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "is_today": local_time.date() == datetime.now(self.coordinator.local_tz).date(),
            "is_tomorrow": local_time.date() == (datetime.now(self.coordinator.local_tz) + timedelta(days=1)).date()
        }