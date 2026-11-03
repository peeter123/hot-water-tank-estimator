# Design

## Context

See proposal.md (Why) for the motivation and the specs for the behaviour. This document records how the model was
derived from data and why each choice was made.

The repository is new: no code and no specs yet. The evidence comes from the development installation's recorder
history, 1-31 October 2026, exported to `private/history/2026-10-01_2026-10-31/` because the recorder keeps only
30 days. The analysis scripts and their outputs are in `private/analysis/`.

The installation has:
- a 300 L nominal tank holding about 285 L of water (from the manufacturer's empty and filled weights; the October
  analysis used 281 L, which changes the fits by less than 0.1 K);
- a ground source heat pump that charges it through an internal coil low in the tank (218-940 mm of 1660 mm), with
  no pump circulating the tank water. Heating from below mixes the water above the coil by convection; the water
  below the coil, about 15-20 L, is heated less (corrected on 2026-11-03: the first draft said an external circuit
  circulated the tank);
- one tank temperature sensor in a sleeve 1020 mm up a 1660 mm tank, at about 58 % of the water volume once the
  base and the dished bottom are taken off (the October analysis assumed 50 %; corrected on 2026-11-03);
- the heat pump's thermal DHW energy counter (kWh), heat power, DHW-demand binary sensor, and production flow
  ("out") and return ("in") temperatures;
- a whole-house water meter (m3, 1 L resolution, readings every 5 s during flow);
- one bathroom humidity sensor, in the only room with a shower and a bath.

An evening price block keeps the heat pump from charging between 16:00 and 23:00.

### Evidence

1. **Charging.**
   - 26 heating runs. Two kinds: midday runs (about 12:00) that end at 57-60 C, the setpoint, and recovery runs
     after the block or in the morning that stop at 49-50.4 C.
   - At each run's end, the highest mean of production flow and return over the last 2 minutes matched the tank
     sensor within 1.3 K, for example 57.9 against 58.0 C and 50.3 against 50.5 C.
   - Production return is the coil's outlet, at the bottom of the coil. Its 48.5 C at the end of a 50 C run, close
     to the flow, shows the water around the whole coil is at the charged temperature then, and convection has
     mixed the water above it. A run that stops below the setpoint still leaves the tank above the coil evenly
     mixed, so it is "charged". The water below the coil stays colder; the closure fit absorbs that steady deficit
     (about 15-20 L, or roughly 0.7 kWh per charge from 50 C) mostly in the start-up energy (see D4).
   - Flow and return start falling up to 40 s before the demand sensor turns off, so the charged temperature is
     the highest mean in the last 2 minutes, not the last reading.
2. **Energy closure between runs** (25 intervals).
   - For each pair of consecutive runs, the tank average at the start of the next run follows from that run's
     energy, and the charged temperature at the end of the previous run is known. The difference must equal loss
     plus draws.
   - A grid fit gives:
     - other-draws hot share 0.2;
     - loss coefficient 0.004 per hour (fixed from evidence 4);
     - start-up energy 1.8 kWh per run that does not reach the tank (circuit and heat exchanger warm-up);
     - volume 281 L, with the heat capacity factor fitted at 1.0.
   - Mean absolute error 1.9 K, worst 6.7 K. That interval was 47 hours with no shower, where small draws were
     overestimated.
   - Without the start-up energy the best error is 2.6 K. Recovery runs that follow a night with few draws then
     need a share above 1.
