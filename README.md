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

## Configuration

Add the integration under Settings, Devices and services. Each tank is one entry with its own device, and a second
tank is a second entry. The config flow has five steps. The sensor fields offer entities of a suitable domain and
device class (the heating active binary sensor is filtered by domain only).

| Step | Field | Meaning |
|---|---|---|
| Tank | Name | The name of the device. |
| Tank | Tank volume | The effective volume of the tank in L, 20-2000. |
| Tank | Tank temperature sensor | The temperature sensor of the tank. |
| Tank | Sensor height | Where the sensor sits, in % of the tank height from the bottom, 20-80. Default 50. |
| Water meter | Water meter | The total water meter of the house. It needs a volume unit: L, m3, gal or ft3. |
| Heat input | Heat energy counter | The thermal energy counter of the heater (kWh, or another energy unit, which is converted). |
| Heat input | Heat power sensor | The heat power of the heater (W, or another power unit, which is converted). |
| Heat input | Heating active binary sensor | A binary sensor that is on while the tank is heated. |
| Heat input | Flow temperature sensor | The flow temperature of the heater. Give it with the return temperature. |
| Heat input | Return temperature sensor | The return temperature of the heater. Give it with the flow temperature. |
| Shower detection | Bathroom humidity sensors | One or more humidity sensors. A rise tells a shower or bath from other draws. |
| Cold water | Cold water temperature sensor | The cold supply water. Without it, a seasonal curve is used. |

At least one of the energy counter, the power sensor and the heating active binary sensor is needed. Without
flow and return, the tank sensor gives the charged temperature at the end of a heating run. A tank sensor can
belong to one entry only.

Temperature sensors in F or K are converted to C. Everything else has a default, so a fresh entry runs without
opening the options.

## Options

Open the options of the entry to change anything. The options flow has four steps. Saving reloads the entry and
keeps the model state (the tank average, the charged temperature and the draw session) and the calibration.

| Step | Field | Default | Meaning |
|---|---|---|---|
| Tank and temperatures | Tank volume, Tank temperature sensor, Sensor height | as set | As in the config flow. |
| Tank and temperatures | Thermocline width | 35 % | Width of the layer between hot and cold water. Learned. |
| Tank and temperatures | Usable fraction | 0.85 | Fraction of the tank that can be drawn before the outlet runs cold. Learned from the button. |
| Tank and temperatures | Shower mix temperature | 38 C | The temperature of your shower water. |
| Tank and temperatures | Maximum temperature | 95 C | The highest temperature the model accepts. |
| Tank and temperatures | Sensor tolerance | 1.5 K | How far below the charged temperature the sensor may read before the cold layer counts as reached. |
| Tank and temperatures | Sensor margin | 2 K | How far the tank average may stay above the value the sensor gives. |
| Tank and temperatures | Ambient temperature | 20 C | The temperature around the tank, for the standing loss. |
| Tank and temperatures | Cold water mean temperature | 12.5 C | Yearly mean of the cold water, used without a cold water sensor. |
| Tank and temperatures | Cold water amplitude | 5 K | Seasonal swing around the mean. |
| Tank and temperatures | Coldest day of the year | 46 | Day of the year with the coldest cold water. |
| Sources | Water meter and the optional sources | as set | As in the config flow. Clear a field to remove the source. |
| Draws, losses and heat | Loss coefficient | 0.004 per hour | Standing loss. Learned. |
| Draws, losses and heat | Other draws hot share | 0.2 | Share of the litres outside a shower that comes from the tank. Learned. |
| Draws, losses and heat | Start-up energy per run | 0 kWh | Energy of each run that does not reach the tank. Learned. |
| Draws, losses and heat | Shower flow | 7.5 L/min | Turns litres into minutes. |
| Draws, losses and heat | Humidity rise | 6 points | Rise above the lowest humidity of the window that counts as a shower. |
| Draws, losses and heat | Humidity window | 60 min | The window of that lowest value. |
| Draws, losses and heat | Long draw duration | 0 min | A draw this long counts as a shower. 0 is off. For homes without a humidity sensor. |
| Draws, losses and heat | Reclassify window | 10 min | Litres drawn this long before detection count as shower water. |
| Draws, losses and heat | Session gap | 60 s | Draws closer than this belong to one session. |
| Draws, losses and heat | Maximum draw per reading | 100 L | A larger rise of the meter in one reading is ignored. |
| Draws, losses and heat | Power threshold | 100 W | Heat power above this counts as heating. |
| Learning | Locked parameters | none | Parameters that keep their value from these options and are never learned. |
| Learning | Days of history for the setup fit | 30 days | History replayed at setup and by the recalibrate action, 1-30. |

