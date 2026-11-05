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
