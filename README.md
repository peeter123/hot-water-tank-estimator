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

- hot water remaining: litres of tank water at the charged temperature;
- shower water remaining: litres of mixed water at your shower temperature;
- charge level, in percent of the last charge;
- shower minutes left;
- the charged temperature and the estimated tank average temperature;
- the cold water temperature used;
- the standing heat loss of the tank, in W;
- a shower detected binary sensor and a "Shower ran cold" button;
- calibration diagnostics.

## What it is for

Typical uses: show on a dashboard whether there is enough hot water for another shower, see how many minutes of
shower are left, and compare the tank before and after a heating run or a price block. The integration only
displays; it does not control the heater. It needs no tank flow meter, only sensors you probably have already.

## Requirements

- A tank temperature sensor, and its height in the tank (from the data sheet).
- A total water meter for the house (any volume unit), for example a HomeWizard Watermeter or a P1/pulse meter.
- At least one of:
  - a thermal energy counter for heating the tank;
  - a heat power sensor;
  - a binary sensor that is on while the tank is heating.
- Optional: the heater's flow and return temperatures, one or more bathroom humidity sensors, a cold water
  temperature sensor, and an ambient temperature sensor for the air around the tank.

## Installation

Home Assistant 2026.10 or newer is needed.

Through HACS:
1. In HACS, open the menu, choose Custom repositories, and add `https://github.com/peeter123/hot-water-tank-estimator`
   with the type Integration.
2. Search for "Hot Water Tank Estimator" in HACS and download it.
3. Restart Home Assistant.
4. Add "Hot Water Tank Estimator" under Settings, Devices and services, Add integration.

By hand: copy the folder `custom_components/hot_water_tank_estimator` of this repository into the
`custom_components` folder of your Home Assistant configuration, restart Home Assistant, and add the integration as
in step 4.

## Configuration

Add the integration under Settings, Devices and services. Each tank is one entry with its own device, and a second
tank is a second entry. The config flow has five steps. The sensor fields offer entities of a suitable domain and
device class (the heating active binary sensor is filtered by domain only).

| Step | Field | Meaning |
|---|---|---|
| Tank | Name | The name of the device. |
| Tank | Tank volume | The effective volume of the tank in L, 20-2000. |
| Tank | Tank temperature sensor | The temperature sensor of the tank. |
| Tank | Sensor height | Where the sensor sits, in % of the water volume below it, 20-80. Default 50. See "Finding the sensor height". |
| Water meter | Water meter | The total water meter of the house. It needs a volume unit: L, m3, gal or ft3. |
| Heat input | Heat energy counter | The thermal energy counter of the heater (kWh, or another energy unit, which is converted). |
| Heat input | Heat power sensor | The heat power of the heater (W, or another power unit, which is converted). |
| Heat input | Heating active binary sensor | A binary sensor that is on while the tank is heated. |
| Heat input | Flow temperature sensor | The flow temperature of the heater. Give it with the return temperature. |
| Heat input | Return temperature sensor | The return temperature of the heater. Give it with the flow temperature. |
| Shower detection | Bathroom humidity sensors | One or more humidity sensors. A rise tells a shower or bath from other draws. |
| Temperatures | Cold water temperature sensor | The cold supply water. Without it, a seasonal curve is used. |
| Temperatures | Ambient temperature sensor | The air around the tank, for the standing loss. Without it, the Ambient temperature of the options is used. See "Ambient temperature sensor". |

At least one of the energy counter, the power sensor and the heating active binary sensor is needed. Without
flow and return, the tank sensor gives the charged temperature at the end of a heating run. A tank sensor can
belong to one entry only.

Temperature sensors in F or K are converted to C. Everything else has a default, so a fresh entry runs without
opening the options.

### Reconfiguring

To change the tank or its sources later, open the entry under Settings, Devices and services, choose the three dots
and Reconfigure. One form shows the tank volume, the tank sensor, the sensor height and all the sources, with the same
checks as the setup. It is the only place to change the volume, the tank sensor, the water meter and the heat
inputs. A tank sensor that another entry uses is refused. The entry, its device, the model state and the
calibration stay, and the entry reloads. The tuning values are in the options. Adding, removing or replacing the
ambient sensor here starts a recalibration in the background.

### Finding the sensor height

The height is the share of the tank's water that lies below the sensor. A connection height in the data sheet is
measured from the floor, and the water column starts above it (base, bottom insulation, dished bottom), so a plain
ratio to the outer height overstates it. Use the bottom and the top of the water column instead. (The empty and filled
weights give the water volume, and with the inner diameter the height of the water column, so its bottom.) For
example, a tank 1700 mm high has its water from 150 mm to 1650 mm, and the sensor sleeve is at 1000 mm. That is
(1000 - 150) / (1650 - 150) = 850 / 1500 = 0.57, so enter 57, while the plain 1000 / 1700 would give 59. A wrong
height shows as a bias in the charge errors of the diagnostic
sensors.

