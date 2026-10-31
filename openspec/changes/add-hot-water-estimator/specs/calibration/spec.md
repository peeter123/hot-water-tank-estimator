# Spec Delta

## Purpose

Fits each tank's parameters to that tank: from recorder history at setup, at every heating run end afterwards, and
from the user's report that a shower ran cold. Every installation then gets values that fit its own house, not
those of the development installation.

## ADDED Requirements

### Requirement: Learned parameters and their bounds
The integration SHALL learn the following parameters, each kept within its bounds:

| Parameter | Bounds |
|---|---|
| other-draws hot share | 0-0.6 |
| start-up energy | 0-3 kWh |
| loss coefficient | 0.001-0.015 per hour |
| thermocline width | 0.1-0.6 |
| usable fraction | 0.5-0.98 |

Until a parameter has been learned, the configured option value SHALL be used. Once learned, the learned value SHALL
be used, unless the user has locked that parameter in the options. Removing a lock SHALL discard the value learned
before the lock, so the option value applies until the next fit. Each update of a learned parameter SHALL change it
by at most a quarter of its bound range, except the "Shower ran cold" button, which records a user observation.

#### Scenario: Locked parameter
- **WHEN** the user locks the other-draws hot share at 0.25
- **THEN** the model uses 0.25, and learning neither changes it nor reports it as learned

#### Scenario: Out-of-bounds fit
- **WHEN** the start-up energy in use is 2.9 kWh and a fit gives 4.2 kWh
- **THEN** the learned start-up energy is 3 kWh

### Requirement: Charge closure measures the error since the previous charge
When a heating run ends and an energy counter or power sensor is configured, the integration SHALL compute the
true tank average at the start of the run as `T_charge - (E_run - S) * 1000 / (1.163 * V)`, plus the run's own
mixed-draw drop, other-draw term (at the share in use) and loss term (at the loss coefficient in use), all in K. Here
E_run is the run's energy in kWh and S the start-up energy in use. The charge error SHALL be the model's T_avg at the
run's start minus that true average. It SHALL be stored with the sums of the interval before the run and of the run:
the mixed-draw drop, the other-draw term, the loss term, E_run and the hours.

#### Scenario: Error at a recovery run
- **WHEN** a run with E_run 10.64 kWh ends at T_charge 49.9 C on a 281 L tank, S is 1.8 kWh, and the model held
  T_avg 25.0 C at the run's start
- **THEN** the true start average is 49.9 - 8.84 * 1000 / 326.8 = 22.9 C, and the charge error is +2.1 K

### Requirement: Charge closures exclude sensor bounds
The interval sums used for learning SHALL come from the energy balance alone, without the sensor bounds, so that
learning measures the balance and not the corrections.

#### Scenario: Bound applied during the interval
- **WHEN** a sensor bound raised T_avg by 3 K during an interval
- **THEN** the interval's sums do not include those 3 K

### Requirement: Learning at each charge
After each charge closure, the integration SHALL refit the other-draws hot share, the start-up energy and the loss
coefficient. The fit is a least-squares fit of the closure equation over the stored intervals, with older intervals
weighted down by a forgetting factor of 0.95 per interval. It SHALL apply the fit only once at least 5 intervals are
stored. When at least 3 quiet-window loss estimates exist, the fit SHALL hold the loss coefficient at their mean and
fit only the share and the start-up energy, because the loss and other-draw sums move together and closures alone
cannot separate them.

#### Scenario: Too few intervals
- **WHEN** 4 intervals are stored
- **THEN** the options or setup-fit values stay in use

#### Scenario: Step limit
- **WHEN** the share in use is 0.2 and the fit gives 0.5
- **THEN** the share becomes 0.35 (0.2 plus a quarter of the 0-0.6 range)

### Requirement: Charge closures need a heat measurement
When neither an energy counter nor a power sensor is configured, the integration SHALL NOT compute charge closures.
It SHALL learn the loss coefficient from quiet windows only.

