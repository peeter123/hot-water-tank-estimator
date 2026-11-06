# Design

## Context

See proposal.md, Why. The parts this change touches work as follows today.

- **Heating runs** (`model.py`). The first configured detector decides whether a run is active:
  - the heating-active binary sensor;
  - else the heat power above the power threshold;
  - else 10 minutes after the last energy counter increase.

  While a run is active, each counter increase (or the integrated power) raises T_avg by `dE * 1000 / (1.163 * V)`
  K, after the run's start-up energy S. Every run end sets `T_avg = T_ch = T_charge` and starts a new calibration
  interval. Counter increases up to 10 minutes after a run end (the counter lag) go to that run's closure only. Any
  other counter increase outside a run is dropped.
- **Closures** (`calibration.py`). The closure equation over the interval and the run, with `C = 1.163 * V / 1000`
  kWh/K, is:

  ```text
  t_ch_prev - t_charge + E_run / C - mixed = k * loss + share * other + S / C
  ```

  A closure whose own run is shorter than `MIN_RUN_MINUTES` (15) is excluded as `short_run`. A closure where one
  source was unavailable for more than 10 % of the interval is excluded as `source_unavailable:<source>`.
- **Calibrator windows.** The open quiet window (`_window`) and the first-drop state (`_drop`: none, `armed`, `hot`
  or `done`) live only in memory. `_last_run_end` and the waiting closure are saved already.
- **Humidity.** `on_humidity` with None (unavailable) records nothing, so the sensor's last reading stays in its
  window. The runtime listens to `state_changed` only. A sensor that reports an unchanged value causes no event, and
  Home Assistant then only moves `State.last_reported`. A sensor that stops reporting looks the same as one that
  reports unchanged values.
- **Availability.** The model tracks unavailable seconds per source within the calibration interval, for the
  closure exclusion only. The diagnostics show the current availability of each source. Nothing alerts the user.
- **Replays.** The setup fit and `scripts/backtest.py` feed recorded states through the same model, with a tick every
  5 minutes. The recorder's history holds state changes, not unchanged reports.
- **Store.** `TankModel.from_dict` rejects another `STATE_VERSION` and ignores unknown keys. `Calibrator.restore` and
  `Closure.from_dict` also ignore unknown keys. Missing required keys drop the model state or the calibration.

## Goals / Non-Goals

**Goals:**
- Every rule is in the pure modules, so the replays follow it. The only exceptions are the repair issues and
  `last_reported`, which exist only in Home Assistant.
- A store saved by this change loads in the previous release, and the previous release's store loads here.
- With the sources of the development installation, the October and November backtests change only where this change
  means them to: the shower of 2026-10-10.

**Non-Goals:**
- No change to the detector order, the detector hold, the counter lag, the 10 % unavailable exclusion or the ambient
  fallback.
- No new entity. The backup and the silence show in the diagnostics and the repair issues.

## Decisions

### D1: A short run adds its heat but does not charge

A run is short when `t_end - run_start < 15 min`, where t_end is the run end used for the charge: the last counter
increase for a counter timeout, else the moment the detector turned off.
- **Heat.** The run's heat counts as for any run: T_avg rises by `(dE - S_left) * 1000 / (1.163 * V)` K per increase,
  and T_ch is at least T_avg. So a short run uses its start-up energy first, because it is a run. Counter increases
  in the counter lag after a short run are applied to T_avg the same way, because no charge has absorbed them.
- **No charge.** T_avg and T_ch keep their modelled values. The last reset, the interval sums and the previous
  charged temperature stay, so the next closure still knows its start.