## Options

Open the options of the entry to change the tuning. The options flow has four steps. The tank volume, the tank sensor,
the water meter and the heat inputs are not in it: they change in Reconfigure (see Configuration). Saving reloads the
entry and keeps the model state (the tank average, the charged temperature and the draw session) and the calibration.

| Step | Field | Default | Meaning |
|---|---|---|---|
| Tank and temperatures | Sensor height | as set | As in the config flow. |
| Tank and temperatures | Thermocline width | 35 % | Width of the layer between hot and cold water. Learned. |
| Tank and temperatures | Usable fraction | 0.85 | Fraction of the tank that can be drawn before the outlet runs cold. Learned from the button. |
| Tank and temperatures | Shower mix temperature | 38 C | The temperature of your shower water. |
| Tank and temperatures | Maximum temperature | 95 C | The highest temperature the model accepts. |
| Tank and temperatures | Sensor tolerance | 1.5 K | How far below the charged temperature the sensor may read before the cold layer counts as reached. |
| Tank and temperatures | Sensor margin | 2 K | How far the tank average may stay above the value the sensor gives. |
| Tank and temperatures | Ambient temperature | 20 C | The temperature around the tank, for the standing loss. Used without an ambient sensor, and when the sensor has been unavailable longer than the fallback time. |
| Tank and temperatures | Ambient sensor fallback time | 3 h | How long the last ambient sensor reading stays in use after the sensor becomes unavailable, 0-24. |
| Tank and temperatures | Cold water mean temperature | 12.5 C | Yearly mean of the cold water, used without a cold water sensor. |
| Tank and temperatures | Cold water amplitude | 5 K | Seasonal swing around the mean. |
| Tank and temperatures | Coldest day of the year | 46 | Day of the year with the coldest cold water. |
| Sources | Flow and return temperature sensors, Bathroom humidity sensors, Cold water temperature sensor, Ambient temperature sensor | as set | As in the config flow. Clear a field to remove the source. Give flow and return together. Adding, removing or replacing the ambient sensor starts a recalibration in the background. |
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
| Hot water remaining | L | Litres of tank water at the charged temperature that can still be drawn. |
| Shower water remaining | L | Litres of mixed water at the shower mix temperature that this makes. |
| Charge level | % | The usable tank compared with the last charge. |
| Shower time remaining | min | Shower water divided by the shower flow. |
| Charged temperature | C | The temperature of the hot layer. |
| Tank average temperature | C | The estimated average temperature of the tank. |
| Cold water temperature | C | The cold water temperature in use: the sensor, or the seasonal curve. |
| Heat loss | W | The standing heat loss of the tank: the loss coefficient times the tank's heat capacity times the excess of the tank average over the ambient temperature in use. 0 W at or below the ambient temperature. |
| Shower detected | | On while a shower or bath is detected. Unavailable when there are no humidity sensors and the long draw rule is off. |
| Shower ran cold | | Button. Press it when a shower ran cold earlier than predicted. |

The calibration diagnostic sensors are listed under "Diagnostic sensors" below.

## Why the hot water remaining is less than the tank volume

Right after a charge the estimate counts the whole tank as charged, at the charged temperature, yet hot water
remaining shows less than the tank volume. Only the usable fraction of the tank can be drawn hot:
- as water is drawn, cold water enters at the bottom and mixes into a lukewarm layer, so the outlet runs lukewarm
  before all the hot water has been replaced;
- with a heating coil low in the tank, the water below the coil is colder and cannot be drawn hot.

The usable fraction covers both. It is a setting that is learned from the "Shower ran cold" button, not measured. Charge
level compares the usable tank with the last charge, so it is 100 % right after any charge, whatever the heater reached.
The litres show the absolute amount.

## Supported heat sources

A tank heated by a heater that circulates the whole tank is supported, and so is a coil low in the tank. A coil or
element high up in the tank, or a second heat source such as an electric element next to the heater, is not
supported yet: the estimate then does not know that the heat goes into the upper part only.

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
- Quiet nights, with no draw and no heating, give the loss coefficient from the fall of the tank sensor, against the
  mean ambient temperature of the night.
- Adding, removing or replacing the ambient sensor (in the options or in Reconfigure) recalibrates the tank in the
  background after the reload, because the loss coefficient fitted against a sensor is not the one fitted against
  the fixed ambient temperature. The tank average and the charged temperature are kept.
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
| Calibration samples | | The number of valid heating runs (closures) in the fit. Sensor starts and excluded runs are not counted. The first heating run after adding an entry is a sensor start, so it does not raise the count. |
| Last charge error | K | The error of the model at the start of the last run. |
| Mean charge error | K | The mean absolute error over the last 10 runs. |

