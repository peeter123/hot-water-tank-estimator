# Spec Delta

## MODIFIED Requirements

### Requirement: Standing loss cools both temperatures
At least every 5 minutes, T_avg and T_ch SHALL each drop by `k * (T - T_ambient) * dt` kelvin, where T is the value
itself, k the loss coefficient per hour, T_ambient the ambient temperature in use and dt the hours since the last
loss step. There SHALL be no loss below T_ambient.

#### Scenario: One hour of standing loss
- **WHEN** T_avg and T_ch are 57 C, T_ambient 20 C and k 0.004 per hour, and one hour passes with no draw or heat
- **THEN** both drop by 0.004 * 37 = 0.148 K

#### Scenario: Cooler room from an ambient sensor
- **WHEN** T_avg and T_ch are 57 C, the ambient sensor reads 15 C and k is 0.004 per hour, and one hour passes with
  no draw or heat
- **THEN** both drop by 0.004 * 42 = 0.168 K

### Requirement: Shower minutes remaining
The integration SHALL expose the shower minutes left as shower water remaining divided by a flow, rounded to whole
minutes. While a shower is detected and has at least 1 minute of flow, the flow SHALL be the current shower's
rolling flow (see draw-classification); otherwise it SHALL be the shower flow in use (see calibration). The `flow`
and `flow_basis` attributes (`current_shower` or `median`) SHALL say which. The `minutes_low` and `minutes_high`
attributes SHALL give the minutes at the highest and lowest flow in the shower flow history, or the state if empty.

#### Scenario: Minutes from litres
- **WHEN** shower water remaining is 346 L and the shower flow 7.5 L/min
- **THEN** shower minutes remaining is 46 min

#### Scenario: Minutes for two people
- **WHEN** shower water remaining is 346 L, the shower flow in use 7.65 L/min, and the history's flows range from 7.3
  to 12.1 L/min
- **THEN** shower minutes remaining is 45 min, `minutes_low` is 29 and `minutes_high` is 47

#### Scenario: Minutes during a high-flow shower
- **WHEN** a shower is detected with 4 minutes of flow, its rolling flow is 12.0 L/min, shower water remaining is
  240 L, and the shower flow in use is 7.65 L/min
- **THEN** shower minutes remaining is 20 min, with `flow` 12.0 and `flow_basis` `current_shower`

#### Scenario: First minute of a shower
- **WHEN** a shower is detected with 40 seconds of flow, shower water remaining is 346 L, and the shower flow in use
  is 7.65 L/min
- **THEN** shower minutes remaining is 45 min, with `flow_basis` `median`

## ADDED Requirements

### Requirement: Ambient temperature in use
When an ambient temperature sensor is configured and available, its reading SHALL be the ambient temperature in use.
While it is unavailable, its last reading SHALL stay in use for the configured fallback time (default 3 hours); after
that, and when no sensor is configured, the configured ambient temperature SHALL be used.

#### Scenario: Sensor available
- **WHEN** an ambient sensor is configured and reads 19.5 C, and the configured ambient temperature is 20 C
- **THEN** the ambient temperature in use is 19.5 C

#### Scenario: Short outage
- **WHEN** the ambient sensor last read 18.0 C and has been unavailable for 1 hour
- **THEN** the ambient temperature in use is 18.0 C

#### Scenario: Long outage
- **WHEN** the ambient sensor has been unavailable for 4 hours and the configured ambient temperature is 20 C
- **THEN** the ambient temperature in use is 20 C
