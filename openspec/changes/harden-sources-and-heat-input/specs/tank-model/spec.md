# Spec Delta

## MODIFIED Requirements

### Requirement: A tank is charged at the end of a heating run
When a heating run of at least 15 minutes ends, T_avg and T_ch SHALL both be set to the charged temperature. When
flow and return temperature sensors are configured, the charged temperature SHALL be the highest mean of their
readings over the 2 minutes before the run ended, where the reading in force at the start of those 2 minutes counts
as well. Otherwise, or when flow and return have no reading with both values in that window, it SHALL be the tank
sensor's reading.

#### Scenario: Run ends below the setpoint
- **WHEN** a run ends, and over its last 2 minutes the highest mean of flow and return was (52.2 + 48.4) / 2 = 50.3 C
- **THEN** T_avg and T_ch become 50.3 C and the cold fraction is 0

#### Scenario: No flow and return sensors
- **WHEN** a run ends with no flow and return sensors configured, and the tank sensor reads 58.0 C
- **THEN** T_avg and T_ch become 58.0 C

#### Scenario: Charged temperature unavailable
- **WHEN** a run ends while neither the flow and return readings nor the tank sensor are available
- **THEN** T_avg and T_ch keep their modelled values

### Requirement: Sensor above the charged temperature raises it
While heating is not active, if the tank sensor reads more than `T_ch + tolerance`, T_ch SHALL be raised to the
sensor reading, and T_avg SHALL rise by the same step, less the metered heat that raised T_avg without a charge
(heat outside a heating run and of short runs) since the last charge or manual reset, as far as an earlier raise has
not used it. This covers heat the model does not see, such as a backup heater
without a meter, without counting metered heat twice. Raising T_avg with it keeps `T_ch - T_avg`, so the outputs do
not fall when heat arrives.

#### Scenario: Unmetered heat
- **WHEN** heating is off, the tolerance is 1.5 K, T_ch is 50 C, T_avg 45 C and the sensor reads 55 C
- **THEN** T_ch becomes 55 C and T_avg 50 C

#### Scenario: Sensor sees heat outside a run
- **WHEN** heating is off, the tolerance is 1.5 K, T_ch is 50 C and T_avg 45 C, heat outside a run then raises T_avg
  by 3 K to 48 C, and the sensor reads 55 C
- **THEN** T_ch becomes 55 C and T_avg 50 C, because 3 K of the 5 K step was counted already

## ADDED Requirements

### Requirement: A short heating run adds its heat without a charge
A heating run shorter than 15 minutes SHALL NOT charge the tank: T_avg and T_ch SHALL keep their modelled values. Its
heat SHALL raise T_avg as for any run, after the start-up energy, and counter increases in the 10 minutes after it
ends SHALL raise T_avg the same way. A short run does not mix the tank, so there is no charged temperature to set.

#### Scenario: Run cut off by a cooling demand
- **WHEN** a 285 L tank holds T_avg 40.0 C and T_ch 55.0 C, a run of 6 minutes adds 1.5 kWh, and the start-up energy
  is 0.5 kWh
- **THEN** after the run T_avg is 40.0 + 1000 / (1.163 * 285) = 43.0 C and T_ch 55.0 C

#### Scenario: Run of 15 minutes
- **WHEN** a run of exactly 15 minutes ends and the charged temperature is 52.0 C
- **THEN** T_avg and T_ch become 52.0 C

### Requirement: Heat outside a heating run raises the tank average
When an energy counter is configured, each increase of dE kWh while no heating run is active, and more than 10
minutes after the last run ended, SHALL raise T_avg by `dE * 1000 / (1.163 * V)` kelvin, with no start-up energy and
no charge. T_ch SHALL then be at least T_avg. Without an energy counter, heat power readings above the power threshold
while no run is active SHALL count the same way, integrated over time.

#### Scenario: Heat of cooling with the DHW demand off
- **WHEN** a heating-active binary sensor is off, a 285 L tank holds T_avg 45.0 C and T_ch 55.0 C, and the counter
  rises by 1.3 kWh
- **THEN** T_avg is 45.0 + 1300 / (1.163 * 285) = 48.9 C, T_ch stays 55.0 C, and no charge happens

#### Scenario: Heat outside a run reaches the charged temperature
- **WHEN** no run is active, T_avg is 54.0 C and T_ch 55.0 C on a 285 L tank, and the counter rises by 1.0 kWh
- **THEN** T_avg and T_ch are both 54.0 + 3.02 = 57.0 C

#### Scenario: Counter lag after a run
- **WHEN** a run ended 4 minutes ago and the counter rises by 0.2 kWh
- **THEN** T_avg does not change, and the 0.2 kWh counts towards that run's closure

#### Scenario: Power below the threshold
- **WHEN** only a heat power sensor and a heating-active binary sensor are configured, the binary sensor is off, and
  the power reads 40 W for an hour with a threshold of 100 W
- **THEN** T_avg does not rise
