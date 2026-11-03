# Design

## Context

See proposal.md (Why) for the motivation; the specs give the required behaviour. This change builds on the code of
`add-hot-water-estimator`, which must be archived first, so that the capabilities exist under `openspec/specs/`.

The current state the approach depends on:
- `model.py` applies standing loss with a fixed `ambient_temperature` option. `calibration.py` uses the same option
  for quiet-window loss estimates.
- The cold water sensor is the pattern for an optional temperature source. It has:
  - a `Sources` flag;
  - an `on_cold_water_sensor` input to the model;
  - a role in the setup fit's `History`, replayed in `setup_fit.py`;
  - a role in `scripts/history.py` and the backtest map file.
- `Calibrator.cold_shower` sets the usable fraction to the model's cold fraction at the time of the press, then sets
  `T_avg = T_ch - u * (T_ch - T_cold)`. It keeps no record of the press, so nothing can be undone.
- `classification.py` groups meter readings into sessions (the session gap, default 60 s). It knows when a session
  ends, but nothing keeps the model state at that moment.
- `shower_flow` is a tuning option (default 7.5 L/min) and is used only in `shower_minutes`.
- The entry state is saved in one `Store`, with the model and the calibrator serialised to plain dicts.

## Goals / Non-Goals

**Goals:**
- **Model stays pure.** Every new rule is pure Python in `model.py`, `classification.py` or `calibration.py`, so the
  replay, the backtest and the unit tests run it without Home Assistant.
- **One pattern per input.** The ambient sensor follows the cold water sensor pattern end to end: config, model,
  history export, replay and backtest.
- **Old stores still load.** Stores saved before this change load without a migration step. New fields have
  defaults.

**Non-Goals:**
- A store version bump. The new fields are optional keys in the existing dicts.
- Showing the press checks in the UI before a press. The rejection notification is the feedback.

## Decisions

### D1: Ambient temperature in use

The tank model exposes `ambient_temperature(now)`, which returns one of:
- the sensor reading, while the sensor is available;
- the last reading, for up to `ambient_fallback` hours (default 3) after the sensor went unavailable;
- the `ambient_temperature` option otherwise.

Every user of the old option calls this method: the loss step, the heat loss output and the quiet-window estimate.

Evidence for the 3-hour default. Over 30 days the development installation's air sensor next to the tank:
- read 18.7-21.25 C;
- moved at most 1.3 K within one day;
- had a daily mean that fell from 20.5 to 19.0 C over the month.

A 3-hour-old reading is therefore within about 1 K. Against a tank-to-room difference of about 38 K, that is under
3 % of the loss rate. The fallback covers short radio or battery outages of wireless sensors. A longer outage falls
back to the configured value, because a reading many hours old may be from another season of the day.

The quiet-window estimate uses the window's mean ambient temperature: the time-weighted mean of the ambient in use
over the window. The mean is in both the numerator's window and its denominator, so it removes the room's daily
swing from k.

Changing the ambient source starts a recalibration. k fitted against 20 C and k fitted against a sensor are not the
same parameter, so keeping the old value would bias it.

The trigger is a stored marker, not the flow's save handler. The store keeps the ambient entity the calibration was
last fitted with (`ambient_fit`). When the entry starts and the configured sensor differs, the background setup fit
runs. This one rule covers both the options flow and reconfigure, runs after the reload, and repeats after a
restart that interrupted the fit. A store without the marker counts as fitted without an ambient sensor. This was
decided in the group 1 implementation on 2026-11-03.

The ambient sensor's availability does not exclude a closure, unlike the other sources' 10 % rule (group 1 review,
2026-11-03). The model always has an ambient value, from the sensor, its last reading or the option, and the ambient
enters only the loss term. Over an 8-hour interval at k 0.004 per hour, a 1 K ambient error moves the closure by
about 0.03 K, which is far below the charge errors.

A source that is no longer configured has no say in the model. On restore, the last reading of a removed ambient or
cold water sensor is dropped, so the option or the seasonal curve applies at once. The group 1 review found that
both sensors kept their last reading for good after removal; the cold water case predates this change and is fixed
here with it.

**Alternatives considered:**
- Always use the option as the fallback, with no hold. A 1-second sensor dropout would then jump the loss rate.
- Hold the last value without a time limit. Rejected for the reason above: after a long outage the value may be
  stale.

### D2: Heat loss output

`heat_loss_w = k * C * max(0, T_avg - T_ambient) * 1000`, with:
- k the loss coefficient in use, per hour;
- `C = 1.163 * V / 1000` kWh/K;
- T_avg and T_ambient in C.

