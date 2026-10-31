# Hot Water Tank Estimator

A Home Assistant custom integration that estimates how much hot water is left in a domestic hot water tank that
has no flow meter of its own.

It keeps a two-layer energy balance of the tank, with a hot layer above a cold one:
- water drawn, measured by a whole-house water meter, takes energy out;
- heat from the heater's energy counter or power sensor puts energy in;
- at the end of each heating run the tank is charged: all of it at the mean of the heater's flow and return
  temperature;
- the tank's own sensor, at the height you configure, shows how far the cold layer has risen;
- a rise in bathroom humidity tells mixed shower and bath water apart from other draws.

The integration fits its parameters to your tank: first from the recorder's history at setup, then at every heating
run end. Diagnostic sensors show what it learned and how well it fits.

It provides:

- tank water remaining: litres of tank water at the charged temperature;
- shower water remaining: litres of mixed water at your shower temperature;
- percent charged;
- shower minutes left;
- the charged temperature and the estimated tank average temperature;
- the cold water temperature used;
- a shower detected binary sensor and a "Shower ran cold" button;
- calibration diagnostics.

## Status

In development, not yet released. The plan and specification are in
`openspec/changes/add-hot-water-estimator/`.

## Requirements

- A tank temperature sensor, and its height in the tank (from the data sheet).
- A total water meter for the house (any volume unit), for example a HomeWizard Watermeter or a P1/pulse meter.
- At least one of:
  - a thermal energy counter for heating the tank;
  - a heat power sensor;
  - a binary sensor that is on while the tank is heating.
- Optional: the heater's flow and return temperatures, one or more bathroom humidity sensors, and a cold water
  temperature sensor.

## Installation

Planned: add this repository to HACS as a custom repository of type Integration, download it, restart Home
Assistant, then add "Hot Water Tank Estimator" under Settings, Devices and services.

## Development

See [docs/development.md](docs/development.md). `python scripts/lint.py` runs all checks with pinned tools.

## License

MIT, see [LICENSE](LICENSE).