#### Scenario: Binary-only heating source
- **WHEN** only a heating-active binary sensor is configured
- **THEN** no charge error is reported, and the hot share and start-up energy stay at their option values

### Requirement: Loss learning from quiet windows
After every window of at least 5 hours without a draw or heating, the integration SHALL estimate the loss
coefficient from the tank sensor's fall, while the sensor still reads within the tolerance of T_ch. A window SHALL
open no earlier than 1 hour after a run end, because the sensor still settles then. The estimate is
`k = rate / (T_mean - T_ambient)`, where rate is the fall in K/h and T_mean the window's mean sensor reading. From 3
estimates on, their mean SHALL be the loss coefficient in use and the one the closure fit holds. With fewer, the
closure fit SHALL fit k as well once 5 intervals are stored.

#### Scenario: Quiet night
- **WHEN** the sensor falls from 57.0 to 55.9 C over 8 hours with no draw and no heating, with T_ambient 20 C
- **THEN** the window's estimate is 0.1375 / 36.45 = 0.0038 per hour

### Requirement: Thermocline width from the first sensor drop
When the tank sensor first falls below `T_ch - tolerance` after a charge, while heating is not active, the
integration SHALL estimate the width as `2 * (h - f_e)`. Here f_e is the cold fraction of the energy balance at that
moment. The learned width SHALL be the mean of the last 10 estimates, applied after at least 3.

#### Scenario: Sensor starts to fall
- **WHEN** h is 0.5 and the energy balance's cold fraction is 0.33 when the sensor first drops after a charge
- **THEN** the estimate is 2 * (0.5 - 0.33) = 0.34

### Requirement: Usable fraction from a cold shower
The integration SHALL provide a "Shower ran cold" button for each tank. Pressing it SHALL set the learned usable
fraction to the current cold fraction, within its bounds. It SHALL then set T_avg so that the tank water remaining
is 0, because the user has just observed an empty tank.

#### Scenario: Shower runs cold early
- **WHEN** the user presses the button while the cold fraction is 0.72 and the usable fraction is 0.85
- **THEN** the usable fraction becomes 0.72, and tank water remaining is 0 L

### Requirement: Setup fit from recorder history
When an entry is created, and when the `hot_water_tank_estimator.recalibrate` action runs, the integration SHALL
replay up to the configured number of days of recorder history (default 30) of the entry's sources through the
model. It fits the other-draws hot share, start-up energy, loss coefficient and thermocline width, using the same
closure equation and width estimate as live learning. The replay SHALL run in the background, without blocking Home
Assistant.

#### Scenario: New entry with a month of history
- **WHEN** a user adds a tank whose sources have 30 days of history with 26 heating runs
- **THEN** after the replay the four parameters are set from the fit, and the calibration samples sensor reads 25

#### Scenario: Not enough history
- **WHEN** the history has fewer than 5 charge closures
- **THEN** the parameters fitted from closures stay at their option values, and the model keeps running

### Requirement: Calibration state persists
The learned values, the stored intervals, the width estimates and the calibration history SHALL be saved per entry
and restored after a restart or reload. The `recalibrate` action SHALL replace them with the new fit, except the
usable fraction learned from the "Shower ran cold" button, which a replay cannot learn.

#### Scenario: Restart keeps the learned share
- **WHEN** Home Assistant restarts after learning a share of 0.22
- **THEN** the share in use after the restart is 0.22

### Requirement: Diagnostic sensors for calibration
Each tank SHALL provide diagnostic-category sensors for:
- the other-draws hot share, start-up energy (kWh), loss coefficient (per hour), thermocline width (%) and usable
  fraction (%) in use;
- the number of calibration samples (charge closures stored);
- the last charge error (K);
- the mean absolute charge error over the last 10 closures (K).

Each parameter sensor SHALL have a `source` attribute: option, setup fit, learned or locked.

#### Scenario: After a week of use
- **WHEN** the tank has had 9 charge closures since setup
- **THEN** the samples sensor counts them, the error sensors show the last and the mean absolute error, and each
  parameter sensor shows its value and source
