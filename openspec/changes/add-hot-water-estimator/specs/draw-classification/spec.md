# Spec Delta

## Purpose

Decides how much of the water measured by a whole-house water meter came out of the hot water tank. This lets the
tank model use a meter that also counts toilet flushes, cold taps and appliances.

## ADDED Requirements

### Requirement: Litres drawn come from a total water meter
The litres drawn SHALL be the increase of the configured total water meter between two readings, converted to
litres from the meter's unit (m3, L, gal or ft3). A decrease, or a non-numeric reading, SHALL NOT count as a draw.
The next valid reading SHALL become the new starting point.

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
(default 60 minutes). Detection SHALL end once every sensor is below its window minimum plus half the rise.

#### Scenario: Shower starts
- **WHEN** the lowest bathroom humidity of the last 60 minutes is 61 % and the sensor now reads 72 %
- **THEN** a shower is detected

#### Scenario: Shower ends with hysteresis
- **WHEN** a shower is detected, the window minimum is 61 %, the rise 6 points, and the humidity falls to 65 %
- **THEN** the shower is still detected, and it ends once the humidity is below 64 %

### Requirement: Shower detection is exposed
The integration SHALL expose a binary sensor that is on while a shower or bath is detected, by humidity or by the
long-draw rule. It SHALL be unavailable when neither detection method is configured.

#### Scenario: Binary sensor follows detection
- **WHEN** a shower is detected by humidity
- **THEN** the shower detected binary sensor is on

### Requirement: Long draws count as a shower
When the long-draw duration is set (default 0, off), a draw session that has lasted at least that many minutes
SHALL count as a shower from that moment until the session ends. This is for homes without a bathroom humidity
sensor.

#### Scenario: Long draw without humidity sensor
- **WHEN** the long-draw duration is 3 minutes and a session has run for 3 minutes
- **THEN** a shower is detected until the session ends

### Requirement: Litres in a shower session count fully as hot
Every litre drawn while a shower is detected SHALL count as hot water at the mix temperature. When detection
starts during a session, the litres already drawn in that session SHALL be recounted as hot. Humidity rises about
a minute after a shower starts, and the long-draw rule fires only after its duration.

#### Scenario: Recount at detection
- **WHEN** a session has drawn 7 litres at the other-draws share of 0.3 before a shower is detected
- **THEN** the remaining 7 * 0.7 = 4.9 litres are added to the hot water drawn

### Requirement: Other draws count at a configured share
A litre drawn while no shower is detected SHALL count as the configured other-draws hot share of a litre (0-1,
default 0.3). This covers hot taps mixed in with cold toilet flushes and appliances.

#### Scenario: Toilet flush or tap
- **WHEN** 6 litres are drawn with no shower detected and the share is 0.3
- **THEN** 1.8 litres are counted as hot
