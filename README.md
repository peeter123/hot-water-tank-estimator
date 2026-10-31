# Hot Water Tank Estimator

A Home Assistant custom integration that estimates how much hot water is left in a domestic hot water tank that
has no flow meter of its own.

It keeps an energy balance of the tank. Water drawn, measured by a whole-house water meter, cools the tank. Heat
from the heater's energy counter or power sensor warms it. The tank's own temperature sensor anchors the estimate
at the end of each heating cycle and corrects it when the tank empties. A rise in bathroom humidity tells showers
and baths apart from other draws.

It provides:

- hot water remaining, in litres of water at your shower mix temperature;
- percent full;
- shower minutes left;
- the estimated tank average temperature;
- the cold water temperature used;
- a shower detected binary sensor.

## Status

In development, not yet released. The plan and specification are in
`openspec/changes/add-hot-water-estimator/`.

## Requirements

- A tank temperature sensor.
- A total water meter for the house (any volume unit), for example a HomeWizard Watermeter or a P1/pulse meter.
- At least one of:
  - a thermal energy counter for heating the tank;
  - a heat power sensor;
  - a binary sensor that is on while the tank is heating.
- Optional: one or more bathroom humidity sensors, a cold water temperature sensor, and a setpoint entity.

## Installation

Planned: add this repository to HACS as a custom repository of type Integration, download it, restart Home
Assistant, then add "Hot Water Tank Estimator" under Settings, Devices and services.

## License

MIT, see [LICENSE](LICENSE).