A mean charge error that rises, or errors that keep one sign, point to a wrong sensor height or a changed
household. Check the sensor height first. Download the diagnostics of the entry to see the options, the state,
which sources are available, the last 100 model events and every stored closure (heating run) with its status
and reason.

## How the estimate updates

Nothing is polled. Every state change of a source (water meter, tank sensor, heat input, humidity, cold water,
ambient) goes to the model at once, and a 5-minute timer lets the standing loss and the cold layer move when nothing
changes. The entities update after each of those. The model state and the calibration are stored per entry every
minute or so and at shutdown, so a restart continues where it stopped.

## The model in short

The tank is a hot layer above a cold one, with a thermocline between them:
- a heating run charges the whole tank to the charged temperature;
- water drawn takes energy out, counted from the litres on the water meter and the cold water temperature;
- the standing loss slowly cools the tank;
- the tank sensor at its height gives a bound: once the cold layer reaches it, the estimate cannot show more water
  than the sensor allows;
- the usable fraction of the tank is what can be drawn before the outlet runs lukewarm.

Every formula, unit, default and the reason for it is in [docs/model.md](docs/model.md).

## Ambient temperature sensor

An ambient temperature sensor is optional and replaces the fixed Ambient temperature of the options in the standing
loss, in the quiet nights that give the loss coefficient, and in the Heat loss sensor. Without one, a room that is
not at 20 C biases the loss coefficient and the heat loss a little.
- **Where to put it:** in the air around the tank, at the tank. A sensor in sun, next to the heater or in another
  room measures another temperature. The loss coefficient is fitted against that sensor, so it absorbs a constant
  offset, but not a swing that does not follow the tank's surroundings.
- **Outages:** while the sensor is unavailable, its last reading stays in use for the Ambient sensor fallback time (3
  hours). A longer outage falls back to the Ambient temperature of the options, because a reading many hours old
  may belong to another part of the day.
- **History:** the setup fit and the recalibrate action replay the sensor's recorder history. Before its first
  recorded reading, the replay uses the Ambient temperature of the options.
- **Removing a sensor:** the last reading of a removed cold water or ambient sensor is dropped, so the seasonal curve,
  or the Ambient temperature of the options, applies at once.

## Tuning

The defaults are a start, and the fit learns most values. Three settings decide how well the estimate matches your
showers:
- **The shower ran cold earlier than predicted:** press the "Shower ran cold" button right then. It sets the usable
  fraction to the current cold fraction. Check the sensor height first if the charge errors are biased.
- **Usable fraction** (Options): lower it when showers run cold with litres left, raise it when water remains after
  the estimate reached zero. The button does this for you.
- **Thermocline width** (Options): a wide layer makes the hot water run out more gradually. It is learned from the
  first fall of the tank sensor after a charge; lock it if you set it by hand.
- **Other draws hot share** (Options): the share of the litres outside showers (taps, washing machine, garden) that
  is hot water. Raise it when the tank empties faster than predicted between showers, lower it when it empties
  slower. It is learned from the heating runs.

To see the effect of a setting on your own history, run the backtest from a checkout of this repository, on a
history export (`scripts/history.py`) or a fixture:

```sh
uv run --no-project scripts/backtest.py EXPORT_DIR --volume 200 --map-file MAPPING.json \
  --options '{"usable_fraction": 0.8}'
```

The roles of an export are the names of the setup fit: `tank_temperature`, `water_meter`, `dhw_energy`, `dhw_power`,
`dhw_heating`, `flow_temperature`, `return_temperature`, `bathroom_humidity`, `cold_water_temperature` and
`ambient_temperature`. The map file maps each file name (without `.json`) to its role. An export with an
`ambient_temperature` file replays the ambient sensor, one without it uses the fixed ambient temperature.

