# Spec Delta

## MODIFIED Requirements

### Requirement: Learned parameters and their bounds
The integration SHALL learn the following parameters, each kept within its bounds:

| Parameter | Bounds |
|---|---|
| other-draws hot share | 0-0.6 |
| start-up energy | 0-3 kWh |
| loss coefficient | 0.001-0.015 per hour |
| thermocline width | 0.1-0.6 |
| usable fraction | 0.5-0.98 |
| shower flow | 3-20 L/min |

Until a parameter has been learned, the configured option value SHALL be used; for the shower flow that is its
default of 7.5 L/min. Once learned, the learned value SHALL be used, unless the user has locked that parameter in the
options. Removing a lock SHALL discard the value learned before the lock, so the option value applies until the next
fit. Each update of a learned parameter SHALL change it by at most a quarter of its bound range, except the "Hot
water ran out" button, which records a user observation, and the shower flow, which is the median of recent showers.

#### Scenario: Locked parameter
- **WHEN** the user locks the other-draws hot share at 0.25
- **THEN** the model uses 0.25, and learning neither changes it nor reports it as learned

#### Scenario: Out-of-bounds fit
- **WHEN** the start-up energy in use is 2.9 kWh and a fit gives 4.2 kWh
- **THEN** the learned start-up energy is 3 kWh

### Requirement: Loss learning from quiet windows
After every window of at least 5 hours without a draw or heating, the integration SHALL estimate the loss
coefficient from the tank sensor's fall, while the sensor still reads within the tolerance of T_ch. A window SHALL
open no earlier than 1 hour after a run end, because the sensor still settles then. The estimate is
`k = rate / (T_mean - T_ambient)`, where rate is the fall in K/h, T_mean the window's mean sensor reading and
T_ambient the window's mean ambient temperature in use (see tank-model). From 3 estimates on, their mean SHALL be the
loss coefficient in use and the one the closure fit holds. With fewer, the closure fit SHALL fit k as well once 5
intervals are stored.

#### Scenario: Quiet night
- **WHEN** the sensor falls from 57.0 to 55.9 C over 8 hours with no draw and no heating, with T_ambient 20 C
- **THEN** the window's estimate is 0.1375 / 36.45 = 0.0038 per hour

#### Scenario: Quiet night with an ambient sensor
- **WHEN** the same window has an ambient sensor whose readings average 16.0 C over it
- **THEN** the window's estimate is 0.1375 / 40.45 = 0.0034 per hour

### Requirement: Setup fit from recorder history
When an entry is created, and when the `hot_water_tank_estimator.recalibrate` action runs, the integration SHALL
replay up to the configured number of days of recorder history (default 30) of the entry's sources through the
model. It fits the other-draws hot share, start-up energy, loss coefficient and thermocline width, using the same
closure equation and width estimate as live learning, and fills the shower flow history from the showers it finds.
The replay SHALL use the ambient sensor's history when one is configured. It SHALL run in the background.

#### Scenario: New entry with a month of history
- **WHEN** a user adds a tank whose sources have 30 days of history with 26 heating runs
- **THEN** after the replay the four parameters are set from the fit, and the calibration samples sensor reads 25

#### Scenario: Not enough history
- **WHEN** the history has fewer than 5 charge closures
- **THEN** the parameters fitted from closures stay at their option values, and the model keeps running

#### Scenario: Showers in the history
- **WHEN** the replayed history holds 14 detected showers of at least 3 minutes of flow
- **THEN** the shower flow history holds the last 10 of them, and the shower flow in use is their median

### Requirement: Calibration state persists
The learned values, the stored intervals, the width estimates, the shower flow history, the undo record of the last
"Hot water ran out" press and the calibration history SHALL be saved per entry and restored after a restart or
reload. The `recalibrate` action SHALL replace them with the new fit, except the usable fraction learned from the
"Hot water ran out" button and its undo record, which a replay cannot learn.

#### Scenario: Restart keeps the learned share
- **WHEN** Home Assistant restarts after learning a share of 0.22
- **THEN** the share in use after the restart is 0.22

#### Scenario: Restart keeps the undo
- **WHEN** Home Assistant restarts 5 minutes after an accepted "Hot water ran out" press
- **THEN** the undo button is still available, and undo restores the usable fraction from before the press

## ADDED Requirements

### Requirement: Usable fraction from hot water running out
The integration SHALL provide a "Hot water ran out" button for each tank. The user presses it when a shower or a
tap that was hot runs cold. An accepted press SHALL set the learned usable fraction to the cold fraction at the end
of the last draw, within its bounds. It SHALL then lower T_avg by the drop that makes tank water remaining 0 at that
moment, and apply that drop to the current T_avg, so heat added since that moment is kept.

#### Scenario: Shower runs cold early
- **WHEN** the last draw ended 8 minutes ago with a cold fraction of 0.72, the usable fraction is 0.85, and no heat
  was added since
