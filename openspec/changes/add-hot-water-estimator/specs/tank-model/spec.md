# Spec Delta

## Purpose

Keeps an energy balance of one hot water tank as its average temperature, and derives from it how much shower
water is left, so a house without a tank flow meter can see its remaining hot water.

## ADDED Requirements

### Requirement: Tank average temperature is the model state
Each tank SHALL keep an estimated average water temperature in degrees Celsius. This one value is the model state.
Every other output derives from it and the configured parameters. It SHALL be exposed as a temperature sensor.

#### Scenario: State exposed
- **WHEN** a tank is set up and its model holds 47.3 C
- **THEN** the tank average sensor reports 47.3 C

### Requirement: Water drawn lowers the tank average
Each litre counted as hot water (see draw-classification) SHALL lower the average by
`dV * (T_draw - T_cold) / V` kelvin. Here dV is the counted litres, V the tank volume in litres and T_cold the
cold water temperature. T_draw is the lower of the shower mix temperature and the current tank average, because a
tank colder than the mix temperature cannot deliver it.

#### Scenario: Shower draw from a full tank
- **WHEN** the tank is 281 L at an average of 54 C, the mix temperature is 38 C, the cold water is 14 C, and 10
  litres are counted as hot
- **THEN** the average drops by 10 * (38 - 14) / 281 = 0.854 K, to 53.15 C

#### Scenario: Draw from a tank colder than the mix temperature
- **WHEN** the tank average is 30 C, the mix temperature 38 C, the cold water 14 C, the volume 281 L, and 10
  litres are counted as hot
- **THEN** the average drops by 10 * (30 - 14) / 281 = 0.569 K

### Requirement: Heat from an energy counter raises the tank average
When a thermal energy counter is configured, each increase of dE kWh SHALL raise the average by
`dE * 1000 / (1.163 * V)` kelvin, where 1.163 Wh/(L*K) is the volumetric heat capacity of water.

#### Scenario: Energy counter step
- **WHEN** the counter rises by 3.27 kWh on a 281 L tank at 40 C
- **THEN** the average rises by 3270 / (1.163 * 281) = 10.0 K, to 50.0 C

### Requirement: Heat from a power sensor raises the tank average
When a heat power sensor is configured instead of an energy counter, the energy SHALL be the power integrated over
time between updates, applied with the same formula as the energy counter. Gaps where the power was unavailable
SHALL count as no energy.

#### Scenario: Constant power for ten minutes
- **WHEN** a 281 L tank receives 6 kW of heat for 10 minutes
- **THEN** the average rises by 1000 Wh / (1.163 * 281) = 3.06 K

### Requirement: Anchor to the tank sensor at the end of heating
When heating stops, the average SHALL be set to the tank sensor's value, because a tank heated by circulation is
evenly mixed at that moment and its sensor then reads the average. Heating counts as active:
- while the configured heating-active binary sensor is on; otherwise
- while the heat power is above the configured threshold; otherwise
- for 10 minutes after the last energy counter increase.

#### Scenario: Heating cycle ends below setpoint
- **WHEN** the heating-active binary sensor turns off while the tank sensor reads 50.5 C and the model holds 48.2 C
- **THEN** the tank average becomes 50.5 C

#### Scenario: Sensor unavailable at the end of heating
- **WHEN** heating stops while the tank sensor is unavailable
- **THEN** the tank average keeps its modelled value

### Requirement: Heating without a heat input follows the sensor upward
When no energy counter and no heat power sensor is configured, the average SHALL rise to the tank sensor's value
whenever heating is active and the sensor reads higher than the model.

#### Scenario: Binary-only heating source
- **WHEN** only a heating-active binary sensor is configured, it is on, the sensor reads 45 C and the model holds
  41 C
- **THEN** the tank average becomes 45 C

### Requirement: Standing loss lowers the tank average
At least every 5 minutes the average SHALL drop by `k * (T_avg - T_ambient) * dt` kelvin. Here k is the loss
coefficient per hour, T_ambient the configured surrounding temperature and dt the hours since the last loss step.
There SHALL be no loss when T_avg is at or below T_ambient.

#### Scenario: One hour of standing loss
- **WHEN** the average is 57 C, the ambient temperature 20 C and k 0.0037 per hour, and one hour passes with no draw or heat
- **THEN** the average drops by 0.0037 * 37 * 1 = 0.137 K

### Requirement: The tank sensor caps the tank average
While heating is not active and the tank sensor is available, the average SHALL NOT be higher than the sensor
reading plus the configured cap margin. A sensor low in the tank lags small draws, but once it falls it shows the
tank emptying, so a higher model value is wrong.

#### Scenario: Model above the sensor after a long shower
- **WHEN** heating is off, the margin is 3 K, the tank sensor reads 23 C and the model holds 33 C
- **THEN** the tank average becomes 26 C

#### Scenario: Sensor lags early in a shower
- **WHEN** heating is off, the margin is 3 K, the tank sensor reads 50 C and the model holds 45.6 C
- **THEN** the tank average stays 45.6 C

### Requirement: The tank average stays within physical bounds
The average SHALL be kept between the current cold water temperature and the configured maximum tank temperature,
after every update.

#### Scenario: Draws on an empty tank
- **WHEN** the cold water is 14 C, the model holds 14.2 C, and a draw would lower it by 1 K
- **THEN** the tank average becomes 14 C

### Requirement: Cold water temperature follows the season or a sensor
The cold water temperature SHALL be `mean - amplitude * cos(2 * pi * (day_of_year - coldest_day) / 365)` from
the configured mean, amplitude and coldest day. When a cold water temperature sensor is configured and available,
its value SHALL be used instead. The value in use SHALL be exposed as a temperature sensor.

#### Scenario: Seasonal curve in late October
- **WHEN** no sensor is configured, the curve is mean 12.5 C, amplitude 5 K, coldest day 46, and the date is
  31 October (day 304)
- **THEN** the cold water temperature is 12.5 - 5 * cos(2 * pi * 258 / 365) = 13.8 C

#### Scenario: Sensor unavailable
- **WHEN** a cold water sensor is configured but unavailable
- **THEN** the seasonal curve value is used

### Requirement: Hot water remaining in litres at the mix temperature
The integration SHALL expose the litres of water at the mix temperature still available as
`max(0, V * (T_avg - T_floor) / (T_mix - T_cold))`, rounded to whole litres. T_floor is the usable floor
temperature: the tank average at which the shower turns cold. When T_mix is not above T_cold, the sensor SHALL be
unavailable.

#### Scenario: Full tank
- **WHEN** V is 281 L, T_avg 54 C, T_floor 25 C, T_mix 38 C and T_cold 13.8 C
- **THEN** hot water remaining is 281 * 29 / 24.2 = 337 L

#### Scenario: Below the floor
- **WHEN** T_avg is 23 C and T_floor 25 C
- **THEN** hot water remaining is 0 L

### Requirement: Percent full relative to the full temperature
The integration SHALL expose percent full as `(T_avg - T_floor) / (T_full - T_floor) * 100`, limited to 0-100
and rounded to whole percent. T_full is the configured setpoint entity's value when available, and otherwise the
configured full temperature.

#### Scenario: Half way
- **WHEN** T_full is 55 C, T_floor 25 C and T_avg 40 C
- **THEN** percent full is 50 %

### Requirement: Shower minutes remaining
The integration SHALL expose the shower minutes left as hot water remaining divided by the configured shower flow
in litres per minute, rounded to whole minutes.

#### Scenario: Minutes from litres
- **WHEN** hot water remaining is 337 L and the shower flow 7.5 L/min
- **THEN** shower minutes remaining is 45 min
