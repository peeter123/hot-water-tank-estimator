# Spec Delta

## MODIFIED Requirements

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
humidity, by a draw in a still humid bathroom or by the long-draw rule, until it ends. It SHALL be off while the
bathroom only still counts as humid. It SHALL be unavailable when neither humidity sensors nor the long-draw rule
is configured.

#### Scenario: Binary sensor follows detection
- **WHEN** a shower is detected by humidity
- **THEN** the shower detected binary sensor is on

#### Scenario: Off after the water stops
- **WHEN** the water of a detected shower stopped 5 minutes ago and the humidity still reads 80 %
- **THEN** the shower detected binary sensor is off

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Shower detection from bathroom humidity
**Reason**: Replaced by "Humidity starts a shower and the water ends it". The humidity still starts a shower with the
same rise and window, but its fall no longer ends it: a shower ends once no water has been drawn for the shower end
time. The hysteresis now only decides how long the bathroom counts as humid after a shower.
**Migration**: None for the configuration: the humidity rise and window keep their options and defaults. Automations
that use the shower detected binary sensor see it turn off about 5 minutes after the water stops, instead of when
the bathroom has dried.
