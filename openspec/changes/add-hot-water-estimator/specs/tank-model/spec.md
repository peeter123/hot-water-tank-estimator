# Spec Delta

## Purpose

Keeps a two-layer energy balance of one hot water tank (a hot layer at the charged temperature above a cold
layer), corrected by the tank sensor at its configured height, and derives from it how much hot water is left.

## ADDED Requirements

### Requirement: Model state is the tank average and the charged temperature
Each tank SHALL keep two temperatures in degrees Celsius: the tank average T_avg and the charged temperature T_ch
of its hot layer. The cold fraction SHALL be `f = (T_ch - T_avg) / (T_ch - T_cold)`, limited to 0-1, and SHALL be 0
when T_ch is not above T_cold. Both temperatures SHALL be exposed as temperature sensors.

#### Scenario: Cold fraction
- **WHEN** T_ch is 57 C, T_avg 50 C and T_cold 14 C
- **THEN** the cold fraction is 7 / 43 = 0.163

### Requirement: Mixed draws take the mix energy
A litre classified as a mixed draw (see draw-classification) SHALL lower T_avg by `(T_mix - T_cold) / V` kelvin,
where V is the tank volume in litres. The house meter counts the hot and cold litres that the mixer combines, so
this is the energy the mix takes from the tank. When T_ch is at or below T_mix, the mixer draws only tank water, and
the drop SHALL be `(T_ch - T_cold) / V` per litre.

#### Scenario: Shower from a charged tank
- **WHEN** V is 281 L, T_ch 57 C, T_mix 38 C and T_cold 14 C, and 10 litres of mixed draw are measured
- **THEN** T_avg drops by 10 * 24 / 281 = 0.854 K, and T_ch is unchanged

#### Scenario: Shower from a tank charged below the mix temperature
- **WHEN** V is 281 L, T_ch 35 C, T_mix 38 C and T_cold 14 C, and 10 litres of mixed draw are measured
- **THEN** T_avg drops by 10 * 21 / 281 = 0.747 K

### Requirement: Other draws take a hot share at the charged temperature
A litre classified as another draw SHALL lower T_avg by `share * (T_ch - T_cold) / V` kelvin, where share is the
configured other-draws hot share (0-1). It covers hot taps among cold toilet flushes and appliances.

#### Scenario: Taps and toilet
- **WHEN** V is 281 L, T_ch 57 C, T_cold 14 C, the share 0.2, and 6 litres of other draws are measured
- **THEN** T_avg drops by 6 * 0.2 * 43 / 281 = 0.184 K

### Requirement: Heat from an energy counter raises the tank average
When a thermal energy counter is configured, each increase of dE kWh during a heating run SHALL raise T_avg by
`dE * 1000 / (1.163 * V)` kelvin, after the configured start-up energy of that run has been used up. While heating,
T_ch SHALL be at least T_avg, because a heating run mixes the tank above the heat source.

#### Scenario: Energy counter step
- **WHEN** the counter rises by 3.27 kWh on a 281 L tank at 40 C, with the start-up energy already used up
- **THEN** T_avg rises by 3270 / (1.163 * 281) = 10.0 K, to 50.0 C, and T_ch is at least 50.0 C

#### Scenario: Start-up energy
- **WHEN** the start-up energy is 1.8 kWh and a run's counter rises by 5.0 kWh on a 281 L tank
- **THEN** T_avg rises by 3200 / (1.163 * 281) = 9.79 K over the run

### Requirement: Heat from a power sensor raises the tank average
When a heat power sensor is configured instead of an energy counter, the energy SHALL be the power integrated over
time between readings, applied with the same rules as the energy counter. Gaps where the power was unavailable
SHALL count as no energy.

#### Scenario: Constant power for ten minutes
- **WHEN** a 281 L tank receives 6 kW for 10 minutes, with the start-up energy used up
- **THEN** T_avg rises by 1000 Wh / (1.163 * 281) = 3.06 K

### Requirement: Heating run detection
Heating SHALL count as active:
- while the configured heating-active binary sensor is on; otherwise
- while the heat power is above the configured threshold; otherwise
- for 10 minutes after the last energy counter increase.

The first of these that is configured decides. While it is unavailable, heating SHALL keep its last state; once it
has been unavailable for 15 minutes, the next configured one decides until it returns.

A heating run SHALL end when heating stops counting as active. When the counter timeout ends it, the run SHALL end
at the last counter increase, because heat input stopped then. Draws and standing loss between that end and the
moment it is found SHALL be applied to the charged tank, and they belong to the interval that starts at the end.

#### Scenario: Binary sensor drives the run
- **WHEN** a heating-active binary sensor is configured and turns from on to off
- **THEN** the heating run ends at that moment

