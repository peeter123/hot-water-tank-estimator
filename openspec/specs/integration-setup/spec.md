# integration-setup Specification

## Purpose

Describes how a user adds and tunes a hot water tank in Home Assistant and what it then provides: the entities,
the action, restart behaviour, handling of unavailable sources, and diagnostics.

## Requirements

### Requirement: Each config entry is one tank
The integration SHALL be added from the UI, with one config entry per tank and no YAML configuration. Each entry
SHALL create one device named after the entry title, and that device SHALL hold the entry's entities.

#### Scenario: Two tanks
- **WHEN** a user adds the integration twice, for an upstairs and a downstairs tank
- **THEN** two devices exist, each with its own model and entities

### Requirement: Config flow collects the tank and its sources
The config flow SHALL ask for:
- the tank name and volume (20-2000 L);
- the tank sensor and its height (20-80 %, default 50 %);
- the total water meter;
- at least one heat input: an energy counter, a heat power sensor or a heating-active binary sensor;
- optionally: flow and return temperature sensors (as a pair), humidity sensors, a cold water sensor and an ambient
  temperature sensor for the air around the tank.

#### Scenario: Required fields
- **WHEN** a user leaves the tank sensor or the water meter empty
- **THEN** the step does not submit and marks the field as required

#### Scenario: No heat information
- **WHEN** a user submits the heat input step with no energy counter, no power sensor and no heating-active binary
  sensor
- **THEN** the step shows an error that at least one is required

#### Scenario: Only one of flow and return
- **WHEN** a user picks a flow temperature sensor without a return temperature sensor
- **THEN** the step shows an error that both or neither are needed

#### Scenario: Unsuitable water meter
- **WHEN** a user picks a water meter whose unit is not a volume unit
- **THEN** the step shows an error naming the accepted units

#### Scenario: Sensor height out of range
- **WHEN** a user enters a sensor height of 90 %
- **THEN** the step shows an error that the height must be 20-80 %

### Requirement: Options flow tunes the model without losing its state
The options flow SHALL let the user change:
- every tuning value named in the defaults requirements below, and the sensor height;
- the optional source entities (flow and return, humidity, cold water, ambient temperature);
- a lock for each learned parameter, the shower flow included (see calibration);
- the history days for the setup fit (1-30, default 30).

Saving SHALL keep the current tank average, the charged temperature and the calibration state. Adding, removing or
replacing the ambient temperature sensor SHALL start a recalibration, because the loss coefficient depends on it. A
shower end time that is not longer than the session gap SHALL be rejected with an error on that field.

#### Scenario: Change sensor height
- **WHEN** T_avg is 44 C and the user changes the sensor height from 50 % to 65 %
- **THEN** T_avg stays 44 C, and the next sensor bound uses 65 %

#### Scenario: Add an ambient sensor
- **WHEN** T_avg is 52 C and the user adds an ambient temperature sensor in the options
- **THEN** T_avg stays 52 C, and a recalibration over the history days runs with that sensor's history

#### Scenario: Shower end time not after the session gap
- **WHEN** the user saves the draws options with the shower end time at 2 min and the session gap at 120 s
- **THEN** the form shows an error on the shower end time and nothing is saved

### Requirement: Reconfigure changes the tank and its sources
A reconfigure step SHALL let the user change everything the config flow asked for, with the config flow's
validation: the volume, the tank sensor and its height, the water meter, the heat inputs and the optional sources.
The volume, the tank sensor, the water meter and the heat inputs SHALL change only here, not in the options flow. It
SHALL refuse a tank sensor that another entry uses. Saving SHALL keep the tuning values, the locks, the history days,
the tank average, the charged temperature and the calibration state, and SHALL reload the entry. When the save
adds, removes or replaces the ambient temperature sensor, a recalibration SHALL replace the calibration state, as in
the options flow, because the loss coefficient depends on it.

#### Scenario: Replace the water meter
- **WHEN** T_avg is 50 C, the usable fraction is locked, and the user picks another water meter in reconfigure
- **THEN** the entry reloads with the new meter, T_avg stays 50 C, and the lock and the calibration samples stay

#### Scenario: Tank sensor of another entry
- **WHEN** the user picks a tank sensor that another entry already uses
- **THEN** reconfigure refuses it and the entry stays unchanged

#### Scenario: Ambient sensor in reconfigure
- **WHEN** T_avg is 52 C and the user adds an ambient temperature sensor in reconfigure
- **THEN** the entry reloads, T_avg stays 52 C, and a recalibration over the history days runs with that sensor's
  history