kWh/K times K per hour is kW, and `* 1000` gives W.

It uses T_avg, not T_ch, because loss acts on the whole tank, and the loss step applies the same rate to T_avg.

It is a main sensor (device class power, state class measurement), not a diagnostic one, because it answers "what
does keeping the tank hot cost". On the development installation it reads about 50 W, against the manufacturer's 68
W at 45 K, which is 58 W at 38.5 K. The learned k sits below the rated value, as the earlier analysis found
(0.0039 against 0.0046).

### D3: The state at the last draw end

When a session ends, the classifier reports it, and the model stores a `DrawEnd` record:
- the end time;
- the cold fraction f;
- T_ch, T_avg and T_cold;
- the tank sensor reading, or None when it was unavailable;
- the usable fraction in use.

A running session counts as "ending now" for a press: the record is built on the spot from the current state. The
record is part of the saved model state, so a restart between the draw and the press keeps it.

The classifier notices a session end only one session gap after its last increase, so the model keeps the state
after every draw increase (`last_draw`, also saved) and turns it into the `DrawEnd` record when the classifier
reports the end. The record then holds the state at the last increase, not at the moment the gap ran out. This was
decided in the group 2 implementation on 2026-11-03.

This answers "what was the tank like when the water ran cold". The press happens up to 20 minutes later, because
the user leaves the shower first. The 20-minute window is the user's choice (2026-11-03): time to step out, dry off
and reach a phone.

### D4: "Hot water ran out"

The button gets the key `hot_water_ran_out`, which changes its entity ID. The user accepted the ID change on the
development installation on 2026-11-03. It calls `Calibrator.hot_water_ran_out(model, now)`, which replaces
`cold_shower`.

1. **Find the draw.** Take the running session, or the last `DrawEnd` no older than 20 minutes. Without one, reject
   with reason `no_recent_draw`.
2. **Check the sensor.** If that record's tank sensor reading is at least `T_ch_end - tolerance`, reject with reason
   `sensor_hot`, giving the reading. While the sensor reads hot, the cold layer is below the sensor, so it is below
   the outlet at the top. A cold outlet then means cold pipe water, not an empty tank. A record without a sensor
   reading skips this check.
3. **Learn.** If the usable fraction is not locked, set `u = clamp(f_end, 0.5, 0.98)`, with source learned.
4. **Empty the tank.** Compute the drop `D = max(0, u - f_end) * (T_ch_end - T_cold_end)` in K. That is the T_avg drop
   that makes `V * (u - f) = 0` at the draw end, since f rises by `dT / (T_ch - T_cold)` per K. Apply
   `T_avg -= D` now, through `set_state`.
   - Heat added since the draw end stays added. Loss since then is already in T_avg.
   - When u was just set to f_end, D is 0 and only the learned u empties the outputs. When u is locked, or clamped
     at 0.5, D is positive.
   - **T_avg reset since the draw end.** D is not applied when T_avg was reset after the draw end: by a charge, by the
     `set_tank_state` action, or by an earlier accepted press. Only u is learned. The reset already replaced the
     T_avg that D would correct, the same argument D5 makes for undo after a charge. Without this rule, a press after
     a charge would lower a freshly charged tank, and a second press on the same draw with u locked would apply D
     twice. Decided after the group 2 review on 2026-11-03.
5. **Record the undo:** the press time, the previous u and its source, and D.

A rejection changes neither the model nor the calibrator. It records a `hot_water_ran_out` event with
`result: rejected` and the reason. The runtime then shows a persistent notification, one per tank with a fixed
notification ID, so repeated presses replace it. The text names the reason and the values, for example "Ignored: the
tank sensor still read 55.8 C when the last draw ended, so the tank was not empty".
- The texts are in the `exceptions` translation category, because hassfest allows no custom category. The runtime
  loads them with `async_get_translations` and fills in the values.
- The notification title is the tank name.
- An accepted press dismisses the notification, so a stale rejection does not stay beside an accepted press.

These choices were made in the group 2 implementation on 2026-11-03.

**Alternatives considered:**
- Apply the press to the state at the moment of the press. A heating run or a long wait would then distort f.
  Rejected because of the 20-minute window.
- Use the "recent shower" as the check. Rejected: a tap running cold is the same evidence (the user, 2026-11-03).
- A repair issue instead of a notification. Rejected: a repair issue is for a broken setup the user must fix, while
  a rejected press is feedback on an input.