#### Scenario: Binary sensor flickers during a run
- **WHEN** a heating-active binary sensor is on, becomes unavailable for 2 seconds, and returns on
- **THEN** the run continues without a charge, and its start-up energy is not counted again

#### Scenario: Counter timeout
- **WHEN** only an energy counter is configured, and its last increase of a run is at 12:30
- **THEN** at 12:40 the run is found to have ended, and it ends at 12:30 with the charge window 12:28-12:30

#### Scenario: Shower before the counter timeout finds the end
- **WHEN** only an energy counter is configured on a 281 L tank, the run's last increase is at 12:30 and the charge
  is 54.0 C, and 60 L of mixed draw at T_mix 38 C and T_cold 14 C follow before the end is found
- **THEN** T_avg is 54.0 - 60 * 24 / 281 = 48.9 C, less standing loss, and T_ch 54.0 C less standing loss

### Requirement: A tank is charged at the end of a heating run
When a heating run ends, T_avg and T_ch SHALL both be set to the charged temperature. When flow and return
temperature sensors are configured, the charged temperature SHALL be the highest mean of their readings over the
2 minutes before the run ended. Otherwise it SHALL be the tank sensor's reading.

#### Scenario: Run ends below the setpoint
- **WHEN** a run ends, and over its last 2 minutes the highest mean of flow and return was (52.2 + 48.4) / 2 = 50.3 C
- **THEN** T_avg and T_ch become 50.3 C and the cold fraction is 0

#### Scenario: No flow and return sensors
- **WHEN** a run ends with no flow and return sensors configured, and the tank sensor reads 58.0 C
- **THEN** T_avg and T_ch become 58.0 C

#### Scenario: Charged temperature unavailable
- **WHEN** a run ends while neither the flow and return readings nor the tank sensor are available
- **THEN** T_avg and T_ch keep their modelled values

### Requirement: Heating without a heat input follows the sensor upward
When no energy counter and no heat power sensor is configured, T_avg and T_ch SHALL rise to the tank sensor's
reading whenever heating is active and that reading is higher.

#### Scenario: Binary-only heating source
- **WHEN** only a heating-active binary sensor is configured, it is on, the sensor reads 45 C and T_avg is 41 C
- **THEN** T_avg becomes 45 C

### Requirement: Standing loss cools both temperatures
At least every 5 minutes, T_avg and T_ch SHALL each drop by `k * (T - T_ambient) * dt` kelvin, where T is the value
itself, k the loss coefficient per hour, T_ambient the configured surrounding temperature and dt the hours since the
last loss step. There SHALL be no loss below T_ambient.

#### Scenario: One hour of standing loss
- **WHEN** T_avg and T_ch are 57 C, T_ambient 20 C and k 0.004 per hour, and one hour passes with no draw or heat
- **THEN** both drop by 0.004 * 37 = 0.148 K

### Requirement: Sensor still at the charged temperature bounds the cold fraction from above
While heating is not active, if the tank sensor reads at least `T_ch - tolerance`, the cold layer is below the
sensor. The cold fraction SHALL then be at most `h - w / 2`, limited to 0-1. Here h is the sensor height as a
fraction of the tank (from the bottom) and w the thermocline width as a fraction of the tank. So T_avg SHALL be at
least `T_ch - (h - w / 2) * (T_ch - T_cold)`.

#### Scenario: Model drew too much
- **WHEN** heating is off, h is 0.5, w 0.35, the tolerance 1.5 K, T_ch 57 C, T_cold 14 C, the sensor reads 57 C
  and T_avg is 40 C
- **THEN** T_avg becomes 57 - 0.325 * 43 = 43.0 C

### Requirement: Sensor at the cold temperature bounds the cold fraction from below
While heating is not active, if the tank sensor reads at most `T_cold + tolerance`, the cold layer has passed the
sensor. The cold fraction SHALL then be at least `h + w / 2`, limited to 0-1, so T_avg SHALL be at most
`T_ch - (h + w / 2) * (T_ch - T_cold)`.

#### Scenario: Tank emptied past the sensor
- **WHEN** heating is off, h is 0.5, w 0.35, the tolerance 1.5 K, T_ch 57 C, T_cold 14 C, the sensor reads 15 C
  and T_avg is 33 C
- **THEN** T_avg becomes 57 - 0.675 * 43 = 28.0 C

### Requirement: Sensor in the thermocline caps the tank average
While heating is not active, when the sensor reads between those two cases, the thermocline has reached it. T_avg
SHALL then be at most `T_s_avg + margin`, where:
- `s = (T_sensor - T_cold) / (T_ch - T_cold)`;
- `f_lo = h - w / 2` and `f_hi = h + w / 2`, each limited to 0-1;
- cold fraction `f_s = f_hi - s * (f_hi - f_lo)`, which is `h + w / 2 - s * w` when neither is limited;
- sensor average `T_s_avg = T_ch - f_s * (T_ch - T_cold)`.

