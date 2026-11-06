# Spec Delta

## MODIFIED Requirements

### Requirement: Charge closure measures the error since the previous charge
When a heating run that charges the tank (at least 15 minutes, see tank-model) ends and an energy counter or power
sensor is configured, the integration SHALL compute the
true tank average at the start of the run as `T_charge - (E_run - S) * 1000 / (1.163 * V)`, plus the run's own
mixed-draw drop, other-draw term (at the share in use) and loss term (at the loss coefficient in use), all in K. Here
E_run is the run's energy in kWh and S the start-up energy in use. The charge error SHALL be the model's T_avg at the
run's start minus that true average. It SHALL be stored with the sums of the interval before the run and of the run:
the mixed-draw drop, the other-draw term, the loss term, the heat outside heating runs (see tank-model), E_run and
the hours. The heat outside runs SHALL enter the closure fit as a known heat input of the interval.

The first charge after the model started from a sensor reading (a new entry, or the start of a replay) has no known
charged start. It SHALL be stored as a sensor start: its error is kept as information, but it is not a closure, it
does not count as a calibration sample, and it is not used for learning.

#### Scenario: First run after a new entry
- **WHEN** a new entry started at the tank sensor's reading, and its first heating run ends
- **THEN** that run is stored as a sensor start, the samples sensor does not go up, and the next run is a closure

#### Scenario: Error at a recovery run
- **WHEN** a run with E_run 10.64 kWh ends at T_charge 49.9 C on a 281 L tank, S is 1.8 kWh, and the model held
  T_avg 25.0 C at the run's start
- **THEN** the true start average is 49.9 - 8.84 * 1000 / 326.8 = 22.9 C, and the charge error is +2.1 K

#### Scenario: Interval with heat outside a run
- **WHEN** heat outside heating runs is counted, the interval before a run holds 3.0 kWh of it on a 285 L tank, and
  its charged temperature is 9.05 K higher than that of an interval without it, all other terms the same
- **THEN** the closure is stored with a heat of 3000 / (1.163 * 285) = 9.05 K, it counts as a calibration sample,
  and the fit gives the same parameters as for the interval without it

### Requirement: Calibration state persists
The learned values, the stored intervals, the width estimates, the shower flow history, the undo record of the last
"Hot water ran out" press, the calibration history, the open quiet window and whether a first sensor drop is
awaited after a charge SHALL be saved per entry and restored after a restart or reload. The `recalibrate` action
SHALL replace them with the new fit, except the usable fraction learned from the "Hot water ran out" button and its
undo record, which a replay cannot learn. An open quiet window or an awaited first drop whose last update is more
than 10 minutes before the first update after the restore SHALL be closed at that last update, without the time
between.

#### Scenario: Restart keeps the learned share
- **WHEN** Home Assistant restarts after learning a share of 0.22
- **THEN** the share in use after the restart is 0.22

#### Scenario: Restart keeps the undo
- **WHEN** Home Assistant restarts 5 minutes after an accepted "Hot water ran out" press
- **THEN** the undo button is still available, and undo restores the usable fraction from before the press

#### Scenario: Options saved during a quiet night
- **WHEN** a quiet window opened at 23:00 with the sensor at 57.0 C, the user saves the options at 02:00, and the
  window closes at 07:00 with the sensor at 55.9 C and T_ambient 20 C
- **THEN** one loss estimate is added for the whole 8 hours, 0.1375 / 36.45 = 0.0038 per hour

#### Scenario: Reload before the first sensor drop
- **WHEN** the entry reloads after a charge and before the sensor first falls below `T_ch - tolerance`
- **THEN** the first drop after the reload still adds a width estimate

#### Scenario: Restart after a long downtime
- **WHEN** a quiet window opened at 23:00 with the sensor at 57.0 C, its last update before a restart was at 04:00 with
  the sensor at 56.3 C, and Home Assistant is back at 07:00 with the tank sensor unavailable
- **THEN** the window closes at 04:00 and gives one estimate over its 5 hours, and the 3 hours of downtime are not in
  it

#### Scenario: Store from before the change
- **WHEN** a store saved without the open quiet window and the first-drop state is loaded
- **THEN** it loads with no open window and no awaited first drop, and the rest of the calibration is kept

### Requirement: Loss learning from quiet windows
After every window of at least 5 hours without a draw or heating, the integration SHALL estimate the loss
coefficient from the tank sensor's fall, while the sensor still reads within the tolerance of T_ch. A window SHALL
open no earlier than 1 hour after a run end or after heat outside a heating run (see tank-model), because the sensor
still settles then. The estimate is
`k = rate / (T_mean - T_ambient)`, where rate is the fall in K/h, T_mean the window's mean sensor reading and
T_ambient the window's mean ambient temperature in use (see tank-model). From 3 estimates on, their mean SHALL be the
loss coefficient in use and the one the closure fit holds. With fewer, the mean of the estimates so far SHALL be the
loss coefficient in use while fewer than 5 intervals are stored, or always when no energy counter or power sensor is
configured; otherwise the closure fit SHALL fit k as well.

#### Scenario: Quiet night
- **WHEN** the sensor falls from 57.0 to 55.9 C over 8 hours with no draw and no heating, with T_ambient 20 C
- **THEN** the window's estimate is 0.1375 / 36.45 = 0.0038 per hour

#### Scenario: Quiet night with an ambient sensor
- **WHEN** the same window has an ambient sensor whose readings average 16.0 C over it
- **THEN** the window's estimate is 0.1375 / 40.45 = 0.0034 per hour

#### Scenario: Settle after heat outside a run
- **WHEN** heat outside a heating run last raised T_avg at 13:00, and the tank is quiet from then on
- **THEN** no quiet window opens before 14:00

### Requirement: Thermocline width from the first sensor drop
When the tank sensor first falls below `T_ch - tolerance` after a charge, while heating is not active, the
integration SHALL estimate the width as `2 * (h - f_e)`. Here f_e is the cold fraction of the energy balance at that
moment. A heating run (also a short one) or heat outside a heating run between the charge and that drop SHALL cancel
the estimate until the next charge, because its heat changes the layers the estimate assumes. The learned width SHALL
be the mean of the last 10 estimates, applied after at least 3.

#### Scenario: Sensor starts to fall
- **WHEN** h is 0.5 and the energy balance's cold fraction is 0.33 when the sensor first drops after a charge
- **THEN** the estimate is 2 * (0.5 - 0.33) = 0.34

#### Scenario: Short run before the first drop
- **WHEN** a short heating run comes between a charge and the sensor's first drop
- **THEN** that drop adds no width estimate

## ADDED Requirements

### Requirement: An interval with a short run is not a closure
When the interval before a heating run holds a heating run shorter than 15 minutes (see tank-model), its closure
SHALL be stored as excluded with the reason `short_run_in_interval`. It is not a calibration sample and is not used
for learning, because the closure equation has one start-up energy per interval.

#### Scenario: Run cut off before a full run
- **WHEN** a run of 6 minutes ends without a charge, and the next run of 50 minutes ends with a charge
- **THEN** the closure of the 50-minute run is excluded as `short_run_in_interval`, and the samples sensor does not
  go up

#### Scenario: Next interval counts again
- **WHEN** the run after that excluded closure ends with no short run in its interval
- **THEN** its closure is a calibration sample