### Requirement: Temperature and shape defaults
Every tuning value SHALL have a default, so that a fresh entry runs without opening the options. The defaults for
temperatures and tank shape SHALL be those in the scenario below. The design records where each one comes from.

#### Scenario: Fresh entry, temperatures and shape
- **WHEN** a user finishes the config flow without opening the options
- **THEN** the defaults are:
  - sensor height 50 % and thermocline width 35 %;
  - usable fraction 0.85;
  - mix temperature 38 C and maximum temperature 95 C;
  - sensor tolerance 1.5 K and sensor margin 2 K;
  - ambient temperature 20 C, and an ambient sensor fallback time of 3 hours;
  - cold water curve mean 12.5 C, amplitude 5 K and coldest day 46.

### Requirement: Draw and heat defaults
The defaults for draws, losses and heat input SHALL be those in the scenario below. The shower flow is a learned
parameter, not a tuning value: its default applies until the first shower is learned, and only its lock is an option.

#### Scenario: Fresh entry, draws and heat
- **WHEN** a user finishes the config flow without opening the options
- **THEN** the defaults are:
  - loss coefficient 0.004 per hour;
  - other-draws hot share 0.2 and start-up energy 0 kWh;
  - shower flow 7.5 L/min;
  - humidity rise 6 points and humidity window 60 min;
  - shower end time 5 min and next shower time 5 min;
  - long-draw duration 0 (off) and reclassify window 10 min;
  - session gap 60 s and maximum draw per reading 100 L;
  - power threshold 100 W.

#### Scenario: Existing entry after the update
- **WHEN** an entry created before the shower end time and the next shower time existed is loaded
- **THEN** it uses their defaults, 5 min each, and its other tuning values are unchanged

### Requirement: Entities and units
Each tank SHALL provide sensors (state class measurement) for:
- tank water remaining (L), named "Hot water remaining";
- shower water remaining (L), named "Shower water remaining";
- percent charged (%), named "Charge level";
- shower minutes remaining (min), named "Shower time remaining";
- heat loss (W), named "Heat loss";
- charged temperature, tank average and cold water temperature (C).

It SHALL also provide a shower detected binary sensor, a "Hot water ran out" button, an "Undo hot water ran out"
button, a "Shower flow" number (L/min), a "Shower flow locked" switch, a "Tank sensor temperature" diagnostic
sensor, the two shower timing and the two shower countdown diagnostic sensors, and the calibration diagnostic
sensors.
Names SHALL be translated, without emoji. The user-facing names differ from the model's vocabulary where the
model's terms read wrongly: "tank water" alone does not say that it is hot, and "percent charged" at 100 % beside
fewer litres than the tank holds reads as an error, while "charge level" compares with the last charge.

#### Scenario: Units shown
- **WHEN** the entities are listed
- **THEN** both remaining sensors are in litres, the charge level in %, the minutes sensor in min, the heat loss in
  W, the shower flow in L/min, the two shower timing sensors in min, and the three temperatures and the tank sensor
  temperature in degrees Celsius

#### Scenario: Names shown
- **WHEN** a new entry titled "Hot Water Tank" is added
- **THEN** its entities include "Hot Water Tank Hot water remaining", "Hot Water Tank Charge level", "Hot Water Tank
  Heat loss", "Hot Water Tank Hot water ran out" and "Hot Water Tank Shower flow"

### Requirement: Set tank state action
The action `hot_water_tank_estimator.set_tank_state` SHALL take a target tank and optionally a tank average and a
charged temperature. With neither given, it SHALL charge the tank to the tank sensor's reading. With only a tank
average given, the charged temperature SHALL stay as it is. The physical bounds SHALL be applied either way.

#### Scenario: Charge by hand
- **WHEN** the action runs with no temperatures while the tank sensor reads 52 C
- **THEN** T_avg and T_ch become 52 C

#### Scenario: Set the average only
- **WHEN** the action runs with a tank average of 30 C while T_ch is 55 C
- **THEN** T_avg becomes 30 C and T_ch stays 55 C

#### Scenario: No temperatures and sensor unavailable
- **WHEN** the action runs with no temperatures while the tank sensor is unavailable
- **THEN** the action fails with an error and the state is unchanged

### Requirement: Recalibrate action
The action `hot_water_tank_estimator.recalibrate` SHALL take a target tank and an optional number of days (1-30).
It SHALL rerun the setup fit from the calibration spec over that history. Locked parameters SHALL stay as they are.

#### Scenario: Recalibrate after moving the sensor
- **WHEN** the user changes the sensor height and runs recalibrate with 14 days
- **THEN** the unlocked parameters are refitted from the last 14 days