- **Event.** A new event kind `short_run`, with the run start, end, energy and start-up energy used. The calibrator
  treats it as a run end for the quiet-window settle time (1 h). The model counts the short runs since the last
  charge (`short_runs` in the next charge's change).

**Why 15 minutes.** It is `MIN_RUN_MINUTES`, under which calibration already excludes a run because it does not mix
the tank. The constant moves to `const.py`, so the model and the calibrator share it. Evidence: the 31 runs of
2026-10-01 to 2026-11-05 lasted at least 43.5 minutes, so no run of the backtests changes.

**Alternative:** a partial charge (T_ch rises, T_avg by the energy). Rejected: a short run does not mix the tank, so
there is no layer at a known temperature to set T_ch to.

### D2: An interval with a short run is not a closure

The closure equation has one start-up energy per interval, and a short run inside it used S as well. The next
charge's closure is therefore excluded with the new reason `short_run_in_interval`, when its `short_runs` is above
0. The check comes after the existing `no_charge_temperature`, `after_*` and sensor-start checks and before the
unavailable check. The old `short_run` check on a closure's own run goes, because a short run makes no closure now;
the reason stays readable in stored closures.

**Alternative:** a second S term per short run in the equation. Rejected: none occurred in 31 runs, and the fit
would get a regressor that is 0 almost always.

### D3: Heat outside a run raises T_avg and enters the closure as a known heat

A counter increase while no run is active and outside the counter lag, with an energy counter configured:
`rise = dE * 1000 / (1.163 * V)` K. T_avg (and the balance's copy) rise by it, and T_ch becomes at least T_avg. No
start-up energy is used, because nothing warms up: the circuit already runs, for cooling. No charge and no reset. The
interval sums gain `heat`, the sum of these rises in K. The event is a `heat` event marked `outside_run: true`.

With a heat power sensor and no energy counter, the power is integrated outside a run as well, but only for readings
above the power threshold. The threshold already separates heating from standby readings, which would add up over a
day: 10 W of noise for 20 h is 0.2 kWh, 0.6 K on 285 L. When the power decides the runs, power above the threshold is
a run, so this applies only with a heating-active binary sensor.

The closure equation becomes:

```text
t_ch_prev - t_charge + E_run / C + heat - mixed = k * loss + share * other + S / C
```

The true start average and the charge error keep their formula: heat outside a run never falls inside a run, because
there every increase is `E_run`. A closure stores `heat`; a stored closure without it reads as 0.

**Why keep the closures.** The heat is measured, like `mixed`, so it is a known input and does not bias the fit. The
risk is a counter that overstates heat during cooling (see Risks).

**Detectors that cannot tell.** With counter-only detection, any increase starts a run. With power-only detection,
power above the threshold is a run. Then heat of cooling is a run, and a run of 15 minutes or more charges the model.
The README's "Supported heat sources" says that heat outside DHW runs needs a heating-active binary sensor.

**Evidence.** In the exports from 2026-10-01 to 2026-11-05 there was no counter increase outside a run beyond the
counter lag, so the backtests do not change. In June 2026 the counter rose 2.57 kWh (14:00-17:00) on 2026-06-23 and
8.10 kWh (06:00-13:00) on 2026-06-24, hourly means of 1.2-1.7 kW (`private/installation.md`).

### D4: The raise rule does not count heat outside a run twice

When heat outside a run warms the top of a partly drawn tank, the tank sensor can rise above `T_ch + tolerance`.
The rule "Sensor above the charged temperature raises it" then raises T_ch to the sensor and T_avg by the same step.
That step is the same heat the counter has already added. The model keeps `heat_uncredited` (K): the heat outside
runs since the last charge or reset that a raise has not yet used. A raise by `step = T_s - T_ch` then raises T_avg by

```text
rise = step - c,   c = min(step, heat_uncredited),   heat_uncredited -= c
```

Example: T_ch 50 C, T_avg 45 C, heat outside a run adds 3 K (T_avg 48 C, uncredited 3 K), the sensor reads 55 C with
a tolerance of 1.5 K: step 5 K, c 3 K, so T_ch 55 C and T_avg 50 C. Unmetered heat with nothing uncredited still
raises T_avg by the whole step, as today. A charge or a set_tank_state sets `heat_uncredited` to 0.

**Alternative:** no raise while heat outside a run came in recently. Rejected: it needs an arbitrary window, and it
would hide unmetered heat that comes at the same time.

### D5: The calibrator saves its open windows

`Calibrator.to_dict` adds two keys:
- `quiet_window`: the open window's start, first reading, value in force, its time, the two integrals and the
  ambient in use; None without one;
- `drop`: the first-drop state, None, `armed`, `hot` or `done`.

`restore` reads both with `.get`, so a store without them restores no window and no armed drop, as today. After a
restart the first `observe` integrates the held value over the downtime. Draws or heating during the downtime show up
as events when the sources report again, and they close the window. The estimate then still needs 5 hours of window.

### D6: A humidity sensor is silent after the silence time without a report

- **Option.** "Humidity silence time" (`humidity_silence`), in hours: default 2, 0-24, step 0.5, 0 off. It sits on
  the draws step after the humidity window, as the ambient fallback does on the shape step.
- **Reports.** The model keeps, per humidity sensor, the time of its last report and whether its last state was
  unavailable. `on_humidity` with a value is a report at its time. The runtime passes each humidity state's
  `last_reported` with every state it feeds and on every tick (5 minutes), so an unchanged report counts too, without
  a listener on `state_reported`. At start the fed state's `last_reported` is used, not the start time, so a reload
  does not restart a silence.
- **Silent** at `now`: the silence time is above 0, the sensor is not unavailable, and `now - last_report >= silence
  time`. A sensor with no report yet counts from the model's start.
- **Replays** see only recorded changes, so every gap between two recorded states is a silence when it is long
  enough.
- **The degraded state** holds when a humidity sensor is configured and every humidity sensor is unavailable or
  silent. The model exposes it, together with each sensor's last report.

**Why 2 hours.** Gaps between recorded humidity states in October: 6 of 0.5-1 h, 4 of 1-1.5 h, 2 of 1.5-2 h, 1 of 2-3
h and 1 of 3.7 h; in November up to the 6th, one of 0.5-1 h. At 2 h a silence counts from 2 h after the last report.
That window holds the shower of 2026-10-10 (17:54-18:05 UTC; silent from 17:44). The other window, 2026-10-05
19:12-20:10 UTC, holds no draw of 5 minutes (the longest is 4.4 min). At 1.5 h two more silences count, with no shower
in them. The sensor was never unavailable in either export: it goes silent instead. Data in
`private/installation.md`.

### D7: The detection backup is the next shower rule

While the degraded state holds and no shower is in progress, a draw session that has lasted the next shower time
(default 5 min) starts a shower. As in the humid bathroom after a shower, the session's litres within the reclassify
window are reclassified, and the shower ends by the shower end time. The backup starts as soon as the degraded state
holds; for an unavailable sensor that is from its first unavailable state. When a reading returns, the degraded state
ends. A shower in progress then runs to its end. "Draw counts as shower" (the classifier's `session_shower_time`)
counts down to the session start plus the next shower time while degraded.

**Why the next shower time, not the long-draw duration.** The long-draw duration is off by default (0), and with a
humidity sensor it is ignored. The next shower time already separates showers from washbasin draws (2.3 minutes in
the evidence of `improve-shower-end-detection`). Evidence: with it, the October backtest adds the shower of 2026-10-10
and no other shower.

**Where.** The classifier gets the degraded flag from the model on each call (`ClassifierOptions` stays static).
`_maybe_start` and `session_shower_time` treat degraded like humid for the session trigger. A humidity edge cannot
occur while degraded, because no sensor reads.

### D8: Repair issues in the runtime

The model has no notion of how long a source has been out across restarts. Home Assistant's state does: an unavailable
or unknown state's `last_changed` is when it went out. So the repair issues are runtime only (`estimator.py`):
- **Down since.**
  - Unavailable, unknown or non-numeric: the state's `last_changed`.
  - Missing entity: the estimator's start.
  - Humidity: the last report, when it is silent.
- **Check.** On every tick, and on every state change of a source so that a source that is back clears its issue at
  once. For each source entity: an issue when `now - down_since` reaches its threshold, else no issue.
- **Thresholds,** constants in `const.py`. They are not options: the user can only confirm or dismiss an issue,
  never act on a threshold.

  | Source | Threshold | Why |
  |---|---|---|
  | Water meter | 30 min | Draws are not classified while it is out. A catch-up above 100 L per reading is dropped as implausible. Never out in 35 days. |
  | Energy counter, power, heating detector | 30 min | Twice the detector hold (15 min). The one long outage (19 min, 2026-10-09, all heat pump entities at once) stays below. |
  | Tank sensor | 1 h | The sensor bounds pause and the balance runs alone. The 19-minute outage and the 2 s dropouts stay below. |
  | Humidity | 2 h | The silence time default. Shower detection falls back to D7. |
  | Flow and return, cold water, ambient | 3 h | The ambient fallback. The cold water falls back to the seasonal curve, and the charge temperature to the tank sensor. |

- **Issue.** `issue_id = f"{entry_id}_{entity_id}"`, `is_fixable=False`, `is_persistent=False`, severity WARNING. The
  estimate keeps running on its fallback, so nothing is broken outright. The translation key is per role
  (`source_unavailable_<role>`). The placeholders are the tank title, the entity ID and the threshold, and the text
  says what the estimate loses. An entity with several roles uses its first role's text and the shortest threshold.
- **Removal.** When the source is back, on entry unload (a reload raises it again from `last_changed` on the next
  check), and on entry removal.
- After a Home Assistant restart the states are new, so an outage counts again from the restart (proposal, Out of
  scope).

**Alternative:** issues from the model's unavailable seconds. Rejected: those reset at every charge and do not survive
a restart. They are also not what a repair issue is about.

### D9: Diagnostics

Added:
- for each humidity sensor, its last report and whether it is silent;
- the degraded flag;
- the ids of the entry's open repair issues;
- the event kind `short_run` and the `outside_run` mark on heat events;
- the closure reason `short_run_in_interval`.

### D10: Stores in both directions

`STATE_VERSION` stays the same, because the previous release rejects another version. The new model keys are:
- `short_runs`;
- `heat` in the interval sums, the run snapshot and the increase sums;
- `heat_uncredited`;
- the humidity reports.

The new calibrator keys are `quiet_window`, `drop` and `heat` in each closure. All are read with defaults (0, None,
empty). The previous release reads the keys it knows and ignores the rest: `IntervalSums.from_dict`,
`Closure.from_dict` and `Calibrator.restore` pick their fields by name. A test loads a new store in a copy of the
previous release's restore code, as `improve-shower-end-detection` did.

### D11: Evidence and backtest

The October and November backtests run at the commit before this change (baseline) and after the classifier group.
Expected:
- the shower of 2026-10-10 is listed, 71 L mixed instead of other;
- the charge error of the closure after it falls;
- no other shower changes;
- the other closures are equal (no short run, no heat outside a run).

The outputs go to `private/analysis/` and the summary to `private/installation.md`.

## Risks / Trade-offs

- [The counter overstates the heat during cooling: the firmware derives the DHW heat power during cooling from the
  full condensing power, so the counter can count heat that does not reach the tank] → The tank sensor's bounds still
  cap T_avg (the thermocline and cold caps), and the sensor only lowers the estimate. The check before the cooling
  season stays in the backlog (proposal, Out of scope).
- [A 5-minute draw that is not a shower, such as a garden hose, counts as a shower while the humidity sensor is out]
  → Only during an outage. October had about 2.6 hours of counted silence, with no such draw.
- [Replays see more silence than the runtime for a sensor that reports unchanged values often, because the recorder
  keeps changes only] → The backtest overstates the backup at worst. Whether the development installation's sensor
  reports unchanged values is not known. The live diagnostics show its last report next to its last change, and the
  live check records the difference.
- [A user gets a humidity repair issue a few times a month for a battery sensor that goes quiet] → That is the point
  of the issue (detection is degraded), and it clears itself. The silence time can be raised, or set to 0 for a
  sensor that reports only on change.
- [An unavailable heating detector during a cooling dump: the detector hold keeps the last state, and the next
  detector (power or counter) can then call the heat a run] → Unchanged behaviour of the detector fallback. After 30
  minutes the heating detector's repair issue shows it.
- [The credit of D4 is wrong when unmetered and metered heat come at once] → The raise then adds less than the
  unmetered heat. The sensor bounds correct it at the next draw; this is rare.

## Migration Plan

- No option migration. The humidity silence time takes its default for existing entries.
- Deploy and restart on the development installation once the code groups have passed review, with the user's
  authorization. Rollback: deploy the previous commit and restart. The stores load in both directions (D10), and
  the repair issues are not persistent, so they go with the restart.