## Entities

Each tank has one device with these entities. All names are translated.

| Entity | Unit | Meaning |
|---|---|---|
| Tank water remaining | L | Litres of tank water at the charged temperature that can still be drawn. |
| Shower water remaining | L | Litres of mixed water at the shower mix temperature that this makes. |
| Percent charged | % | The usable tank compared with the last charge. |
| Shower time remaining | min | Shower water divided by the shower flow. |
| Charged temperature | C | The temperature of the hot layer. |
| Tank average temperature | C | The estimated average temperature of the tank. |
| Cold water temperature | C | The cold water temperature in use: the sensor, or the seasonal curve. |
| Shower detected | | On while a shower or bath is detected. Unavailable when there are no humidity sensors and the long draw rule is off. |
| Shower ran cold | | Button. Press it when a shower ran cold earlier than predicted. |

The calibration diagnostic sensors are listed under "Diagnostic sensors" below.

## Actions

| Action | Fields | What it does |
|---|---|---|
| `hot_water_tank_estimator.set_tank_state` | Tank average, Charged temperature | Sets the temperatures by hand. With neither given, the tank is charged to the reading of the tank sensor, and the action fails if the sensor is unavailable. With only the average given, the charged temperature stays. |
| `hot_water_tank_estimator.recalibrate` | Days (1-30) | Fits the parameters again from the recorder history. Locked parameters and the usable fraction learned from the button stay. |

Both take a tank (an entity of the tank) as target. The temperatures of `set_tank_state` are in C.

## Calibration

The integration fits its parameters to your tank, so the defaults are only a start:
- At setup, and with the recalibrate action, it replays the recorder history of the sources (up to the history
  days) through the model, in the background. The fit reruns at each start until it has run once. Sources that
  are excluded from the recorder weaken it, and with no history the values stay at the options. The fit covers the
  other draws hot share, the start-up energy, the loss coefficient and the thermocline width. The share and the start-up
  energy need at least 5 heating runs in the history.
- The model of the tank itself starts from the tank sensor's reading, not from the end state of the replay.
- At the end of every heating run the run's energy shows how far the model was off at the start of the run. This
  needs an energy counter or a power sensor. The share, the start-up energy and the loss coefficient are refitted
  from the last runs. Each update moves a value by at most a quarter of its range.
- Quiet nights, with no draw and no heating, give the loss coefficient from the fall of the tank sensor.
- The first fall of the tank sensor after a charge gives the thermocline width.
- The "Shower ran cold" button sets the usable fraction to the current cold fraction and empties the model.
- A locked parameter keeps its value from the options and is never learned. Removing a lock discards what was
  learned before it.

The formulas and the reasons are in [docs/model.md](docs/model.md). The learned values are kept per entry, so they
survive restarts and reloads.

## Diagnostic sensors

These sensors have the diagnostic category, so they are hidden from dashboards by default.

| Sensor | Unit | Meaning |
|---|---|---|
| Other draws hot share | | The value in use. The `source` attribute says where it comes from: option, setup fit, learned or locked. |
| Start-up energy | kWh | The same, with its `source`. |
| Loss coefficient | 1/h | The same, with its `source`. |
| Thermocline width | % | The same, with its `source`. |
| Usable fraction | % | The same, with its `source`. |
| Calibration samples | | The number of heating runs stored for the fit. |
| Last charge error | K | The error of the model at the start of the last run. |
| Mean charge error | K | The mean absolute error over the last 10 runs. |

A mean charge error that rises, or errors that keep one sign, point to a wrong sensor height or a changed
household. Check the sensor height first. Download the diagnostics of the entry to see the options, the state,
which sources are available, the last 100 model events and every stored closure (heating run) with its status
and reason.

## Development

See [docs/development.md](docs/development.md). `python scripts/lint.py` runs all checks with pinned tools.

## License

MIT, see [LICENSE](LICENSE).
