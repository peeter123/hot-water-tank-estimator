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

### Requirement: Config flow collects the sources
The config flow SHALL ask for:
- the tank name and volume (20-2000 L);
- the tank temperature sensor (required);
- the total water meter (required);
- the heat input: an energy counter, a heat power sensor and/or a heating-active binary sensor, with at least one
  of the three required;
- optional humidity sensors;
- an optional cold water temperature sensor;
- an optional setpoint entity.

#### Scenario: No heat information
- **WHEN** a user submits the heat input step with no energy counter, no power sensor and no heating-active binary
  sensor
- **THEN** the step shows an error that at least one is required

#### Scenario: Unsuitable water meter
- **WHEN** a user picks a water meter whose unit is not a volume unit
- **THEN** the step shows an error naming the accepted units

### Requirement: Options flow tunes the model without losing its state
The options flow SHALL let the user change every tuning value:
- mix, floor, full and maximum temperature;
- cap margin, loss coefficient and ambient temperature;
- other-draws share, shower flow, humidity rise and window, long-draw duration, session gap and maximum draw;
- cold water curve mean, amplitude and coldest day;
- the power threshold.

It SHALL also let the user change the optional source entities. Saving SHALL keep the current tank average.

#### Scenario: Change floor temperature
- **WHEN** the tank average is 44 C and the user changes the floor temperature from 25 C to 22 C
- **THEN** the tank average stays 44 C and the remaining litres are recalculated with 22 C

### Requirement: Defaults for tuning values
Every tuning value SHALL have a default, so that a fresh entry runs without opening the options. The defaults
SHALL be those in the scenarios below. The design records where each one comes from.

#### Scenario: Temperature defaults
- **WHEN** a user finishes the config flow without opening the options
- **THEN** the mix temperature is 38 C, the floor 25 C, the full temperature 55 C, the maximum 95 C, the cap margin
  3 K and the ambient temperature 20 C

#### Scenario: Model coefficient defaults
- **WHEN** a user finishes the config flow without opening the options
- **THEN** the loss coefficient is 0.0037 per hour, the other-draws share 0.3, the shower flow 7.5 L/min and the
  power threshold 100 W, and the cold water curve has mean 12.5 C, amplitude 5 K and coldest day 46

#### Scenario: Draw detection defaults
- **WHEN** a user finishes the config flow without opening the options
- **THEN** the humidity rise is 6 points, the humidity window 60 min, the long-draw duration 0 (off), the session
  gap 60 s and the maximum draw per reading 100 L

### Requirement: Entities and units
Each tank SHALL provide:
- sensors for tank average temperature (C), hot water remaining (L, volume storage), percent full (%), shower
  minutes remaining (min) and cold water temperature (C);
- a shower detected binary sensor.

All sensors SHALL use state class measurement, and SHALL use translated names without emoji.

#### Scenario: Units shown
- **WHEN** the entities are listed
- **THEN** the remaining sensor is in litres, the percent sensor in %, the minutes sensor in min, and the
  temperatures in degrees Celsius

### Requirement: Set tank average action
The action `hot_water_tank_estimator.set_tank_average` SHALL take a target tank and an optional temperature. It
SHALL set that tank's average to the given temperature, or to the tank sensor's value when no temperature is
given, within the physical bounds.

#### Scenario: Anchor by hand
- **WHEN** the action runs without a temperature while the tank sensor reads 52 C
- **THEN** the tank average becomes 52 C

#### Scenario: No temperature and sensor unavailable
- **WHEN** the action runs without a temperature while the tank sensor is unavailable
- **THEN** the action fails with an error and the tank average is unchanged

### Requirement: State survives a restart
After a Home Assistant restart or an entry reload, each tank SHALL restore:
- its tank average;
- the last water meter reading and the last energy counter reading;
- the humidity window history.

On the first start, with nothing restored, the tank average SHALL start at the tank sensor's value. If that is
unavailable, it SHALL start at the full temperature.

#### Scenario: Restart
- **WHEN** Home Assistant restarts while the tank average is 41.2 C
- **THEN** after the restart the tank average is 41.2 C

#### Scenario: First start
- **WHEN** a new entry starts and the tank sensor reads 56 C
- **THEN** the tank average is 56 C

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

### Requirement: Diagnostics
The integration SHALL provide config entry diagnostics with:
- the entry's options;
- the current model state;
- whether each source is available;
- the most recent 50 model events, each with its time, kind, input change and resulting average.

#### Scenario: Download diagnostics
- **WHEN** a user downloads diagnostics for a tank
- **THEN** the file contains the tank average, the options and the recent events