3. **Showers.**
   - 13 sessions with a humidity rise of 6 points or more. Peaks were 77-93 % from baselines of 51-64 %; draws
     without a shower never rose more than 2 points.
   - Eight emptied the tank past the sensor: sessions of 240-361 L, often several showers in a row. The sensor fell
     to 22-28 C within an hour.
   - Five did not move the sensor at all: 60-150 L. On 14 October a 141 L shower at 8.8 L/min left it at
     57.5 -> 57.1 C, a cold fraction of about 0.31.
   - The tank is sharply stratified, and the sensor only reacts once the cold layer reaches it.
   - Single showers ran at 6.2-10.0 L/min, with a median of about 7.3 L/min.
   - Humidity detection came 0.9-6.3 minutes after a shower session started (a replay of the month with the
     model's detection rule).
   - Correction, found in task group 3: the first analysis took a session's start from the meter's previous reading,
     which can be hours old. That made one morning shower look like a 270-minute night trickle at 0.8 L/min, and
     skewed session durations and flows. The figures here are recomputed from the meter's first increase. October
     has no slow trickle merging with a shower.
4. **Standing loss.**
   - 28 quiet windows of 5-10 hours with no draw and no heating. The sensor fell 0.08-0.24 K/h, giving k from
     0.0027 to 0.0083 per hour, with a median of about 0.0042.
   - The high values follow evenings with draws, when the cold layer was already near the sensor.
5. **Long shower 29 October.**
   - 240 L at 7.1 L/min starting at 54 C. The sensor fell from 54 to 50 C over the first 96 L, then to 40 C at
     146 L, 30 C at 205 L and 23 C at the end. It settled at 21.9 C.
   - The user confirmed that the last shower was still warm.
   - The recovery run's energy, less the start-up energy, puts the average at about 23 C. Against a charged
     temperature of about 55 C, that is a cold fraction of about 0.78 with the outlet still warm.
6. **Sensor height and thermocline width** (from evidence 3 and 5).
   - The sensor first leaves the charged temperature at a cold fraction of about 0.31-0.35 (14 October: a 141 L
     shower at about 0.31 did not move it; 29 October: 50 C, s = 0.89, at about 0.35). That gives
     `h - w / 2` of about 0.31-0.35 whatever the height.
   - The width then depends on h. The October analysis assumed h = 0.5 and found w of about 0.28-0.38. With the
     measured h of about 0.58, `w = 2 * (h - f)` gives about 0.46-0.54, and the full thermocline rule applied to
     the 50 C point (s = 0.89 at about 0.35) gives about 0.59.
   - A backtest of October at several heights (2026-11-03) has the lowest fitted charge error at h = 0.57-0.60
     (1.5 K, against 1.9 K at 0.5), with a fitted w of 0.44-0.49. So the sensor height entered by the user matters,
     and the shipped width default (0.35) is only a starting value that the setup fit replaces.

## Goals / Non-Goals

**Goals:**
- An estimate that is right at the moments that matter: during and after showers while charging is blocked.
- No drift over days: every heating run charges the model, and the sensor bounds it in between.
- Every installation fits its own parameters (D11), so the development installation's values are only starting
  defaults. A new user enters the tank volume and sensor height. Calibration does the rest, and the diagnostic
  sensors show how well it fits.
- The model is testable without Home Assistant, and replayable on recorded history.

**Non-Goals:**
- More layers than hot and cold, or the physics of mixing inside the thermocline. The width and the usable
  fraction absorb them.
- Predicting future use.

## Decisions

### D1: Two layers, kept as an average and a charged temperature

A charged tank is all at T_ch. Every draw replaces tank water with cold water from below, and a sharp thermocline
keeps the two apart (evidence 3). So the tank is a hot layer at T_ch above a cold layer at T_cold, with cold
fraction `f = (T_ch - T_avg) / (T_ch - T_cold)`.

Keeping T_avg (energy: `V * 1.163 * T_avg` Wh above 0 C) and T_ch gives three things:
- the energy balance works on T_avg alone;
- the sensor's height can be compared with f;
- the outputs can say how much tank water is still hot, not just how much energy is left.

Both cool with standing loss. T_ch changes only through loss, charging, heating (where `T_ch >= T_avg`), and a
sensor reading above it.

Alternatives:
- **One average temperature with a floor temperature** (the first draft of this change). It could not use the
  sensor's height, so the sensor only became useful once it fell, and the floor had no physical meaning per tank.
- **Litres of hot water as the state.** It needs a temperature per litre, double-counts partial charges, and drifts
  as the cold water warms through the year.

### D2: Draws are energy

- **Mixed draw:** the house meter counts the hot and cold litres a thermostatic mixer combines. The energy taken is
  `dV * 1.163 * (T_mix - T_cold)` Wh, so `dT_avg = -dV * (T_mix - T_cold) / V` in K, with dV and V in L.
  - The tank water that leaves is `dV * (T_mix - T_cold) / (T_ch - T_cold)`, about 56 % at 57 C, 38 C and 14 C.
  - When `T_ch <= T_mix`, the mixer takes only tank water and the drop is `dV * (T_ch - T_cold) / V`.
- **Other draw:** `dT_avg = -share * dV * (T_ch - T_cold) / V`. A share of the litres leaves the tank at T_ch,
  the rest is cold water that bypasses it.
  - The default share 0.2 comes from the fit in evidence 2: hot taps for hands and the kitchen, among toilet
    flushes and appliances.
- `1.163 Wh/(L*K)` is the volumetric heat capacity of water near 20-60 C. The real value is about 1.5 % lower at
  60 C, which is well inside the other uncertainties.

### D3: Heat input, start-up energy and heating detection

- Energy counter: `dT_avg = dE * 1000 / (1.163 * V)` in K, with dE in kWh. Power: `dE = P * dt` (left Riemann sum,
  P in W, dt in h). Gaps count as zero.
- **Start-up energy:** the first S kWh of each run are not applied (default 0).
  - Evidence 2 fits 1.8 kWh on the development installation: energy the counter reports but the circuit and heat
    exchanger keep.
  - It only changes the estimate during a run, because the charge at the end resets it. It matters when a run is
    cut short, such as by a price block that starts mid-run.
  - The default is 0 because the value depends on the plumbing. Calibration (D11) learns it per tank.
- **Heating detection**, in this order:
  1. a heating-active binary sensor gives exact run edges;
  2. otherwise, heat power above 100 W, which is above standby readings and below any heating power;
  3. otherwise, 10 minutes after the last counter increase. Counters update at least every few minutes while
     heating. The timeout only finds the end: the run ends at the last increase, because after it the heater may
     circulate space heating water or stand still, and its flow and return no longer show the tank.

  The first configured detector decides. Sources go unavailable for seconds around restarts and reloads, so an
  unavailable detector holds the heating state instead of handing over at once, which would end or start a run and
  charge the tank to a wrong temperature. After 15 minutes the next configured detector takes over.
- With only a binary sensor, T_avg and T_ch follow the sensor upward while heating, because a heating tank's sensor
  eventually rises.

### D4: Charging at run end

- At the end of a run, set `T_avg = T_ch = T_charge`. Evidence 1: the tank above the coil is evenly mixed then,
  and the model counts the whole tank at `T_charge` by convention.
- The colder water below a low coil (Evidence 1) is carried in two places: as energy, by the start-up energy that
  the closure fit learns (the steady deficit per charge), and as litres, by the usable fraction `u` (water that
  cannot be drawn hot). The docs say both.
- `T_charge` is the highest mean of flow and return over the last 2 minutes. Taking the highest mean skips the drop
  of up to 40 s before the demand sensor turns off.
- Without flow and return sensors, `T_charge` is the tank sensor. It agreed within 1.3 K on the development
  installation, but the heater's own temperatures do not depend on where the sensor sits.
- This charge makes errors in heat input (counter overhead, losses during the run) irrelevant at every run end.

### D5: Sensor height turns the tank sensor into a measurement

The sensor sits at height h, a fraction of the tank from the bottom (configurable 20-80 %, default 50 %). The
thermocline is w wide. While heating is not
active, with tolerance `delta` (default 1.5 K) and margin m (default 2 K):

| Sensor reading | Meaning | Rule |
|---|---|---|
| `T_s >= T_ch - delta` | Cold layer still below the sensor, so `f <= h - w/2` | Lower bound: `T_avg >= T_ch - (h - w/2) * (T_ch - T_cold)` |
| In between | Thermocline at the sensor. Linear reading: `s = (T_s - T_cold) / (T_ch - T_cold)`, `f_s = h + w/2 - s * w`, `T_s_avg = T_ch - f_s * (T_ch - T_cold)` | Upper cap: `T_avg <= T_s_avg + m` |
| `T_s <= T_cold + delta` | Cold layer past the sensor, so `f >= h + w/2` | Upper cap: `T_avg <= T_ch - (h + w/2) * (T_ch - T_cold)` |
| `T_s > T_ch + delta` | Heat the model did not see | `T_ch = T_s`, and T_avg rises by the same step |

`h - w/2` and `h + w/2` are limited to 0-1. The in-between reading then spans the limited range,
`f_s = f_hi - s * (f_hi - f_lo)`, so it meets the two other rules at its ends.

- **The tolerance is critical.** A reading just below `T_ch - delta` caps T_avg near the top of the thermocline
  (about 12.5 K below T_ch with the defaults), while one just above it only sets the lower bound. A sensor that reads
  more than delta below the flow and return charge, or that cools faster than the tank, drops the estimate by about a
  quarter of the tank at once. The docs tell users to raise delta when the sensor sits below the charged temperature
  right after a run.

- **The lower bound** corrects overcounted small draws and keeps the model from emptying while the sensor still reads
  hot. Evidence 3: a 141 L shower at a cold fraction of about 0.31 left the sensor unchanged, which is within
  `h - w/2 = 0.325`.
- **The in-between reading is only an upper cap.** Checked against the 29 October drain (evidence 5, T_ch about 54 C,
  w = 0.35):

  | Drawn | Sensor | Linear reading | Energy model (after the 27 h of draws before it) |
  |---|---|---|---|
  | 96 L | 50 C | 39.6 C | 39.8 C |
  | 146 L | 40 C | 36.1 C | 35.5 C |
  | 205 L | 30 C | 32.5 C | 30.4 C |
  | 240 L | 23 C | 30.1 C | 27.4 C |

  The recovery run's energy puts the end at about 23 C. The linear reading fits the start of the drain and then
  reads too warm, because the thermocline widens during a long draw. Raising the model towards it would show water
  that is not there. Used as a cap, it only pulls the model down when draws went uncounted, such as a shower that
  was not detected.
- **The margin** lets the energy balance smooth sensor noise and steps of 0.1 K. 2 K is about the sensor's change
  for 20 L of shower in the thermocline.
- **The default `w = 0.35`** comes from evidence 6. The tolerance of 1.5 K covers the slow loss of the top layer
  between charges.
- **Range of h:** outside 20-80 % the sensor would see only one layer for most of the cycle.
- Alternatives:
  - A two-sided bound around the linear reading. It is wrong late in a long drain (table above).
  - A fixed "sensor plus margin" cap (the first draft). It did not know where the sensor was, and it could not
    raise an overdrawn model.
  - A Kalman filter. It needs noise models for parameters that the bounds above handle well enough.

### D6: Draw classification

- Litres come from the whole-house meter. A litre is a **mixed draw** while a shower or bath is detected, and an
  **other draw** otherwise.
- Detection uses a rise of at least 6 points over the 60-minute minimum. Evidence 3: shower rises are 13-40 points,
  other draws stay within 2. Hysteresis is half the rise, so detection lasts until the room has dried most of the
  way. A tap used in that time counts as mixed, which errs on the side of showing less.
- **Reclassify window:** humidity rose 0.9-6.3 minutes after a shower started (evidence 3). At detection, the
  session's litres from the last 10 minutes become mixed draws. With a 3-minute window, six October showers kept
  8-21 L as other draws, up to about 1.2 K of T_avg each; 10 minutes covers every October case.
  - The window still bounds the reclassification, so a long session in which other draws ran into a shower does
    not take mix energy for all of it. October has no such session, so this is a safeguard, not evidence.
- Sessions are increases no more than 60 s apart. At 1 L resolution and the lowest realistic shower flow (about
  2.5 L/min), increases are at most 24 s apart.
- The long-draw rule is off by default, for homes without a humidity sensor. It would also fire on garden watering.
- Jumps over 100 L in one reading are ignored. No household draws that much in 5-15 s, so such a jump is a meter
  catching up after being offline.

### D7: Outputs

- **Tank water remaining:** `V * (u - f)` litres at T_ch, at least 0. u is the usable fraction, the cold fraction
  at which the outlet runs cold. It covers the thermocline and the outlet position.
  - The default 0.85 is just above evidence 5, where the shower was still warm at about 0.78, and below 1, the limit
    for an ideal tank.
  - A tank with a worse thermocline runs cold earlier, so users lower u after a shower that ran cold.
- **Shower water remaining:** tank water times `(T_ch - T_cold) / (T_mix - T_cold)`. This is the energy identity
  from D2 read backwards.
- **Percent charged:** `(u - f) / u * 100`, 100 % right after any charge. Charged is by convention whatever the
  heater reached, so percent compares with the last charge, not with the setpoint. The litres show the absolute
  amount.
- **Shower minutes:** shower litres divided by 7.5 L/min, a round value near the median shower flow in evidence 3
  (about 7.3 L/min; 6.2-10.0 L/min for single showers).
- **Mix temperature:** 38 C, the user's thermostatic setting and a common default.

### D8: Seasonal cold water curve

- `T_cold = mean - amplitude * cos(2 * pi * (doy - coldest_day) / 365)`.
- Defaults: 12.5 C mean, 5 K amplitude, coldest on day 46 (mid February). This follows published Dutch
  drinking-water temperatures (about 7-8 C in February, 17-18 C in August): ground temperature lags the air by
  about six weeks.
- Users elsewhere set their own values or give a sensor.
- A 2 K error in T_cold changes the shower litres by about 8 %, and every charge absorbs it.

### D9: Home Assistant structure

- `model.py` is a pure Python class with the formulas in D1-D8. It takes timestamps and numbers and returns events,
  and has no Home Assistant imports. Tests, the backtest and the replay fixtures run it directly.
- `__init__.py` keeps one `TankEstimator` per entry in `entry.runtime_data` and registers the action.
- The estimator subscribes with `async_track_state_change_event` to every configured source: the water meter, the
  energy counter or power sensor, the heating binary sensor, the flow and return sensors, the tank sensor, the
  humidity sensors and the cold water sensor.
  - Flow and return are kept as a 2-minute ring of readings for D4.
  - A 5-minute `async_track_time_interval` runs loss and the sensor bounds.
  - Events instead of polling keep each litre and each heat step exact.
- Entities subscribe to the estimator through a dispatcher signal. There is no coordinator because nothing is
  polled.
- The full model state from the integration-setup spec persists in the entry's `Store`, next to the calibration
  state. It is written at most once a minute while inputs arrive, and at unload. A later input must not push a
  pending write further out, or a long heating run would go unsaved for hours. The event log is not persisted.
  The first draft kept the model in the tank average sensor's restore data, but a user who disables that sensor
  would then lose the model at every restart.
- The setup fit and `recalibrate` run one at a time. A fit takes a snapshot of the calibration state when it
  starts. When it is applied, a "Shower ran cold" press or a manual reset made while it ran is kept. Live closures
  from those seconds are dropped.
- Config flow steps:
  1. tank: name, volume, tank sensor and height;
  2. water meter;
  3. heat input, with flow and return;
  4. shower detection;
  5. cold water.

  Selectors are filtered by domain and device class. The options flow holds every tuning value plus the optional
  sources. An options update reloads the entry, and the state survives through the `Store`.
- A reconfigure step (`async_step_reconfigure`, the Gold rule reconfiguration-flow) changes everything the config
  flow asked for: the volume, the tank sensor and its height, the water meter, the heat inputs and the optional
  sources. It refuses a tank sensor that another entry uses, keeps the tuning values, locks, history days, model
  state and calibration, and reloads the entry (decided with the user on 2026-11-03; the options flow alone does not
  meet the rule).
- The options flow keeps what can change without a duplicate check: the tuning values (the sensor height
  among them), the optional sources (flow and return, humidity, cold water), the locks and the history days. The
  volume, the tank sensor, the water meter and the heat inputs change only through reconfigure (group 8 review,
  2026-11-03), so the tank sensor check cannot be bypassed.
- Like Home Assistant's own helpers, an entry keeps all its settings in `options` (`data` stays empty), so that
  both flows edit one mapping and the live entry needs no migration. The `config-flow` quality rule's comment
  says so.
- Diagnostics: options, state, source availability and a ring of the last 100 events.
- Translations go in `strings.json` and `translations/en.json`, plain text.

### D10: Test data from recorded history

- `scripts/history.py` exports recorder history over the REST API. The token comes from a file and the entity IDs
  and time range from arguments. The output is a JSON file per role.
- `scripts/anonymise.py` turns an export window into a fixture with made-up entity IDs and only the roles the
  model uses.
- The replay fixtures, with the evidence they cover:

| Fixture | Window | Evidence |
|---|---|---|
| `long_shower` | 28 October 14:30 to 30 October 02:00 | A charge, then 240 L to 22 C, still warm, recovery run to 50 C |
| `shower_unseen` | 14 October 11:30 to 15 October 15:30 | Midday charge, 141 L shower the sensor does not see, next run |
| `back_to_back` | 22 October 11:30 to 23 October 01:00 | 88 + 200 L sessions, the block, recovery run |
| `late_detection` | 13 October 18:00 to 23:30 | Detection 6.3 minutes into a shower session, then a 163 L shower and the recovery run |
| `quiet_days` | 23 October 11:30 to 25 October 13:30 | 47 h of small draws only, the worst closure interval, with both its charges |
| `week` | 23 October 11:30 to 30 October 13:30 | 8 runs and 7 closures, showers, quiet nights; tests the setup fit |
| `month` | 1-31 October | Every run, shower and quiet night; used by the backtest, not by unit tests |

A replay starts each fixture charged at the tank sensor's reading, which ignores the draws since the last real
charge. So a fixture's first charge measures that start, not the model, and is not a closure. Later charges close
an interval that starts at a charge. Each window starts before or inside a run, so that its first charge comes
early and the charges after it are closures.

The first six are trimmed to the roles in use and kept in `tests/fixtures/`. `month` stays in `private/` because
of its size and is only used by the backtest.

- `scripts/backtest.py` replays a history export through `model.py` and `calibration.py`, the same code as the
  setup fit, and prints:
  - the charge error at every closure;
  - the outputs through every shower;
  - the fitted parameters;
  - the error with the fitted parameters against the defaults.

  It is the developer's view of what an entry's setup fit does.

### D11: Self-calibration

The values fitted in evidence 2-6 belong to one house. How much of the tap water is hot, the start-up energy of the
plumbing, the insulation and the thermocline all differ per installation. So each entry fits its own, the same way
the evidence was produced, and the shipped defaults are only where it starts.

- **The closure equation.** At every run end the run's energy tells the true average at the start of the run
  (calibration spec). Between charges the energy balance without the sensor bounds gives:

  ```text
  T_ch_prev - T_true_start = loss_sum * k + other_sum * share + mixed_sum
  T_true_start = T_charge - (E_run - S) / C + mixed_run + share * other_run + k * loss_run
  ```

  where:
  - `loss_sum` is the sum of `(T - T_ambient) * dt` from the previous charge to the run start;
  - `other_sum` is the sum of `dV * (T_ch - T_cold) / V` over other draws in that time;
  - `mixed_sum` is the mixed-draw drop in that time;
  - `loss_run`, `other_run` and `mixed_run` are the same three sums inside the run, because the tank is drawn
    and loses heat while the heater runs;
  - C = 1.163 * V / 1000 kWh/K.

  This is linear in k, share and S. A weighted least-squares fit over the stored intervals (forgetting factor 0.95,
  at least 5 intervals, each update limited to a quarter of the bound range) gives all three. With 25 intervals on
  the development installation, this fit gave share 0.2, S 1.8 kWh and an error of 1.9 K. The step limit and the
  minimum count keep one odd interval (a guest's bath, a leaking tap) from throwing the values off.
- **Loss from quiet windows.** Evidence 4 shows that quiet nights give k directly from the sensor while it still
  reads the hot layer. This also covers installations without a heat measurement, where there are no closures.
  - A window opens 1 hour after a run end at the earliest. Right after a run the sensor still settles, and windows
    opened at the end gave the three lowest October estimates (0.0016-0.0020 per hour against 0.0027-0.0037 an hour
    later).
  - With at least 3 quiet estimates, the closure fit holds k at their mean and fits only the share and S. Closures
    alone cannot separate k from the share: the loss and other-draw sums move together (correlation 0.93-0.96 in
    October), so a week of closures gave share 0.00 and k 0.0094 with a standard error wider than the bounds. With
    k held at the quiet-window value, the week gives share 0.11 and S 2.2 kWh, and the month 0.18 and 1.75 kWh,
    as evidence 2 did with k fixed from evidence 4. Without quiet windows the closures fit k too.
- **Width from the first sensor drop.** The cold fraction of the energy balance at the moment the sensor first
  leaves the charged temperature is `h - w/2`. Evidence 3 and 6 place that at about 0.31-0.35.
- **Usable fraction from the user.** Only a person can tell that a shower ran cold, so a button does it and also
  empties the model. A follow-up can detect it from shower flow or bathroom temperature (proposal).
- **Setup fit.** A new entry replays up to 30 days of the recorder's history of its sources. The recorder keeps
  about 10 days by default, and 30 on the development installation. It uses the same model and fitter code as
  live learning and the backtest, so an entry is calibrated on its first day instead of after a few weeks.
  - The replay reads history through the recorder's executor (`get_instance(hass).async_add_executor_job` with
    `history.state_changes_during_period` per entity). It then runs the replay in the executor too, because a month
    is about 80 000 states and a few seconds of CPU.
- **Precedence:** option value, then the setup fit, then live learning, unless locked. Locks are for users who know
  better, and for tests. Removing a lock discards the value learned before it, so the option value applies until
  the next fit. A recalibrate keeps the usable fraction learned from the button, which no replay can learn.
- **Every update of a learned parameter**, the width and the quiet-window k included, moves it by at most a quarter
  of its bound range, so one odd night or drain cannot throw it off. The "Shower ran cold" button is the exception:
  it records what the user observed.
- **Excluded closures:**
  - runs shorter than 15 minutes, because a short run does not mix the tank;
  - intervals in which a source was unavailable for more than 10 % of the time;
  - intervals in which the "Shower ran cold" button reset the model;
  - intervals ending in a run with no charged temperature (neither flow and return nor the tank sensor available).
    The model keeps its values. The interval after it is excluded too, because it has no known charged start.
- **Counter lag at the run end:** with a binary sensor or heat power deciding the run, the energy counter can report
  the run's last step after the run ended. Counter increases within 10 minutes after the end count towards that
  run's energy for its closure. The model itself has already been charged, so it does not apply them.
- **Visibility:** the diagnostic sensors show each parameter with its source, the samples and the charge errors. A
  rising mean charge error points at a wrong sensor height or a changed household. It is the first thing the README
  tells users to check.
- **Code:** `calibration.py` is pure Python next to `model.py`: the interval sums, the fitter and the width
  estimator. Persistence uses a `Store` per entry, not entity restore data, so the model and the learned values
  survive an entity being renamed, disabled or re-added.

Alternatives:
- **Shipping the development installation's values as defaults with only manual tuning** (the first draft). It
  only works for houses like the author's.
- **A recursive least-squares filter instead of refitting the stored intervals.** It is cheaper, but harder to
  bound, inspect and replay. With at most a few hundred intervals a refit is instant.

## Risks / Trade-offs

- **The sensor height is guessed wrong.** The bounds then move the model to wrong cold fractions. The README
  explains how to read the height from the data sheet. The backtest's charge errors show a wrong height as a
  consistent bias, and the margin limits the damage of any single reading.
- **Several bathrooms, or showers in a room without a humidity sensor.** Several humidity sensors are allowed, and
  the long-draw rule covers rooms without one. A shower that is not detected counts at the other share, and the
  first sensor bound corrects it once the cold layer reaches the sensor.
- **Garden watering in summer.** It counts at the other share (0.2 of its litres), the bounds correct it, and the
  next charge resets it.
- **Humidity rises without a shower** (cooking, humid weather). With no meter increase there is no effect. If water
  runs meanwhile, the estimate errs towards showing less.
- **The water meter misses low flows.** Small trickles are lost, which errs towards showing more water. The bounds
  catch large errors.
- **A tank heated high up** (a coil or an electric element in the upper part) only heats and mixes the water above
  the heat source, so the charge rule is wrong for it. A coil low in the tank, as on the development installation,
  mixes nearly all of it by convection, and the charge rule holds. Tanks heated high up, and a second heat source
  such as an electric element, are out of scope here (proposal); the README says so.
- **Learning drifts on unusual weeks** (guests, holidays). The step limit, the forgetting factor and the minimum
  count slow it down. The error sensors make drift visible, and locks and `recalibrate` undo it.
- **A run cut short mid-charge.** The charge rule still applies, using the flow and return at that moment. The
  tank is then not uniform, so the error shows at the next sensor bound. The backtest in task group 4 checks the
  price-block cut-offs.

## Migration Plan

There is no existing integration to migrate from. Rollout on the development installation, each step with the
user's authorization:
1. Deploy the integration folder over SSH (the author's workspace deploy script gets a mapping) and restart.
2. Add the config entry with that installation's entities, volume and sensor height (listed in the git-ignored
   `private/installation.md`) and the shipped defaults. The setup fit learns the rest (user decision in task 4.6).
3. Check the diagnostics over the next shower and heating runs (task 6.3), and keep comparing the charge errors and
   sensor bounds for a week.
4. Add a dashboard block.

Rollback: remove the config entry and the folder. Nothing else depends on it.

## Open Questions

- Whether to exclude dishwasher and washing machine fills, where the appliance integration reports them, with
  optional "cold appliance" water sensors. This can be added later without changing the model.
- The icon and logo ship in the integration's own `brand/` folder (Home Assistant 2026.3 and later), so the brands
  repository is not needed (decided 2026-11-03).