The model SHALL NOT be raised towards T_s_avg, because the thermocline widens during long draws and the linear
reading then overstates the hot water left.

#### Scenario: Sensor falling during a long shower
- **WHEN** heating is off, h is 0.5, w 0.35, the margin 2 K, T_ch 57 C, T_cold 14 C, the sensor reads 40 C and
  T_avg is 41 C
- **THEN** T_s_avg is 57 - (0.675 - 0.6047 * 0.35) * 43 = 37.1 C, and T_avg becomes 39.1 C

#### Scenario: Model below the sensor reading
- **WHEN** the same holds but T_avg is 33 C
- **THEN** T_avg stays 33 C

### Requirement: Sensor above the charged temperature raises it
While heating is not active, if the tank sensor reads more than `T_ch + tolerance`, T_ch SHALL be raised to the
sensor reading, and T_avg SHALL rise by the same step. This covers heat the model does not see, such as a backup
heater without a meter. Raising T_avg with it keeps `T_ch - T_avg`, so the outputs do not fall when heat arrives.

#### Scenario: Unmetered heat
- **WHEN** heating is off, the tolerance is 1.5 K, T_ch is 50 C, T_avg 45 C and the sensor reads 55 C
- **THEN** T_ch becomes 55 C and T_avg 50 C

### Requirement: The temperatures stay within physical bounds
After every update, the model SHALL keep `T_cold <= T_avg <= T_ch <= T_max`, where T_max is the configured maximum
tank temperature.

#### Scenario: Draws on an empty tank
- **WHEN** T_cold is 14 C, T_avg 14.2 C, and a draw would lower it by 1 K
- **THEN** T_avg becomes 14 C

### Requirement: Cold water temperature follows the season or a sensor
The cold water temperature SHALL be `mean - amplitude * cos(2 * pi * (day_of_year - coldest_day) / 365)` from the
configured mean, amplitude and coldest day. When a cold water temperature sensor is configured and available, its
value SHALL be used instead. The value in use SHALL be exposed as a temperature sensor.

#### Scenario: Seasonal curve in late October
- **WHEN** no sensor is configured, the curve is mean 12.5 C, amplitude 5 K, coldest day 46, and the date is
  31 October (day 304)
- **THEN** the cold water temperature is 12.5 - 5 * cos(2 * pi * 258 / 365) = 13.8 C

#### Scenario: Sensor unavailable
- **WHEN** a cold water sensor is configured but unavailable
- **THEN** the seasonal curve value is used

### Requirement: Tank water remaining
The integration SHALL expose the litres of tank water at the charged temperature that can still be drawn as
`max(0, V * (u - f))`, rounded to whole litres. u is the usable fraction: the share of the tank that can be drawn
before the outlet runs cold, which is less than 1 because of the thermocline and the outlet position.

#### Scenario: Partly drawn tank
- **WHEN** V is 281 L, u 0.85, T_ch 57 C, T_avg 50 C and T_cold 14 C (f 0.163)
- **THEN** tank water remaining is 281 * 0.687 = 193 L

#### Scenario: Empty
- **WHEN** f is 0.9 and u 0.85
- **THEN** tank water remaining is 0 L

### Requirement: Shower water remaining
The integration SHALL expose the litres of mixed water at the mix temperature that the remaining tank water makes:
tank water remaining (unrounded) times `(T_ch - T_cold) / (T_mix - T_cold)`, rounded to whole litres. When T_ch is
at or below T_mix, it SHALL equal the tank water remaining.

#### Scenario: Mixing multiplies the tank water
- **WHEN** tank water remaining is 193.1 L, T_ch 57 C, T_mix 38 C and T_cold 14 C
- **THEN** shower water remaining is 193.1 * 43 / 24 = 346 L

### Requirement: Percent charged
The integration SHALL expose percent charged as `(u - f) / u * 100`, limited to 0-100 and rounded to whole percent.
It reads 100 % right after a heating run ends, whatever the charged temperature.

#### Scenario: Partly drawn
- **WHEN** u is 0.85 and f 0.163
- **THEN** percent charged is 81 %

### Requirement: Shower minutes remaining
The integration SHALL expose the shower minutes left as shower water remaining divided by the configured shower
flow in litres per minute, rounded to whole minutes.

#### Scenario: Minutes from litres
- **WHEN** shower water remaining is 346 L and the shower flow 7.5 L/min
- **THEN** shower minutes remaining is 46 min