It prints the charge error at every heating run and the outputs through every shower, once with your options and once
with the fitted ones. The usage, all arguments and what the numbers mean are in
[docs/model.md](docs/model.md#the-backtest).

## Troubleshooting

- **No values after setup:** the sensors need a reading of the tank sensor first, and the heating-run based
  estimates need at least one heating run. Check that the sources are available. The diagnostics download shows which
  are.
- **The setup fit did nothing:** the recorder holds no history for the sources, or they are excluded from it. Run the
  recalibrate action later, or set the values in the options.
- **Hot water remaining is always lower than the tank volume:** this is the usable fraction, see above.
- **A steady error after each charge:** check the sensor height, then the tank volume.
- **Shower detected is unavailable:** there is no humidity sensor and the long draw rule is off. Add a sensor or set
  a long draw duration in the options.
- **A shower is not detected:** lower the humidity rise or the long draw duration; several humidity sensors are
  allowed.
- **A value you set by hand is overwritten:** lock the parameter in the options.

## Removal

Open the entry under Settings, Devices and services, choose the three dots and Delete. The entities and the device
go with it, and the stored model state and calibration are deleted. The source entities (meters, sensors) are not
touched. To remove the integration completely, then remove it in HACS (or delete the folder from
`custom_components`) and restart Home Assistant.

## Limitations

- The sensor height is entered by hand. A wrong value biases the estimate; the charge error sensors show it.
- Tanks heated high up (a coil or element in the upper part) and a second heat source such as an electric element
  are not supported. A coil low in the tank is.
- One tank sensor only, and no probe on the hot outlet.
- A shower in a room without a humidity sensor is not detected (the long draw rule covers part of it). It then counts
  at the other draws share, and the sensor bound corrects the estimate once the cold layer reaches the sensor.
- Garden watering and other large draws count at the other draws share, and the next charge resets them.
- A humidity rise without a shower (cooking, humid weather) has no effect without water drawn; with a draw it errs
  towards showing less.
- A water meter that misses low flows loses small trickles, which errs towards showing more water.
- Learning can drift in unusual weeks (guests, holidays). The error sensors show it, and locks and the recalibrate
  action undo it.
- A heating run cut short leaves the tank not uniform; the error shows at the next sensor bound.
- The usable fraction is learned only from the button, not measured.
- The integration displays only. It does not warn or control the heater.

## Dashboard example

A section for a sections view, using only core cards. The entity IDs assume a tank named "Hot Water Tank", so
change them to match your entry. `sensor.tank_temperature` stands for your own tank temperature sensor.

```yaml
type: grid
cards:
  - type: heading
    heading: Hot Water
    icon: mdi:water-boiler
  - type: tile
    entity: sensor.hot_water_tank_hot_water_remaining
    name: Hot water
    grid_options:
      columns: 6
  - type: tile
    entity: sensor.hot_water_tank_shower_water_remaining
    name: Shower water
    grid_options:
      columns: 6
  - type: tile
    entity: sensor.hot_water_tank_charge_level
    name: Charge level
    grid_options:
      columns: 6
  - type: tile
    entity: sensor.hot_water_tank_shower_time_remaining
    name: Shower time
    grid_options:
      columns: 6
  - type: history-graph
    title: Last 24 hours
    hours_to_show: 24
    grid_options:
      columns: full
      rows: 5
    entities:
      - entity: sensor.hot_water_tank_tank_average_temperature
        name: Tank average
      - entity: sensor.hot_water_tank_charged_temperature
        name: Charged temperature
      - entity: sensor.tank_temperature
        name: Tank sensor
      - entity: binary_sensor.hot_water_tank_shower_detected
        name: Shower detected
```

## Automation examples

A notification when the shower time left drops below 10 minutes (the entity ID assumes a tank named "Hot Water
Tank", and `notify.mobile_app_phone` stands for your own notifier):

```yaml
alias: Hot water is running low
triggers:
  - trigger: numeric_state
    entity_id: sensor.hot_water_tank_shower_time_remaining
    below: 10
actions:
  - action: notify.mobile_app_phone
    data:
      message: Less than 10 minutes of shower water left.
```

Charge the model by hand when the heater runs a boost or legionella cycle that the energy counter does not show.
`binary_sensor.heater_boost_active` stands for your own sensor that is on during the cycle:

```yaml
alias: Hot water tank charged by the boost run
triggers:
  - trigger: state
    entity_id: binary_sensor.heater_boost_active
    from: "on"
    to: "off"
actions:
  - action: hot_water_tank_estimator.set_tank_state
    target:
      entity_id: sensor.hot_water_tank_hot_water_remaining
    data:
      tank_average: 60
      charged_temperature: 60
```

## Development

See [docs/development.md](docs/development.md). `python scripts/lint.py` runs all checks with pinned tools.

## License

MIT, see [LICENSE](LICENSE).

The images in `custom_components/hot_water_tank_estimator/brand/` use parts of two Material Design Icons glyphs, the
heat waves of `radiator` and the pipes of `water-boiler`, from the Pictogrammers `@mdi/svg` package (version
7.4.47). They are (c) Pictogrammers and licensed under the
Apache License 2.0, whose text is in [LICENSE-MDI](LICENSE-MDI). `scripts/brand.py` draws them, with a light grey
outline in the `dark_` variants for dark backgrounds.
