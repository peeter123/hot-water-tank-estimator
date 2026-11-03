# Spec Delta

## MODIFIED Requirements

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
replacing the ambient temperature sensor SHALL start a recalibration, because the loss coefficient depends on it.

#### Scenario: Change sensor height
- **WHEN** T_avg is 44 C and the user changes the sensor height from 50 % to 65 %
- **THEN** T_avg stays 44 C, and the next sensor bound uses 65 %

#### Scenario: Add an ambient sensor
- **WHEN** T_avg is 52 C and the user adds an ambient temperature sensor in the options
- **THEN** T_avg stays 52 C, and a recalibration over the history days runs with that sensor's history

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
  - long-draw duration 0 (off) and reclassify window 10 min;
  - session gap 60 s and maximum draw per reading 100 L;
  - power threshold 100 W.

### Requirement: Entities and units
Each tank SHALL provide sensors (state class measurement) for:
- tank water remaining (L), named "Hot water remaining";
- shower water remaining (L), named "Shower water remaining";
- percent charged (%), named "Charge level";
- shower minutes remaining (min), named "Shower time remaining";
- heat loss (W), named "Heat loss";
- charged temperature, tank average and cold water temperature (C).

It SHALL also provide a shower detected binary sensor, a "Hot water ran out" button, an "Undo hot water ran out"
button, a "Shower flow" number (L/min), a "Shower flow locked" switch and the calibration diagnostic sensors.
Names SHALL be translated, without emoji. The user-facing names differ from the model's vocabulary where the
model's terms read wrongly: "tank water" alone does not say that it is hot, and "percent charged" at 100 % beside
fewer litres than the tank holds reads as an error, while "charge level" compares with the last charge.

#### Scenario: Units shown
- **WHEN** the entities are listed
- **THEN** both remaining sensors are in litres, the charge level in %, the minutes sensor in min, the heat loss in
  W, the shower flow in L/min, and the three temperatures in degrees Celsius

#### Scenario: Names shown
- **WHEN** a new entry titled "Hot Water Tank" is added
- **THEN** its entities include "Hot Water Tank Hot water remaining", "Hot Water Tank Charge level", "Hot Water Tank
  Heat loss", "Hot Water Tank Hot water ran out" and "Hot Water Tank Shower flow"

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

## ADDED Requirements

### Requirement: Shower flow number
The "Shower flow" number SHALL show the shower flow in use, with a `source` attribute (default, learned or locked),
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
The "Shower flow locked" switch SHALL show whether the shower flow is locked. It is the same lock as the shower flow
lock in the options, so the switch, the options and the number's `source` always agree, also after a restart or a
reload. Turning the switch on SHALL lock the shower flow at the flow in use at that moment. Turning it off SHALL
return the shower flow to the median of the history, within its bounds, with source learned, or to the default
while the history is empty. Setting the "Shower flow" number SHALL turn the switch on. The history SHALL keep
filling while the switch is on.

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

### Requirement: Heat loss sensor
The "Heat loss" sensor SHALL show the standing heat loss of the tank in W as `k * C * (T_avg - T_ambient) * 1000`,
with k the loss coefficient in use, `C = 1.163 * V / 1000` kWh/K and T_ambient the ambient temperature in use (see
tank-model), rounded to whole watts. It SHALL read 0 W when T_avg is at or below T_ambient.

#### Scenario: Standing loss of a charged tank
- **WHEN** V is 285 L, k 0.0039 per hour, T_avg 58 C and T_ambient 19.5 C
- **THEN** the heat loss is 0.0039 * 0.331 * 38.5 * 1000 = 50 W
