# OStrom Price Monitoring

This integration allows you to monitor the price of electricity in your area. It pulls data from the Ostrom Energy API (https://production.ostrom-api.io/spot-prices) and displays it as sensors in Home Assistant. The documentation of the API can be found here: https://docs.ostrom-api.io/reference/api-access.

The API seems to provide prices until 11pm of that day. After 2pm it provides prices for up to 11pm of the day after.

This integration will poll the API every hour (full hour) and update the sensors accordingly.

## ⚙️ Sensors

![Ostrom Sensors](https://github.com/oliverwehrens/homeassistant_ostrom_integration/blob/main/images/ostrom_sensors.png?raw=true)

- OstromForecastSensor - current forecasted price
- OstromAveragePriceSensor - average price of the day
- OstromMinPriceSensor - lowest price of the day
- OstromMaxPriceSensor - highest price of the day
- OstromNextPriceSensor - next price of the day
- OstromLowestPriceTimeSensor - time of the lowest price of the day
- OstromHighestPriceTimeSensor - time of the highest price of the day

## 📈Charts

[thomsbe](https://github.com/thomsbe) added a nice apexcharts card. Thanks a lot for the '[Issue](https://github.com/oliverwehrens/homeassistant_ostrom_integration/issues/1)'.

```yaml
type: custom:apexcharts-card
graph_span: 23h
span:
  start: hour
  offset: "-1h"
header:
  title: Strompreise Zukunft(€/kWh)
  show: true
apex_config:
  xaxis:
    type: datetime
    labels:
      datetimeFormatter:
        hour: HH:mm
        day: dd MMM
  plotOptions:
    bar:
      colors:
        ranges:
          - from: 0
            to: 0.15
            color: "#2ecc71"
          - from: 0.15
            to: 0.2
            color: "#a6d96a"
          - from: 0.2
            to: 0.25
            color: "#ffff99"
          - from: 0.25
            to: 0.3
            color: "#fdae61"
          - from: 0.3
            to: 0.35
            color: "#f46d43"
          - from: 0.35
            to: 1
            color: "#d73027"
series:
  - entity: sensor.ostrom_energy_spotpreis
    attribute: prices
    float_precision: 3
    type: column
    name: Preis
    data_generator: |
      const prices = entity.attributes.prices;
      return Object.entries(prices).map(([timestamp, value]) => {
        const date = new Date(timestamp);
        return [date, value];
      });
    show:
      datalabels: false
      in_header: true
yaxis:
  - min: 0
    max: 0.5
```

```yaml
 type: custom:apexcharts-card
graph_span: 24h
header:
  title: Strompreise (€/kWh)
  show: true
apex_config:
  xaxis:
    type: datetime
    labels:
      datetimeFormatter:
        hour: HH:mm
        day: dd MMM
  plotOptions:
    bar:
      colors:
        ranges:
          - from: 0
            to: 0.15
            color: "#2ecc71"
          - from: 0.15
            to: 0.2
            color: "#a6d96a"
          - from: 0.2
            to: 0.25
            color: "#ffff99"
          - from: 0.25
            to: 0.3
            color: "#fdae61"
          - from: 0.3
            to: 0.35
            color: "#f46d43"
          - from: 0.35
            to: 1
            color: "#d73027"
series:
  - entity: sensor.ostrom_energy_spotpreis
    type: column
    name: Preis
    float_precision: 3
    group_by:
      duration: 1h
      func: avg
    show:
      datalabels: false
      in_header: false
yaxis:
  - min: 0
    max: 0.5
  ```

![](https://github.com/oliverwehrens/homeassistant_ostrom_integration/blob/main/images/chart1.png?raw=true)


## 🔐 Credentials

- You need to provide a client id and client secret to use this integration. You can get these from the Ostrom Developer Portal (https://developer.ostrom-api.io/).
![Ostrom Developer Portal](https://github.com/oliverwehrens/homeassistant_ostrom_integration/blob/main/images/ostrom_client.png?raw=true)

## 👨🏻‍🔧 Installation

### Via HACS

[Add to Home Assistant](https://my.home-assistant.io/redirect/hacs_repository/?owner=oliverwehrens&repository=homeassistant_ostrom_integration&category=integration)


Add it to HACS manually:

- Home Assistant → HACS > Integrations
- Top-right ⋮ → Custom repositories
- URL: https://github.com/oliverwehrens/homeassistant_ostrom_integration
- Category: Integration

### Manually

- Copy the `ostrom_integration` folder to your `config/custom_components` folder. 
  - You need to have access to the terminal in Home Assistant
 ```
cd /root/homeassistant/custom_components
git clone https://github.com/oliverwehrens/homeassistant_ostrom_integration.git   
```
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

## Questions ?

Contact me on [🦋Bluesky](https://bsky.app/profile/owehrens.com). 