### D5: Undo

The undo record holds the press time, the previous u and its source, and D. `Calibrator.undo(model, now)` does the
following:
- **Before the next charge:** restore u and its source, and raise T_avg by D through `set_state`, limited by the
  physical bounds. Draws and heat since the press stay counted, because only D is reversed.
- **After the next charge, within 24 hours of it:** restore only u. The charge already set T_avg to the charged
  temperature, so there is no T_avg error left to reverse.
- **Afterwards:** clear the record. The record is also cleared after 24 hours past the next charge.

Details settled before the group 3 implementation (2026-11-03):
- **What counts as the next charge.** It is any reset of T_avg after the press, using the model's `last_reset` from
  D4: a heating-run charge or the `set_tank_state` action. The press's own `set_state` is at the press time, so it
  does not count. After a `set_tank_state`, raising T_avg by D would distort the value the user set, so the same
  "u only" rule applies.
- **When the 24 hours start.** The record keeps the time of the first reset after the press. The calibrator notes it
  the first time it sees `last_reset` later than the press, which happens on every model event and tick. The window
  runs from the reset's own time (`last_reset`), not from the moment the calibrator notices it. Without any reset
  after the press, for example with the heater off for a holiday, the full undo stays available, because the spec
  says "until the next charge".
- **What u restores.** Everything the press changed about u: the value, its source, and the marker that keeps a
  button-learned u through a recalibration. A press that did not change u, because u was locked, restores nothing
  for u.
- **The reset marker.** An undo before the next charge also restores `last_reset` to its value before the press, so
  a later press on the same draw works as if the undone press never happened. Without this, the undo's own
  `set_state` would make that later press skip D.
- **The event.** Undo logs a `hot_water_ran_out` event with `result: undone`, giving the u and the T_avg rise it
  restored.

The undo button is available only while a record exists and undo is still possible. The runtime re-evaluates
availability on every model event and on the 5-minute tick.

The 24 hours is a proposed default from the exploration (2026-11-03). A wrong u shows up the next time the tank runs
low, which in a household with daily showers is within a day.

### D6: Shower flow learning

When a detected shower ends (`draw-classification`), the classifier reports its mixed litres and minutes of flow.
Minutes of flow are the summed duration of the sessions within the shower, each from its first to its last increase.
The calibrator handles each shower:
- **Sample.** With at least 3 minutes of flow, it appends `litres / minutes` to a 10-entry history. That history is
  shared with the setup fit's replay.
- **Value in use.** Unless the shower flow is locked, the value in use is the median of the history, limited to 3-20
  L/min.

Why these values:
- **The median.** Two people at 7.5 and 12 L/min give a median that sits with the majority, not between them. A
  bath fill, a detected "shower" at tap flow, does not pull a median the way it would pull a mean.
- **The 3-minute minimum.** Shorter detected draws are mostly a washbasin during a humidity rise, not a shower
  setting.
- **The bounds 3-20 L/min.** They span water-saving heads at about 5-6 L/min up to large rain heads.
- **The history length of 10.** About a week of showers for two people, so a new shower head is followed within a
  week.

Evidence: the development installation's long shower of 2026-10-29 drew 239 L at 7-8 L/min.

The existing quarter-range step limit for learned parameters does not apply to the shower flow, because the median
is already robust to one odd sample. The calibration spec states this exception.

Shower minutes use the flow in use, except during a shower. `minutes_low` and `minutes_high` use the highest and
the lowest flow in the history. They stay available while the flow is locked, because the history keeps filling.

**During a shower**, the minutes use the current shower's rolling flow instead (the user's request, 2026-11-03):
- **What it is.** The classifier keeps the meter increases of the detected shower with their times, and reports the
  mixed litres over the last 2 minutes of flow divided by those minutes. Gaps longer than the session gap are left
  out, so a pause with the water off does not drag the flow down.
- **Why 2 minutes.** A meter that counts whole litres gives about 15 L in 2 minutes at 7.5 L/min. That resolves the
  flow to about 7 %, while a change at the tap still shows within a minute or two.
- **Why the 1-minute minimum.** Before 1 minute of flow there are too few litres for a flow, so the median stays in
  use.
- **Same sensor.** The value goes to the same "Shower time remaining" sensor, with `flow` and `flow_basis`
  attributes. A separate sensor would be unavailable most of the day, and the dashboard tile should show the most
  relevant number.
- **Display only.** The rolling flow is not learned. At the shower's end, the whole-shower flow goes into the
  history, as above.

