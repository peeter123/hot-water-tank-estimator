# Spec Delta

## ADDED Requirements

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
