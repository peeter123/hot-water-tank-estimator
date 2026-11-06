# Spec Delta

## MODIFIED Requirements

### Requirement: Draw and heat defaults
The defaults for draws, losses and heat input SHALL be those in the scenario below. The shower flow is a learned
parameter, not a tuning value: its default applies until the first shower is learned, and only its lock is an option.

#### Scenario: Fresh entry, draws and heat
- **WHEN** a user finishes the config flow without opening the options
- **THEN** the defaults are:
  - loss coefficient 0.004 per hour;
  - other-draws hot share 0.2 and start-up energy 0 kWh;
  - shower flow 7.5 L/min;
  - humidity rise 6 points, humidity window 60 min and humidity silence time 2 h;
  - shower end time 5 min and next shower time 5 min;
  - long-draw duration 0 (off) and reclassify window 10 min;
  - session gap 60 s and maximum draw per reading 100 L;
  - power threshold 100 W.

#### Scenario: Existing entry after the update
- **WHEN** an entry created before the humidity silence time existed is loaded
- **THEN** it uses its default, 2 h, and its other tuning values are unchanged

### Requirement: State survives a restart
After a Home Assistant restart or an entry reload, each tank SHALL restore:
- T_avg and T_ch;
- the last water meter reading and the last energy counter reading;
- the heating-run state, including the start-up energy used;
- the current draw session;
- the humidity window history, and whether the bathroom still counts as humid after a shower that has ended;
- the time of each humidity sensor's last report, and whether its last state was unavailable;
- the end of the last draw and the time T_avg was last reset (see draw-classification and calibration);
- the shower in progress, with its flow so far, its start and the time of its last meter increase;
- the last ambient reading and when it was last good, for a sensor that is still configured;
- the short runs and the heat outside runs since the last charge (see tank-model).

On the first start, with nothing restored, the tank SHALL start charged at the tank sensor's reading. If that is
unavailable, it SHALL start at 50 C.

#### Scenario: Restart
- **WHEN** Home Assistant restarts while T_avg is 41.2 C and T_ch 56.0 C
- **THEN** after the restart T_avg is 41.2 C and T_ch 56.0 C

#### Scenario: First start
- **WHEN** a new entry starts and the tank sensor reads 56 C
- **THEN** T_avg and T_ch are 56 C

#### Scenario: Restart in the humid bathroom after a shower
- **WHEN** Home Assistant restarts 10 minutes after a shower ended, while the bathroom still counts as humid
- **THEN** no new shower starts from the humidity after the restart, and a draw needs the next shower time to start
  one

#### Scenario: Restart during a shower
- **WHEN** Home Assistant restarts during a detected shower and is back 2 minutes after the water stopped
- **THEN** the shower is still detected, and it ends 5 minutes after its last meter increase

#### Scenario: Reload during a humidity silence
- **WHEN** a humidity sensor last reported 90 minutes ago, the silence time is 2 hours, and the entry reloads
- **THEN** the sensor is silent 30 minutes after the reload, not 2 hours after it

### Requirement: Diagnostics
The integration SHALL provide config entry diagnostics with:
- the entry's options;
- the current model state;
- whether each source is available, and for each humidity sensor its last report and whether it is silent;
- whether shower detection is on the fallback because no humidity sensor reports;
- the open repair issues of the entry;
- the most recent 100 model events, each with its time, kind, input change, and T_avg and T_ch before and after;
- the calibration state: the parameters in use with their sources, the stored intervals with their charge errors,
  the width estimates, the shower flow history and the undo record of the last "Hot water ran out" press.

Event kinds are draw, heat (marked when it came outside a heating run), charge, short run, loss, sensor bound,
calibration, hot water ran out (accepted, rejected with its reason, or undone) and shower flow.

#### Scenario: Download diagnostics
- **WHEN** a user downloads diagnostics for a tank
- **THEN** the file contains T_avg, T_ch, the options and the recent events

#### Scenario: Rejected press in the diagnostics
- **WHEN** a "Hot water ran out" press was rejected because no draw ended in the last 20 minutes
- **THEN** the events contain a hot water ran out event marked rejected, with that reason

#### Scenario: Silent humidity sensor in the diagnostics
- **WHEN** the only humidity sensor last reported 3 hours ago and the silence time is 2 hours
- **THEN** the diagnostics show its last report, mark it silent, show the fallback on, and list its repair issue

### Requirement: Shower countdown diagnostic sensors
Each tank SHALL provide two diagnostic timestamp sensors, unknown when there is nothing to count down: "Shower
ends", the shower end of the shower in progress; and "Draw counts as shower", while no shower is in progress, the
start of the draw session in progress plus the next shower time (bathroom still humid, or no humidity sensor reports)
or plus the long-draw duration (no humidity sensor). Both SHALL be unavailable while no detection method is
configured.

#### Scenario: Shower ends counts down
- **WHEN** a detected shower's last meter increase is at 20:25:21 and the shower end time is 5 min
- **THEN** "Shower ends" is 20:30:21, and after the shower has ended it is unknown

#### Scenario: Draw in the humid bathroom
- **WHEN** a shower has ended, the bathroom still counts as humid, the next shower time is 5 min and a draw session
  starts at 20:40:00
- **THEN** "Draw counts as shower" is 20:45:00, and it is unknown again from just after 20:42:00, when the session
  ends (its last increase at 20:41:00 and a session gap of 60 s), with no further reading

#### Scenario: Long draw without humidity sensor
- **WHEN** an entry has no humidity sensor, the long-draw duration is 8 min and a draw session starts at 07:00:00
- **THEN** "Draw counts as shower" is 07:08:00

#### Scenario: Draw while the humidity sensor is silent
- **WHEN** the only humidity sensor is silent, the next shower time is 5 min and a draw session starts at 17:54:32
- **THEN** "Draw counts as shower" is 17:59:32

## ADDED Requirements

### Requirement: Repair issues for sources that stay unavailable
Each tank SHALL raise one repair issue per source entity that has been unavailable, unknown, non-numeric or missing
for at least its threshold: 30 min for the water meter, energy counter, heat power and heating detector; 1 h for the
tank sensor; 2 h for a humidity sensor, which also counts as out while silent; 3 h for flow, return, cold water and
ambient. The issue SHALL name the tank and the entity and say what the estimate loses, and go once the source is back.

#### Scenario: Water meter out for 40 minutes
- **WHEN** the water meter of the tank "Hot Water Tank" has been unavailable for 40 minutes
- **THEN** a repair issue names "Hot Water Tank" and the meter's entity, and says that draws are not counted

#### Scenario: Short dropout
- **WHEN** the tank sensor is unavailable for 2 seconds, or the heating detector for 19 minutes
- **THEN** no repair issue is raised

#### Scenario: Source back
- **WHEN** a repair issue is open for the energy counter and the counter reports a number again
- **THEN** the issue is removed at once

#### Scenario: Silent humidity sensor
- **WHEN** the only humidity sensor last reported 2 hours ago and the silence time is 2 hours
- **THEN** a repair issue names the sensor and says that shower detection is on the fallback by draw length

#### Scenario: Entry removed
- **WHEN** a tank with an open repair issue is removed
- **THEN** its repair issues are removed with it
