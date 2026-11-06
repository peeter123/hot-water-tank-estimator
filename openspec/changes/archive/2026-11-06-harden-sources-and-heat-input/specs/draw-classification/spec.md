# Spec Delta

## MODIFIED Requirements

### Requirement: Shower detection is exposed
The integration SHALL expose a binary sensor that is on while a shower or bath is in progress: from its start, by
humidity, by a draw in a still humid bathroom, by a draw while no humidity sensor reports, or by the long-draw rule,
until it ends. It SHALL be off while the bathroom only still counts as humid. It SHALL be unavailable when neither
humidity sensors nor the long-draw rule is configured.

#### Scenario: Binary sensor follows detection
- **WHEN** a shower is detected by humidity
- **THEN** the shower detected binary sensor is on

#### Scenario: Off after the water stops
- **WHEN** the water of a detected shower stopped 5 minutes ago and the humidity still reads 80 %
- **THEN** the shower detected binary sensor is off

## ADDED Requirements

### Requirement: A silent humidity sensor counts as unavailable
A humidity sensor SHALL count as silent once it has sent no report for the configured humidity silence time (default
2 hours). A report is any reading, also one that repeats the last value. A silence time of 0 SHALL turn this off, for
a sensor that reports only on change. In a replay of recorder history, each recorded state is a report. A silent
sensor SHALL count as unavailable for shower detection until it reports again.

#### Scenario: Sensor goes quiet
- **WHEN** the silence time is 2 hours and a humidity sensor last reported at 15:44:24
- **THEN** it is silent from 17:44:24, and no longer silent at its next report

#### Scenario: Unchanged reports
- **WHEN** a humidity sensor reports 58.5 % every 10 minutes for 3 hours without a change
- **THEN** it is never silent

#### Scenario: Silence check off
- **WHEN** the silence time is 0 and a humidity sensor has not reported for 5 hours
- **THEN** it is not silent

### Requirement: Shower detection falls back to the draw length while no humidity sensor reports
While humidity sensors are configured and every one of them is unavailable or silent, a draw session that has lasted
the next shower time SHALL start a shower when no shower is in progress. As for a shower in the humid bathroom, the
session's litres within the reclassify window SHALL become mixed draws, and the shower SHALL end once no water has
been drawn for the shower end time. The fallback SHALL end at the next valid reading of any humidity sensor.

#### Scenario: Shower during a silence
- **WHEN** the humidity sensor has been silent since 17:44:24, the next shower time is 5 minutes, and a draw session
  runs from 17:54:32 to 18:04:42 with 71 L
- **THEN** a shower starts at 17:59:32, the litres since 17:54:32 become mixed draws, and all 71 L count as mixed

#### Scenario: Short draw during a silence
- **WHEN** the humidity sensor is silent and a draw session of 4.4 minutes and 22 L runs
- **THEN** its 22 L stay other draws

#### Scenario: Sensor unavailable
- **WHEN** the only humidity sensor is unavailable and a draw session has run for 5 minutes
- **THEN** a shower starts

#### Scenario: One of two sensors still reports
- **WHEN** two humidity sensors are configured, one is unavailable, the other reports without a rise, and a draw
  session runs for 8 minutes
- **THEN** no shower starts, and its litres are other draws

#### Scenario: Sensor reports again
- **WHEN** a shower was started by the fallback, and the humidity sensor reports again while the water still runs
- **THEN** the shower continues until no water has been drawn for the shower end time
