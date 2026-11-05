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
  - humidity rise 6 points and humidity window 60 min;
  - shower end time 5 min and next shower time 5 min;
  - long-draw duration 0 (off) and reclassify window 10 min;
  - session gap 60 s and maximum draw per reading 100 L;
  - power threshold 100 W.

#### Scenario: Existing entry after the update
- **WHEN** an entry created before the shower end time and the next shower time existed is loaded
- **THEN** it uses their defaults, 5 min each, and its other tuning values are unchanged

### Requirement: State survives a restart
After a Home Assistant restart or an entry reload, each tank SHALL restore:
- T_avg and T_ch;
- the last water meter reading and the last energy counter reading;
- the heating-run state, including the start-up energy used;
- the current draw session;
- the humidity window history, and whether the bathroom still counts as humid after a shower that has ended;
- the end of the last draw and the time T_avg was last reset (see draw-classification and calibration);
- the shower in progress, with its flow so far and the time of its last meter increase;
- the last ambient reading and when it was last good, for a sensor that is still configured.

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

### Requirement: Entities and units
Each tank SHALL provide sensors (state class measurement) for:
- tank water remaining (L), named "Hot water remaining";
- shower water remaining (L), named "Shower water remaining";
- percent charged (%), named "Charge level";
- shower minutes remaining (min), named "Shower time remaining";
- heat loss (W), named "Heat loss";
- charged temperature, tank average and cold water temperature (C).

It SHALL also provide a shower detected binary sensor, a "Hot water ran out" button, an "Undo hot water ran out"
button, a "Shower flow" number (L/min), a "Shower flow locked" switch, a "Tank sensor temperature" diagnostic
sensor, the two shower timing and the two shower countdown diagnostic sensors, and the calibration diagnostic
sensors.
Names SHALL be translated, without emoji. The user-facing names differ from the model's vocabulary where the
model's terms read wrongly: "tank water" alone does not say that it is hot, and "percent charged" at 100 % beside
fewer litres than the tank holds reads as an error, while "charge level" compares with the last charge.

#### Scenario: Units shown
- **WHEN** the entities are listed
- **THEN** both remaining sensors are in litres, the charge level in %, the minutes sensor in min, the heat loss in
  W, the shower flow in L/min, the two shower timing sensors in min, and the three temperatures and the tank sensor
  temperature in degrees Celsius

#### Scenario: Names shown
- **WHEN** a new entry titled "Hot Water Tank" is added
- **THEN** its entities include "Hot Water Tank Hot water remaining", "Hot Water Tank Charge level", "Hot Water Tank
  Heat loss", "Hot Water Tank Hot water ran out" and "Hot Water Tank Shower flow"

## ADDED Requirements

### Requirement: Shower timing diagnostic sensors
Each tank SHALL provide two diagnostic sensors (min, device class duration, no state class) with the shower timing
options in use, named as the options: "Shower end after no water" (the shower end time) and "New shower draw while
humid" (the next shower time). The second SHALL be unavailable while no humidity sensor is configured.

#### Scenario: Defaults shown
- **WHEN** an entry with a humidity sensor uses the default shower timing
- **THEN** "Shower end after no water" is 5 min and "New shower draw while humid" is 5 min

#### Scenario: Option saved
- **WHEN** the user saves the options with the shower end time at 7.5 min
- **THEN** after the reload "Shower end after no water" is 7.5 min

#### Scenario: No humidity sensor
- **WHEN** an entry has no humidity sensor and a long-draw duration of 8 min
- **THEN** "Shower end after no water" is 5 min and "New shower draw while humid" is unavailable

### Requirement: Shower countdown diagnostic sensors
Each tank SHALL provide two diagnostic timestamp sensors, unknown when there is nothing to count down: "Shower
ends", the shower end of the shower in progress; and "Draw counts as shower", while no shower is in progress, the
start of the draw session in progress plus the next shower time (bathroom still humid) or plus the long-draw duration
(no humidity sensor). Both SHALL be unavailable while no detection method is configured.

#### Scenario: Shower ends counts down
- **WHEN** a detected shower's last meter increase is at 20:25:21 and the shower end time is 5 min
- **THEN** "Shower ends" is 20:30:21, and after the shower has ended it is unknown

#### Scenario: Draw in the humid bathroom
- **WHEN** a shower has ended, the bathroom still counts as humid, the next shower time is 5 min and a draw session
  starts at 20:40:00
- **THEN** "Draw counts as shower" is 20:45:00, and it is unknown again once the session ends at 20:42:00 (its last
  increase at 20:41:00 and a session gap of 60 s), with no further reading

#### Scenario: Long draw without humidity sensor
- **WHEN** an entry has no humidity sensor, the long-draw duration is 8 min and a draw session starts at 07:00:00
- **THEN** "Draw counts as shower" is 07:08:00
