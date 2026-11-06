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

### Requirement: Humidity starts a shower and the water ends it
The bathroom SHALL count as humid from when any humidity sensor reads at least the rise (default 6 points) above its
minimum over the window (default 60 minutes), until every sensor that reached the rise is below that minimum plus
half the rise. A shower SHALL start when the bathroom becomes humid, and SHALL end once no water has been drawn for
the shower end time (default 5 minutes) after the later of its last meter increase and its start; a humidity fall
SHALL NOT end it.

#### Scenario: Shower starts
- **WHEN** the lowest bathroom humidity of the last 60 minutes is 61 % and the sensor now reads 72 %
- **THEN** a shower is detected

#### Scenario: The water stops
- **WHEN** a shower is detected, its last meter increase was at 20:45:08, no water has been drawn since, and the
  humidity still reads 83 %
- **THEN** the shower ends at 20:50:08, and the bathroom still counts as humid

#### Scenario: Pause in a shower
- **WHEN** the water of a detected shower is off for 3 minutes and then runs again
- **THEN** it stays one shower

#### Scenario: Humidity dips while the water runs
- **WHEN** a shower was detected at 60.6 % with a window minimum of 50.7 %, and the next reading is 53.4 % while
  the water still runs
- **THEN** the shower continues

#### Scenario: Humidity rise without water
- **WHEN** the humidity rises 8 points and no water is drawn
- **THEN** a shower is detected and ends 5 minutes later, with no shower reported

#### Scenario: Bathroom dries
- **WHEN** a shower has ended, the window minimum is 61 %, the rise 6 points, and the humidity falls to 63.9 %
- **THEN** the bathroom no longer counts as humid, and a new rise of 6 points starts a new shower

### Requirement: Another shower while the bathroom is still humid
After a shower has ended while the bathroom still counts as humid, a draw session that has lasted the configured
next shower time (default 5 minutes) SHALL start a new shower. The litres of that session drawn within the reclassify
window SHALL be reclassified from other draws to mixed draws, as at detection. A shorter session SHALL stay other
draws. Once the bathroom no longer counts as humid, only a new humidity rise starts a shower.

#### Scenario: Second shower
- **WHEN** a shower ended at 18:23, the bathroom still counts as humid, and a session starting at 18:25 has run for
  5 minutes, of 6.7 minutes and 42 L in all
- **THEN** a new shower starts at 18:30, the litres since 18:25 become mixed draws, and it is reported as its own
  shower when it ends

#### Scenario: Washbasin after a shower
- **WHEN** a shower has ended and, while the bathroom still counts as humid, a cold washbasin draw of 12 L runs for
  2.3 minutes
- **THEN** its 12 L stay other draws

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

### Requirement: Long draws count as a shower
When no humidity sensor is configured and the long-draw duration is set (default 0, off), a draw session that has
lasted at least that many minutes SHALL start a shower. The shower SHALL end as any detected shower does, once no
water has been drawn for the shower end time. When a humidity sensor is configured, the long-draw duration SHALL NOT
start a shower, because a long draw without a humidity rise is not in the bathroom, such as a garden hose.

#### Scenario: Long draw without humidity sensor
- **WHEN** no humidity sensor is configured, the long-draw duration is 3 minutes, and a session has run for 3
  minutes
- **THEN** a shower is detected, and it ends 5 minutes after the water stops

#### Scenario: Pause in a long-draw shower
- **WHEN** a shower detected by the long-draw rule pauses for 3 minutes and the water runs again
- **THEN** it stays one shower

#### Scenario: Long draw with a humidity sensor
- **WHEN** a humidity sensor is configured, the long-draw duration is 10 minutes, and a 14-minute draw runs while
  the humidity stays within 1 point
- **THEN** no shower is detected, and its litres are other draws

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
