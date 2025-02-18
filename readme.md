# OStrom Price Monitoring

This integration allows you to monitor the price of electricity in your area. It pulls data from the Ostrom Energy API (https://production.ostrom-api.io/spot-prices) and displays it as sensors in Home Assistant. The documentation of the API can be found here: https://ostrom-api.readme.io/reference/.

The API seems to provides prices until 11pm of that day. After 2pm it provides prices for up to 11pm of the day after.

This integration will poll the API every hour (full hour) and update the sensors accordingly.

## 📈 Sensors

![Ostrom Sensors](https://github.com/oliverwehrens/homeassistant_ostrom_integration/blob/main/images/ostrom_sensors.png?raw=true)

- OstromForecastSensor - current forecasted price
- OstromAveragePriceSensor - average price of the day
- OstromMinPriceSensor - lowest price of the day
- OstromMaxPriceSensor - highest price of the day
- OstromNextPriceSensor - next price of the day
- OstromLowestPriceTimeSensor - time of the lowest price of the day
- OstromHighestPriceTimeSensor - time of the highest price of the day

## 🔐 Credentials

- You need to provide a client id and client secret to use this integration. You can get these from the Ostrom Developer Portal (https://developer.ostrom-api.io/).
![Ostrom Developer Portal](https://github.com/oliverwehrens/homeassistant_ostrom_integration/blob/main/images/ostrom_client.png?raw=true)

## 👨🏻‍🔧 Installation

- Copy the `ostrom_integration` folder to your `config/custom_components` folder.
- Restart Home Assistant.
- Configure the integration in the Home Assistant configuration.
- Use your client id, client secret and Zip Codefrom the Ostrom Developer Portal to configure the client

### 📝 Configuration YAML

This is not tested yet :).

```yaml
ostrom_integration:
  client_id: "your_client_id"
  client_secret: "your_client_secret"
  zip_code: "your_zip_code"
```


## 📋 TODO

- Add the forecasted price as statistic diagram, not only as attributes of the sensor.

## ❤️ Pull Request

Are welcome!

## 🪪 License

This project is licensed under the MIT License. See the LICENSE file for details.

## Other Integrations

Not tested yet.

- https://github.com/ChrisCarde/homeassistant-ostrom
- https://github.com/melmager/ha_ostrom
