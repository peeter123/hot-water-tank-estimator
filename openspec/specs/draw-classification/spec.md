# draw-classification Specification

## Purpose

Decides which litres measured by a whole-house water meter are mixed shower or bath water and which are other
draws. This lets the tank model use a meter that also counts toilet flushes, cold taps and appliances.

## Requirements

### Requirement: Litres drawn come from a total water meter
The litres drawn SHALL be the increase of the configured total water meter between two readings, converted to
litres from the meter's unit (m3, L, gal or ft3). A decrease SHALL NOT count as a draw, and the decreased reading
SHALL become the new starting point. A non-numeric or unavailable reading SHALL be skipped: the next valid reading
counts from the last valid one (see integration-setup, unavailable sources).

#### Scenario: Meter in cubic metres
- **WHEN** the meter goes from 347.504 m3 to 347.505 m3
- **THEN** 1 litre is drawn

#### Scenario: Meter reset
- **WHEN** the meter goes from 347.504 m3 to 0.002 m3
- **THEN** no litres are drawn, and 0.002 m3 is the new starting point

### Requirement: Implausible jumps are ignored
An increase larger than the configured maximum per reading (default 100 L) SHALL NOT count as a draw. The reading
SHALL become the new starting point, and a warning SHALL be logged. An example is a meter catching up after being
offline.

#### Scenario: Meter catches up after an outage
- **WHEN** the meter increases by 450 L in one reading with the maximum at 100 L
- **THEN** no litres are drawn and a warning is logged

### Requirement: Draws are grouped into sessions
Readings with an increase SHALL belong to the same draw session while the gap since the previous increase is at
most the configured session gap (default 60 seconds). A longer gap SHALL start a new session.

#### Scenario: Continuous shower
- **WHEN** the meter rises 1 L every 8 seconds for 30 minutes
- **THEN** all those litres belong to one session

#### Scenario: Separate draws
- **WHEN** two increases are 5 minutes apart
- **THEN** they belong to different sessions

### Requirement: Shower detection from bathroom humidity
When one or more humidity sensors are configured, a shower or bath SHALL count as detected while any of them reads
at least the configured rise (default 6 percentage points) above its own lowest value of the configured window
(default 60 minutes). Detection SHALL end once every sensor that
reached the rise is below its window minimum plus half the rise. A sensor that never reached the rise does not hold
detection.

#### Scenario: Shower starts
- **WHEN** the lowest bathroom humidity of the last 60 minutes is 61 % and the sensor now reads 72 %
- **THEN** a shower is detected

#### Scenario: Shower ends with hysteresis
- **WHEN** a shower is detected, the window minimum is 61 %, the rise 6 points, and the humidity falls to 65 %
- **THEN** the shower is still detected, and it ends once the humidity is below 64 %

### Requirement: Long draws count as a shower
When the long-draw duration is set (default 0, off), a draw session that has lasted at least that many minutes
SHALL count as a shower from that moment until the session ends. This is for homes without a bathroom humidity
sensor.

#### Scenario: Long draw without humidity sensor
- **WHEN** the long-draw duration is 3 minutes and a session has run for 3 minutes
- **THEN** a shower is detected until the session ends

### Requirement: Shower detection is exposed
The integration SHALL expose a binary sensor that is on while a shower or bath is detected, by humidity or by the
long-draw rule. It SHALL be unavailable when neither detection method is configured.

#### Scenario: Binary sensor follows detection
- **WHEN** a shower is detected by humidity
- **THEN** the shower detected binary sensor is on

### Requirement: Litres during a shower are mixed draws
Every litre drawn while a shower or bath is detected SHALL be a mixed draw: water through a thermostatic mixer, both
its hot and its cold part counted by the house meter. The tank model takes the mix energy for it (see tank-model).

#### Scenario: Shower litre
- **WHEN** 1 litre is drawn while a shower is detected
- **THEN** it is passed to the tank model as 1 litre of mixed draw

### Requirement: Litres just before detection are reclassified
When detection starts during a session, the litres of that session drawn within the configured reclassify window
before detection (default 10 minutes) SHALL be reclassified from other draws to mixed draws, and the tank model
corrected by the difference. Humidity rises up to about 6 minutes after a shower starts, and the long-draw rule
fires only after its duration. The window keeps other draws earlier in a long session from being reclassified.

#### Scenario: Reclassify at detection
- **WHEN** a session has drawn 45 litres in the 10 minutes before a shower is detected, and 40 litres earlier in a
  slow trickle
- **THEN** the 45 litres become mixed draws and the 40 litres stay other draws

### Requirement: Other litres are other draws
A litre drawn while no shower or bath is detected SHALL be another draw. The tank model takes the configured hot
share of it (see tank-model).

#### Scenario: Toilet flush or tap
- **WHEN** 6 litres are drawn with no shower detected
- **THEN** they are passed to the tank model as 6 litres of other draws

### Requirement: A detected shower reports its litres and minutes of flow
When a detected shower or bath ends, the integration SHALL report its minutes of flow and the mixed litres drawn in
them. Minutes of flow are the summed duration of the draw sessions within the shower, each from its first to its
last increase, so a pause longer than the session gap does not count. The litres of each session's first increase
flowed before that increase, outside the minutes of flow, so they SHALL be left out. Calibration learns the shower
flow from them.

#### Scenario: Shower with a pause
- **WHEN** a detected shower has a session of 5 minutes, a 3-minute pause and a session of 3 minutes, and draws 60 L
  after the first increase of each session
- **THEN** it reports 60 L over 8 minutes of flow

#### Scenario: Shower detected by the long-draw rule
- **WHEN** the long-draw rule detects a shower in a session that lasts 9 minutes and draws 70 L after its first
  increase
- **THEN** it reports 70 L over 9 minutes of flow

#### Scenario: Polled meter
- **WHEN** a detected shower is one 8-minute session from a meter read every 30 s, with 3.75 L per reading
- **THEN** it reports 16 * 3.75 = 60 L over 8 minutes of flow, leaving out the first reading's 3.75 L, so its flow
  is 7.5 L/min and not 8.0

### Requirement: A shower in progress reports its rolling flow
While a shower or bath is detected, the integration SHALL report its rolling flow: the mixed litres over the last 2
minutes of flow, divided by those minutes. Time without flow, longer than the session gap, SHALL not count towards
the 2 minutes. With less than 1 minute of flow in the shower, there SHALL be no rolling flow.

#### Scenario: Steady shower
- **WHEN** a detected shower has drawn 24 L in its last 2 minutes of flow
- **THEN** its rolling flow is 12.0 L/min

#### Scenario: Pause in the shower
- **WHEN** a detected shower drew 15 L in 2 minutes of flow, then paused for 3 minutes with the water off
- **THEN** its rolling flow is still 7.5 L/min

#### Scenario: Too little flow yet
- **WHEN** a detected shower has 40 seconds of flow
- **THEN** it reports no rolling flow

### Requirement: The end of the last draw is kept
The integration SHALL keep, for the last draw session that ended, its end time, the cold fraction at its end, T_ch
and T_avg at its end, and the tank sensor reading at its end. The "Hot water ran out" button applies to that moment
(see calibration).

#### Scenario: Draw ends
- **WHEN** a draw session ends at 19:42 with a cold fraction of 0.74 and the tank sensor reading 31.0 C
- **THEN** the last draw end is 19:42, at a cold fraction of 0.74, with the sensor at 31.0 C