### Requirement: State survives a restart
After a Home Assistant restart or an entry reload, each tank SHALL restore:
- T_avg and T_ch;
- the last water meter reading and the last energy counter reading;
- the heating-run state, including the start-up energy used;
- the current draw session;
- the humidity window history, and whether the bathroom still counts as humid after a shower that has ended;
- the end of the last draw and the time T_avg was last reset (see draw-classification and calibration);
- the shower in progress, with its flow so far, its start and the time of its last meter increase;
- the last ambient reading and when it was last good, for a sensor that is still configured.

On the first start, with nothing restored, the tank SHALL start charged at the tank sensor's reading. If that is
unavailable, it SHALL start at 50 C.

#### Scenario: Restart
- **WHEN** Home Assistant restarts while T_avg is 41.2 C and T_ch 56.0 C
- **THEN** after the restart T_avg is 41.2 C and T_ch 56.0 C

#### Scenario: First start
- **WHEN** a new entry starts and the tank sensor reads 56 C
- **THEN** T_avg and T_ch are 56 C

#### Scenario: Restart in the humid bathroom after a shower
- **WHEN** Home Assistant restarts 10 minutes after a shower ended, while the bathroom still counts as humid
- **THEN** no new shower starts from the humidity after the restart, and a draw needs the next shower time to start
  one

#### Scenario: Restart during a shower
- **WHEN** Home Assistant restarts during a detected shower and is back 2 minutes after the water stopped
- **THEN** the shower is still detected, and it ends 5 minutes after its last meter increase

### Requirement: Unavailable sources pause their part of the model
When a source entity is unavailable or non-numeric, the integration SHALL skip the updates that depend on it and
keep the rest running. When the source returns, its first valid reading SHALL apply the change since the last valid
reading, subject to the counter-reset and implausible-jump rules.

#### Scenario: Water meter offline briefly
- **WHEN** the water meter is unavailable for 2 minutes and returns 3 L higher
- **THEN** 3 litres are classified and applied

#### Scenario: Energy counter reset
- **WHEN** the energy counter drops from 151.5 kWh to 0.2 kWh
- **THEN** no heat is applied and 0.2 kWh is the new starting point

#### Scenario: Tank sensor flickers
- **WHEN** the tank sensor is unavailable for 2 seconds
- **THEN** no sensor bound is applied in that time, and the outputs keep updating from the model

### Requirement: Diagnostics
The integration SHALL provide config entry diagnostics with:
- the entry's options;
- the current model state;
- whether each source is available;
- the most recent 100 model events, each with its time, kind, input change, and T_avg and T_ch before and after;
- the calibration state: the parameters in use with their sources, the stored intervals with their charge errors,
  the width estimates, the shower flow history and the undo record of the last "Hot water ran out" press.

Event kinds are draw, heat, charge, loss, sensor bound, calibration, hot water ran out (accepted, rejected with its
reason, or undone) and shower flow.

#### Scenario: Download diagnostics
- **WHEN** a user downloads diagnostics for a tank
- **THEN** the file contains T_avg, T_ch, the options and the recent events

#### Scenario: Rejected press in the diagnostics
- **WHEN** a "Hot water ran out" press was rejected because no draw ended in the last 20 minutes
- **THEN** the events contain a hot water ran out event marked rejected, with that reason

### Requirement: Shower flow number
The "Shower flow" number (device class volume flow rate) SHALL show the shower flow in use, with a `source`
attribute (default, learned or locked),
and `low` and `high` attributes with the lowest and highest flow in the shower flow history. Setting it SHALL set
the shower flow to that value, within the bounds of 3-20 L/min, and lock it. Turning the lock off, with the "Shower
flow locked" switch or in the options, SHALL turn learning back on.

#### Scenario: Set the shower flow
- **WHEN** the learned shower flow is 7.65 L/min and the user sets the number to 9
- **THEN** the shower flow in use is 9 L/min with source locked, and later showers add to the history without
  changing it

#### Scenario: Unlock in the options
- **WHEN** the shower flow is locked at 9 L/min and the user turns its lock off in the options
- **THEN** the shower flow in use is the median of the history again, with source learned

### Requirement: Shower flow lock switch
The "Shower flow locked" switch SHALL show and set the shower flow lock, which is the same lock as in the options
and the number, also after a restart or a reload. On SHALL lock the flow in use at that moment. Off SHALL return to
the median of the history, within its bounds, with source learned, or to the starting value while the history is
empty. Setting the number SHALL turn the switch on. The history SHALL keep filling while it is on.

#### Scenario: Lock the learned flow
- **WHEN** the learned shower flow is 7.65 L/min and the user turns the switch on
- **THEN** the shower flow in use stays 7.65 L/min with source locked, and later showers do not change it