- **THEN** a press sets the usable fraction to 0.72, and tank water remaining is 0 L

#### Scenario: A tap runs cold
- **WHEN** a kitchen tap draw that is not a shower ends with a cold fraction of 0.80, and the user presses within 20
  minutes
- **THEN** the press is accepted, and the usable fraction becomes 0.80

#### Scenario: Heat added since the draw
- **WHEN** the last draw ended at a cold fraction of 0.75 with tank water remaining 28 L, and a heating run has
  added 1.5 K to T_avg since
- **THEN** a press sets the usable fraction to 0.75, which removes those 28 L with a drop D of 0, and the 1.5 K added
  since stays: tank water remaining is `V * 1.5 / (T_ch - T_cold)`

#### Scenario: Locked usable fraction
- **WHEN** the usable fraction is locked at 0.85 and the last draw ended at a cold fraction of 0.78
- **THEN** a press keeps the usable fraction at 0.85, and lowers T_avg so that tank water remaining was 0 at the end
  of that draw

#### Scenario: Charge since the draw
- **WHEN** the usable fraction is locked at 0.85, the last draw ended at a cold fraction of 0.78, and a heating run
  ended after it, so the tank is charged
- **THEN** a press keeps the usable fraction at 0.85 and leaves T_avg at its charged value

### Requirement: Implausible presses are rejected with a notification
A press of "Hot water ran out" SHALL be rejected when no draw session is running or has ended within the last 20
minutes, or when the tank sensor read at least `T_ch - tolerance` at the end of that draw. While that sensor reads
hot, the cold layer is below it and cannot have reached the outlet at the top. A rejected press SHALL change nothing
and SHALL show a notification that names the reason. Without a sensor reading at that moment, the sensor check SHALL
be skipped.

#### Scenario: No recent draw
- **WHEN** the user presses the button and the last draw session ended 45 minutes ago
- **THEN** nothing changes, and a notification says that no water was drawn in the last 20 minutes

#### Scenario: Sensor still hot
- **WHEN** the last draw ended 5 minutes ago, T_ch is 57 C, the tolerance 1.5 K, and the tank sensor read 55.8 C at
  the end of that draw
- **THEN** nothing changes, and a notification says that the tank sensor still read 55.8 C, so the tank was not empty

#### Scenario: Draw still running
- **WHEN** a draw session is still running when the user presses
- **THEN** the press applies to the cold fraction at the moment of the press

### Requirement: Undo of the last press
The integration SHALL provide an "Undo hot water ran out" button for each tank. Until the next charge after an
accepted press, undo SHALL restore the usable fraction and its source from before the press, and raise T_avg by the
drop the press applied, so draws made since stay counted. After that charge, undo SHALL restore only the usable
fraction, for 24 hours after the charge. Undo SHALL act on the last accepted press only.

#### Scenario: Undo before the next charge
- **WHEN** a press lowered the usable fraction from 0.85 to 0.72 and T_avg by 12 K, and 30 L were drawn since
- **THEN** undo restores the usable fraction to 0.85 and raises T_avg by 12 K, and the 30 L stay counted

#### Scenario: Undo after a charge
- **WHEN** a press lowered the usable fraction from 0.85 to 0.60, and a heating run ended 3 hours ago
- **THEN** undo restores the usable fraction to 0.85 and leaves T_avg at its charged value

#### Scenario: Nothing to undo
- **WHEN** no press was accepted, the last press was undone already, or its undo time has run out
- **THEN** the undo button is unavailable

### Requirement: Shower flow from detected showers
Each detected shower with at least 3 minutes of flow SHALL add its flow to the shower flow history: its mixed litres
divided by its minutes of flow, leaving out pauses longer than the session gap. The history SHALL keep the last 10
flows, also while the shower flow is locked. The shower flow in use SHALL be the median of the history, within its
bounds, unless it is locked.

#### Scenario: Two people, two flows
- **WHEN** the history holds 7.4, 7.6, 7.5, 12.1, 11.8, 7.3, 12.0, 7.7, 11.9 and 7.5 L/min
- **THEN** the shower flow in use is 7.65 L/min, and the history's lowest and highest flows are 7.3 and 12.1 L/min

#### Scenario: Short draw is no shower flow sample
- **WHEN** a detected shower has 2 minutes of flow
- **THEN** the shower flow history does not change

#### Scenario: Shower with a pause
- **WHEN** a detected shower draws 60 L over 8 minutes of flow, with a 3-minute pause in the middle
- **THEN** its flow is 7.5 L/min

## REMOVED Requirements

### Requirement: Usable fraction from a cold shower
**Reason**: Replaced by "Usable fraction from hot water running out". The button is renamed to "Hot water ran out",
counts for taps too, applies to the end of the last draw, rejects implausible presses and can be undone.
**Migration**: The button gets a new key, so its entity ID changes from `button.<tank>_shower_ran_cold` to
`button.<tank>_hot_water_ran_out`. Dashboards and automations that use the old entity ID need the new one.
