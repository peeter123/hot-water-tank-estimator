# Spec Delta

## Purpose

Describes how a user adds and tunes a hot water tank in Home Assistant and what it then provides: the entities,
the action, restart behaviour, handling of unavailable sources, and diagnostics.

## ADDED Requirements

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
- optionally: flow and return temperature sensors (as a pair), humidity sensors, and a cold water sensor.

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
- the optional source entities (flow and return, humidity, cold water);
- a lock for each learned parameter (see calibration);
- the history days for the setup fit (1-30, default 30).

Saving SHALL keep the current tank average, the charged temperature and the calibration state.

#### Scenario: Change sensor height
- **WHEN** T_avg is 44 C and the user changes the sensor height from 50 % to 65 %
- **THEN** T_avg stays 44 C, and the next sensor bound uses 65 %

### Requirement: Reconfigure changes the tank and its sources
A reconfigure step SHALL let the user change everything the config flow asked for, with the config flow's
validation: the volume, the tank sensor and its height, the water meter, the heat inputs and the optional sources.
The volume, the tank sensor, the water meter and the heat inputs SHALL change only here, not in the options flow. It
SHALL refuse a tank sensor that another entry uses. Saving SHALL keep the tuning values, the locks, the history days,
the tank average, the charged temperature and the calibration state, and SHALL reload the entry.

#### Scenario: Replace the water meter
- **WHEN** T_avg is 50 C, the usable fraction is locked, and the user picks another water meter in reconfigure
- **THEN** the entry reloads with the new meter, T_avg stays 50 C, and the lock and the calibration samples stay

#### Scenario: Tank sensor of another entry
- **WHEN** the user picks a tank sensor that another entry already uses
- **THEN** reconfigure refuses it and the entry stays unchanged

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
  - ambient temperature 20 C;
  - cold water curve mean 12.5 C, amplitude 5 K and coldest day 46.

### Requirement: Draw and heat defaults
The defaults for draws, losses and heat input SHALL be those in the scenario below.

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
- charged temperature, tank average and cold water temperature (C).

It SHALL also provide a shower detected binary sensor, a "Shower ran cold" button and the calibration diagnostic
sensors. Names SHALL be translated, without emoji. The user-facing names differ from the model's vocabulary where
the model's terms read wrongly: "tank water" alone does not say that it is hot, and "percent charged" at 100 %
beside fewer litres than the tank holds reads as an error, while "charge level" compares with the last charge.

#### Scenario: Units shown
- **WHEN** the entities are listed
- **THEN** both remaining sensors are in litres, the charge level in %, the minutes sensor in min, and the three
  temperatures in degrees Celsius

#### Scenario: Names shown
- **WHEN** a new entry titled "Hot Water Tank" is added
- **THEN** its sensors include "Hot Water Tank Hot water remaining" and "Hot Water Tank Charge level"

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
- the humidity window history.

On the first start, with nothing restored, the tank SHALL start charged at the tank sensor's reading. If that is
unavailable, it SHALL start at 50 C.

#### Scenario: Restart
- **WHEN** Home Assistant restarts while T_avg is 41.2 C and T_ch 56.0 C
- **THEN** after the restart T_avg is 41.2 C and T_ch 56.0 C

#### Scenario: First start
- **WHEN** a new entry starts and the tank sensor reads 56 C
- **THEN** T_avg and T_ch are 56 C

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
  and the width estimates.

Event kinds are draw, heat, charge, loss, sensor bound and calibration.

#### Scenario: Download diagnostics
- **WHEN** a user downloads diagnostics for a tank
- **THEN** the file contains T_avg, T_ch, the options and the recent events