#### Scenario: Setting the number turns the switch on
- **WHEN** the switch is off and the user sets the number to 9
- **THEN** the switch is on, and the shower flow in use is 9 L/min with source locked

#### Scenario: Unlock with the switch
- **WHEN** the shower flow is locked at 9 L/min, the history's median is 7.65 L/min, and the user turns the switch
  off
- **THEN** the number shows 7.65 L/min with source learned, and the shower flow lock in the options is off

#### Scenario: Unlock with an empty history
- **WHEN** the shower flow is locked at 9 L/min, the history is empty, and the user turns the switch off
- **THEN** the number shows the default of 7.5 L/min with source default

#### Scenario: Lock in the options
- **WHEN** the user turns the shower flow lock on in the options
- **THEN** the switch is on after the reload

### Requirement: Tank sensor temperature diagnostic sensor
The "Tank sensor temperature" sensor SHALL be a diagnostic sensor (C, device class temperature, state class
measurement) that shows the tank sensor reading as the model receives it, in degrees Celsius. It SHALL be
unavailable while the tank sensor is unavailable or not numeric. Its `source_entity` attribute SHALL give the tank
sensor's entity ID, and its `sensor_height` attribute the configured sensor height in %.

#### Scenario: Reading shown
- **WHEN** the tank sensor `sensor.tank_probe` reads 55.8 C and the sensor height is 58 %
- **THEN** the tank sensor temperature is 55.8 C, with `source_entity` `sensor.tank_probe` and `sensor_height` 58

#### Scenario: Reading in Fahrenheit
- **WHEN** the tank sensor reads 132.8 F
- **THEN** the tank sensor temperature is 56.0 C

#### Scenario: Source unavailable
- **WHEN** the tank sensor becomes unavailable
- **THEN** the tank sensor temperature is unavailable, while the tank average keeps its value

### Requirement: Heat loss sensor
The "Heat loss" sensor SHALL show the standing heat loss of the tank in W as `k * C * (T_avg - T_ambient) * 1000`,
with k the loss coefficient in use, `C = 1.163 * V / 1000` kWh/K and T_ambient the ambient temperature in use (see
tank-model), rounded to whole watts. It SHALL read 0 W when T_avg is at or below T_ambient.

#### Scenario: Standing loss of a charged tank
- **WHEN** V is 285 L, k 0.0039 per hour, T_avg 58 C and T_ambient 19.5 C
- **THEN** the heat loss is 0.0039 * 0.331 * 38.5 * 1000 = 50 W

### Requirement: Shower timing diagnostic sensors
Each tank SHALL provide two diagnostic sensors (min, device class duration, no state class) with the shower timing
options in use, named as the options: "Shower end after no water" (the shower end time) and "New shower draw while
humid" (the next shower time). The second SHALL be unavailable while no humidity sensor is configured.

#### Scenario: Defaults shown
- **WHEN** an entry with a humidity sensor uses the default shower timing
- **THEN** "Shower end after no water" is 5 min and "New shower draw while humid" is 5 min

#### Scenario: Option saved
- **WHEN** the user saves the options with the shower end time at 7.5 min
- **THEN** after the reload "Shower end after no water" is 7.5 min

#### Scenario: No humidity sensor
- **WHEN** an entry has no humidity sensor and a long-draw duration of 8 min
- **THEN** "Shower end after no water" is 5 min and "New shower draw while humid" is unavailable

### Requirement: Shower countdown diagnostic sensors
Each tank SHALL provide two diagnostic timestamp sensors, unknown when there is nothing to count down: "Shower
ends", the shower end of the shower in progress; and "Draw counts as shower", while no shower is in progress, the
start of the draw session in progress plus the next shower time (bathroom still humid) or plus the long-draw duration
(no humidity sensor). Both SHALL be unavailable while no detection method is configured.

#### Scenario: Shower ends counts down
- **WHEN** a detected shower's last meter increase is at 20:25:21 and the shower end time is 5 min
- **THEN** "Shower ends" is 20:30:21, and after the shower has ended it is unknown

#### Scenario: Draw in the humid bathroom
- **WHEN** a shower has ended, the bathroom still counts as humid, the next shower time is 5 min and a draw session
  starts at 20:40:00
- **THEN** "Draw counts as shower" is 20:45:00, and it is unknown again from just after 20:42:00, when the session
  ends (its last increase at 20:41:00 and a session gap of 60 s), with no further reading

#### Scenario: Long draw without humidity sensor
- **WHEN** an entry has no humidity sensor, the long-draw duration is 8 min and a draw session starts at 07:00:00
- **THEN** "Draw counts as shower" is 07:08:00