With a whole-litre meter the rolling flow steps by about 0.5 L/min, so the minutes can move by 1 between meter
readings. That is the meter's resolution, not noise to filter.

**The "Shower flow" number** (new `number.py`):
- Its native value is the flow in use.
- Its attributes are `source`, `low` and `high`.
- Setting it calls `Calibrator.set_shower_flow(value)`, which stores the value with source `locked` and adds
  `shower_flow` to the locks.
- The options flow shows the `shower_flow` lock like the other locks. Removing the lock returns to the median.
- The `shower_flow` tuning option is removed from the options form. An existing value in the entry's options is read
  once as the starting value while the history is empty, so a user who tuned it keeps their value until the first
  shower is learned.

**Alternatives considered:**
- An exponential average like the other parameters. Rejected: it swings between the two people's flows.
- Named profiles per person. Out of scope (proposal).

### D7: Persistence and diagnostics

New keys are added to the existing dicts, each with a default on load, so stores saved before this change load
unchanged:
- model: `draw_end` and `last_draw` (D3), `last_reset` (the time T_avg was last replaced, D4), and
  `ambient_sensor` with `ambient_last` (the last good reading, and the time the sensor was last known good, from
  which the fallback counts);
- the entry store: `ambient_fit`, the ambient entity the calibration was last fitted with (D1);
- calibrator: `shower_flow_history` and `undo`.

Diagnostics already dump these dicts, so the new state appears there without new code. The new event kinds are
`hot_water_ran_out` (with `result` accepted, rejected or undone, plus the reason) and `shower_flow`.

### D8: Setup fit and backtest

- **Replay.** `History` gains an optional `ambient_temperature` role, which `setup_fit.py` feeds to the model like
  the cold water sensor. The replay also feeds shower ends to the calibrator, so a recalibration fills the shower
  flow history.
  The undo record and the usable fraction from the button are kept from before the recalibration, as today.
- **Export and backtest.** `scripts/history.py` needs no change, because roles are generic. The backtest's map file
  documents the `ambient_temperature` role, and the README's backtest example names it.

## Risks / Trade-offs

- [The tank sensor reads hot, but the outlet really ran cold, for example with a sensor high in a tank with a very
  wide thermocline] → The check uses `T_ch - tolerance`, the same threshold as the sensor bounds. The notification
  names the reading, and `set_tank_state` remains a manual way out.
- [A bath fill enters the shower flow history] → The median ignores one or two such samples among ten.
- [Two people with very different flows make the median flip when the balance of recent showers changes] → The low
  and high minutes show the spread. The number lock fixes a value for a user who wants a stable one.
- [An ambient sensor in the wrong place, such as one in sun or next to the heat pump, biases k] → k is fitted against
  that sensor, so the bias is absorbed in k. The heat loss in W stays close to right, because it uses the same pair.
  The README advises placing the sensor at the tank, in its air.
- [A press 20 minutes late, after another short draw, such as a toilet flush] → The last session then is the flush,
  not the shower, and its f is a little higher than at the shower's end. This errs towards a larger u by the litres
  of that draw (about 6 L, or 2 % of a 285 L tank). Accepted.
- [A sensor bound between the draw end and a press with u locked] → The bound has already moved T_avg towards the
  sensor, and D is applied on top. The bound acts only when the sensor disagrees with the model, and the error is
  small next to a charge reset. Accepted (group 2 review, 2026-11-03).
- [A second press while the same draw keeps running] → It learns a higher u from the later f, and undo restores only
  the value from before the last press. A user who presses twice means the later moment. Accepted (group 2 review,
  2026-11-03).
- [The renamed button breaks a dashboard or automation that used the old entity ID] → Development only; the rollout
  task updates the live dashboard.
- [The old button's registry entry stays as an unavailable entity after the upgrade] → Only pre-release
  installations have it, so there is no migration code. The rollout removes it on the development installation.

## Migration Plan

1. Archive `add-hot-water-estimator`, so that the capabilities exist as main specs.
2. Implement and review the task groups in order.
3. **Live rollout, with the user's authorization:**
   - deploy and restart, and check that the entry loads with its state kept;
   - add the ambient sensor in the options, which starts a recalibration, and check the fit;
   - update the dashboard to use the renamed button, and add the heat loss and shower flow entities.
4. **Rollback:** deploy the previous commit and restart. The extra store keys are ignored by the old code, so the
   state survives the rollback.

## Open Questions

- The exact notification wording for each reason. It can be settled in the strings during implementation without
  changing behaviour.
