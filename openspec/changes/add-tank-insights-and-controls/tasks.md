# Tasks

Read these before each group:
- `AGENTS.md`, `openspec/config.yaml` and `docs/development.md`;
- this change's proposal and design;
- its specs: `specs/tank-model/spec.md`, `specs/draw-classification/spec.md`, `specs/calibration/spec.md` and
  `specs/integration-setup/spec.md`;
- the requirements they modify, in `openspec/specs/` once `add-hot-water-estimator` is archived.

Each group runs in a fresh session and is committed on its own by the apply workflow. So each group must leave
`python scripts/lint.py` and the tests passing.

Applies to every group:
- Nothing installation-specific enters a tracked file. Entity IDs, history and calibration results of the
  development installation stay in `private/`. Fixtures use made-up entity IDs such as `sensor.tank_ambient`.
- Never read or print `%USERPROFILE%\.ha_token`. Scripts read it themselves.
- Live Home Assistant steps (deploy, restart, config entry, dashboard) run only in the tasks that name them. They run
  after the user authorizes them in the session, through the home-assistant MCP server or the config workspace's
  `scripts/deploy.ps1`.
- Documentation follows the "Documentation" section of `AGENTS.md`, in the same group as the change it describes.
  There are no line-number citations, and superseded text is removed.
- Numbers in tests come from the spec scenarios. A test named after a scenario checks that scenario's numbers.
- Stores saved before this change must still load (design D7). Each group that adds a stored key adds a test that
  loads a store without it.

## 1. Ambient temperature and heat loss

- [x] 1.1 Export the ambient sensor's history before the recorder purges it: the air sensor next to the tank, in
  `private/installation.md`, for 2026-10-04 to 2026-10-31. Write it as the `ambient` role into
  `private/history/2026-10-01_2026-10-31/` with `scripts/history.py`, and add the role to the map file. Verify: the
  file exists, and its first and last timestamps cover the window.
  - Done 2026-11-03 at the user's request, before the recorder purged more: `ambient.json` has 1706 rows from
    2026-10-04 03:27 to 2026-10-31 13:59 UTC, none unavailable (1-3 October were already purged). The map file
    entry is `"ambient": "ambient"`; 1.6 renames the role if the backtest uses another name.
- [x] 1.2 Implement design D1 in `model.py`:
  - an `ambient` source flag and an `on_ambient_sensor` input;
  - `ambient_temperature(now)`, with the 3-hour fallback as a new tuning value `ambient_fallback` (hours, default
    3, range 0-24);
  - the loss step using it;
  - `ambient_last` in the saved state.

  Verify: tests for the tank-model scenarios "One hour of standing loss", "Cooler room from an ambient sensor",
  "Sensor available", "Short outage" and "Long outage", and a test that a store without `ambient_last` loads.
  - Done 2026-11-03: `Sources.ambient_sensor`, `TankModel.on_ambient_sensor`, `ambient_temperature(now)` and the saved
    keys `ambient_sensor` and `ambient_last` (the reading and the time it was last known good, which is when the
    sensor went unavailable, so the fallback counts from the outage). The setup-fit role and the constant are
    `ambient_temperature` / `AMBIENT_TEMPERATURE`, the entry option `ambient_sensor`. `ambient_fallback` is a
    `ModelOptions` field (default 3 h, 0-24 in the options form).
- [x] 1.3 Implement the quiet-window change in `calibration.py`: k uses the window's time-weighted mean ambient in
  use. Verify: tests for the calibration scenarios "Quiet night" and "Quiet night with an ambient sensor".
  - Done 2026-11-03: the window integrates the ambient in use at each observation, like the sensor reading; a test
    with an ambient that changes mid-window checks the time weighting.
- [x] 1.4 Add the heat loss output (design D2) and the "Heat loss" sensor (W, device class power, state class
  measurement, icon, translations). Verify: a test for the integration-setup scenario "Standing loss of a charged
  tank", and the entity test for its unit and class.
  - Done 2026-11-03: the value function in `sensor.py` uses `calibration.heat_capacity`, the model's
    `ambient_temperature` and the loss coefficient in use; there is no separate model property.
- [x] 1.5 Add the ambient sensor as an optional source:
  - in the config flow's cold water step, renamed to "Temperatures" if that reads better;
  - in the options flow's optional sources;
  - in reconfigure;
  - with a selector filtered to temperature sensors;
  - with the `ambient_fallback` tuning value in the options.

  A save that adds, removes or replaces the ambient sensor starts `recalibrate`. Verify:
  - a test for the integration-setup scenario "Add an ambient sensor": T_avg is kept and a recalibration runs;
  - a test that a save without an ambient change starts no recalibration;
  - the config, options and reconfigure tests for the new field.
  - Done 2026-11-03: the config flow's cold step is now "Temperatures" (step id `temperatures`) with the cold water and
    ambient sensors; the options flow has the sensor in "Sources" and `ambient_fallback` in the first step. The
    recalibration is not started by the flow: the store keeps the ambient entity the calibration was fitted with
    (`ambient_fit`), and `TankEstimator.async_start` starts the existing setup fit as a background task when it differs
    from the configured one. That covers the options flow and reconfigure with one rule, runs after the reload, and
    survives a restart before the fit finishes. A store without the key counts as "no ambient sensor".
- [x] 1.6 Replay the ambient role in `setup_fit.py`, and let `scripts/backtest.py` read it from the map file.
  Verify:
  - a test that a replay with an ambient series uses it in the loss and the quiet windows;
  - run the backtest on the October export with and without the `ambient` role, and record k, the quiet-window
    estimates and the mean charge error of both runs, with the date, in `private/installation.md`.
  - Done 2026-11-03: the role is `ambient_temperature`, so the map file entry was renamed from `ambient`. At 285 L
    and height 0.58: k 0.0040 without and 0.0039 with the sensor; mean charge error with the fitted options 1.51 and
    1.52 K. No accuracy gain on this installation (the room averages 19.6 C). Details in `private/installation.md`.
- [x] 1.7 Document D1 and D2:
  - in `docs/model.md`: the formula, the fallback and the reason for each default, and the evidence from 1.6
    without installation details;
  - in the README: the ambient sensor field and where to place the sensor, `ambient_fallback`, the heat loss
    entity, and the backtest's `ambient` role.

  Verify: `python scripts/lint.py`.
  - Done 2026-11-03: `python scripts/lint.py` and `--hassfest` are clean.

## 2. "Hot water ran out" and its checks

- [x] 2.1 Report draw session ends from `classification.py`, and keep the `DrawEnd` record in the model (design D3,
  the draw-classification requirement "The end of the last draw is kept"). Save it in the store. Verify:
  - a test for the scenario "Draw ends";
  - a test that a running session yields a record at the current state;
  - a test that a store without `draw_end` loads.
  - Done 2026-11-03: `DrawClassifier.take_session_end()` reports the end of a session once (the time of its last
    increase). The model keeps `last_draw` (the `DrawEnd` after every draw increase, so the record has the state at the
    end and not the state when the session gap was noticed) and promotes it to `draw_end` on that report; both are saved
    (`draw_end`, `last_draw`) and default to None on load. `TankModel.last_draw_end(now)` returns a record built now
    while a session runs. New `EventKind.HOT_WATER_RAN_OUT`; `log_event` takes an optional `before`.
- [x] 2.2 Replace `Calibrator.cold_shower` with `hot_water_ran_out` (design D4): the 20-minute window, the
  `sensor_hot` check, learning from f at the draw end, the drop D applied now, and the lock. Verify: tests for the
  calibration scenarios "Shower runs cold early", "A tap runs cold", "Heat added since the draw", "Locked usable
  fraction", "Charge since the draw", "No recent draw", "Sensor still hot" and "Draw still running".
  - Done 2026-11-03: `Calibrator.hot_water_ran_out(model, now)` returns a `PressResult` (accepted, reason, values,
    drop) with reasons `no_recent_draw` and `sensor_hot`; the window is `PRESS_WINDOW`. The undo record (step 5) is
    left to group 3: the previous u and its source are still readable at the marked place before they change. The
    "Heat added since the draw" scenario holds with u learned (D is 0, T_avg stays, and the 1.5 K of heat leave 9.8 L);
    a second test with a locked u checks that the drop D is applied to the current T_avg and gives the same litres.
    D is skipped when T_avg was reset after the draw end (a charge, `set_tank_state` or an earlier press): the model
    saves `last_reset` (time of the last T_avg replacement, default None on load) and `reset_since(time)` tells the
    calibrator. Tests: "Charge since the draw", a second press, and a `set_tank_state` after the draw.
- [x] 2.3 Rename the button in the runtime:
  - key, translation key and name become `hot_water_ran_out` / "Hot water ran out", with a new icon translation;
  - a rejected press shows a persistent notification per tank, with a fixed notification ID and translated text
    that names the reason and the values;
  - the `hot_water_ran_out` event goes to the diagnostics.

  Verify: runtime tests for an accepted press, a rejected press (the notification text and that nothing changed),
  and the integration-setup scenario "Rejected press in the diagnostics".
  - Done 2026-11-03: key, translation key and icon `hot_water_ran_out`; `TankEstimator.async_hot_water_ran_out` ticks
    the model, runs the calibrator, logs the `hot_water_ran_out` event (`result`, `reason`, the values) and the
    calibration event with trigger `hot_water_ran_out`. A rejection shows a persistent notification with ID
    `hot_water_tank_estimator_<entry_id>_hot_water_ran_out` and the tank name as title; an accepted press dismisses it.
    The text is in the `exceptions` translation category (`press_ignored_no_recent_draw`, `press_ignored_sensor_hot`),
    loaded with `async_get_translations` in the language of Home Assistant, because hassfest accepts no other
    category for message text.
- [x] 2.4 Replace "Shower ran cold" with "Hot water ran out" everywhere in the README and `docs/model.md`: the press
  timing, the checks, a tap counting as well, and how "cold" differs a little between a tap and a shower. Remove
  the old text. Verify: a search finds no "Shower ran cold" outside `openspec/changes/add-hot-water-estimator/`, and
  `python scripts/lint.py`.
  - Done 2026-11-03: README ("Tuning", entity table, learning list) and `docs/model.md` ("Usable fraction": the four
    steps, the tap versus shower note); no "Shower ran cold" left outside `openspec/`. `python scripts/lint.py` and
    `--hassfest` are clean.

## 3. Undo

- [x] 3.1 Implement the undo record and `Calibrator.undo` (design D5): before the next charge, after it for 24
  hours, the last press only, and the record saved in the store. Verify:
  - tests for the calibration scenarios "Undo before the next charge", "Undo after a charge", "Nothing to undo" and
    "Restart keeps the undo";
  - a test that a recalibration keeps the record;
  - a test that a store without `undo` loads.
  - Done 2026-11-03: `UndoRecord` (press time, previous u with its source, whether the press changed u, D, the model's
    `last_reset` from before, and the time of the first reset after the press) is `Calibrator.undo_record`, written by
    an accepted press and saved under `undo` (None on load without it). `Calibrator.undo(model, now)` returns an
    `UndoResult` or None; `undo_available(model, now)` is a query without side effects, and `observe` notes the first
    reset and clears an expired record, so the runtime needs no extra call. The "learned from the button" marker is
    the presence of u in `values` (u is learned nowhere else), so undo pops it when none was learned before. The
    model gained `last_reset` and `restore_last_reset`. A recalibrate keeps the record: `setup_fit(previous=...)` and
    `_apply_fit`, which takes the live record and, after a press or undo during the fit, the live u. The scenario
    "Undo before the next charge" is a real press on a draw that ended at f 0.22, which clamps u at 0.5 and drops
    T_avg by 0.28 * 43 K; the test compares the undone tank with a control that never had the press. The record
    is timed by the model's own reset, and is dropped when the stored model is discarded.
- [x] 3.2 Add the "Undo hot water ran out" button: available only while undo is possible, re-evaluated on model
  events and on the 5-minute tick, and logging the undo event. Verify: runtime tests that the button is unavailable
  before a press and after an undo, available after an accepted press, and that pressing it restores the state.
  The diagnostics' calibration state includes the undo record (integration-setup "Diagnostics"; added after the
  group 3 review, 2026-11-03), with a diagnostics test.
  - Done 2026-11-03: `UndoHotWaterRanOutButton` (key and translation key `undo_hot_water_ran_out`, icon `mdi:undo`),
    available from `TankEstimator.undo_available()`, which the 5-minute tick and every model event re-evaluate through
    the existing signal; after a restart the saved record gives the right state. A press ticks the model, calls
    `Calibrator.undo`, logs `hot_water_ran_out` with `result: undone` (u, the T_avg rise, `after_reset`) and the
    calibration change, saves and signals; with nothing to undo it raises a `ServiceValidationError` with the
    translated message `nothing_to_undo`. An undo counts as a manual action for a running fit.
    The diagnostics' calibration block has the record under `undo` (None or its dict).
- [x] 3.3 Document undo in the README (the entity, and when it is available) and in `docs/model.md` (what it
  reverses and why it uses the drop D). Verify: `python scripts/lint.py`.
  - Done 2026-11-03: README (entity table, "Tuning") and `docs/model.md` ("Usable fraction": what undo reverses, D
    only, the u-only rule after a charge or `set_tank_state`, the 24 hours). `python scripts/lint.py` and `--hassfest`
    are clean.

## 4. Shower flow

- [x] 4.1 Report each detected shower's mixed litres and minutes of flow from `classification.py`, for humidity and
  long-draw detection. While a shower is detected, also report its rolling flow over the last 2 minutes of flow
  (design D6). Verify: tests for the draw-classification scenarios "Shower with a pause", "Shower detected by the
  long-draw rule", "Polled meter", "Steady shower", "Pause in the shower" and "Too little flow yet".
  - Done 2026-11-03: `DrawClassifier` keeps the detected shower from the rise of detection to its fall (the reclassified
    litres are its first increases) and `take_shower_end()` reports a `ShowerReport(litres, minutes)` once; minutes
    are the sum of the seconds between the increases of one session (first to last increase), and the litres leave
    out the first increase of each session, like the rolling flow (settled after the group 4 review). The
    `rolling_flow` property takes the increases of the last 2 minutes of flow, newest first, and leaves out the
    litre of a session's first increase (it was drawn before the session). The shower in progress is saved with a
    default on load.
- [x] 4.2 Add the shower flow history and the median (design D6) to the calibrator: the 3-minute minimum, the 3-20
  L/min bounds, the lock, and the history kept while locked. It is saved in the store and filled by the setup
  fit's replay. Verify:
  - tests for the calibration scenarios "Two people, two flows", "Short draw is no shower flow sample", "Shower
    with a pause" and "Showers in the history";
  - a test that a store without the history loads;
  - a test that an old `shower_flow` option value is the starting value while the history is empty.
  - Done 2026-11-03: `Calibrator.shower_flows` (10 entries, saved as `shower_flow_history`), `on_shower(litres,
    minutes)` and `shower_flow` as a parameter with the bounds 3-20 (so locks, the options selector, diagnostics
    and the calibration event cover it). The model emits a `shower_flow` event for a shower with 3 minutes of
    flow, the calibrator takes it in `observe`, and the replay does the same. `Calibrator.options` carries the
    flow in use (`ModelOptions.shower_flow`) and the history's lowest and highest flow
    (`ModelOptions.shower_flow_range`), so the model stays pure and the replay and backtest need no change. A
    background fit adds the showers learned while it ran to the replay's history, and keeps a flow set while it ran.
    An option value outside 3-20 is limited like the median, and a `shower_flow` event without litres (a set) is no
    sample.
- [x] 4.3 Compute shower minutes from the flow in use, or from the current shower's rolling flow while a shower is
  detected. Add the attributes `flow`, `flow_basis`, `minutes_low` and `minutes_high`, and update the sensor on
  every meter reading during a shower. Verify: tests for the tank-model scenarios "Minutes from litres", "Minutes
  for two people", "Minutes during a high-flow shower" and "First minute of a shower".
  - Done 2026-11-03: `TankModel.shower_time` gives the minutes, the flow, its basis and the low and high minutes;
    `outputs.shower_minutes` is its `minutes`. The sensor shows them as `flow`, `flow_basis`, `minutes_low` and
    `minutes_high`. The estimator sends the dispatcher signal after every source state, so a meter reading
    during a shower updates the sensor (a test counts the signals).
- [x] 4.4 Add the "Shower flow" number (`number.py`):
  - its value, with the attributes `source`, `low` and `high`;
  - setting it locks the flow;
  - the `shower_flow` lock in the options;
  - the `shower_flow` tuning value removed from the options form;
  - the `shower_flow` event in the diagnostics.

  Verify:
  - tests for the integration-setup scenarios "Set the shower flow", "Unlock in the options", "Units shown" and
    "Names shown";
  - the options-flow tests;
  - `python scripts/lint.py --hassfest`.
  - Done 2026-11-03: `number.py`, `Calibrator.set_shower_flow` and `TankEstimator.async_set_shower_flow`, which
    also writes `shower_flow` to the lock list of the entry options (no reload), so the options flow shows it and
    the store and the options agree at the next start. A lock turned on in the options holds the flow in use at
    that moment. The `shower_flow` tuning value is gone from the draws step; an old value in the options is still
    read as the starting value. `python scripts/lint.py --hassfest` is clean.
- [x] 4.5 Document the shower flow:
  - in `docs/model.md`: the median, its window and bounds, and the reasons;
  - in the README: the number and its lock, the minutes range attributes, the live minutes during a shower (the
    `flow` and `flow_basis` attributes), and an updated dashboard example with the new entities;
  - the high-flow shower limitation, in the README Limitations.

  Verify: `python scripts/lint.py`.
  - Done 2026-11-03: `docs/model.md` has a "Shower flow" section and the Learning, bounds and setup fit text;
    the README has the number, the lock, the attributes, the dashboard entities (heat loss, both buttons, shower
    flow), the Tuning entry and the high-flow limitation. The `shower_flow` option row is removed.

## 5. Rollout on the development installation (each step needs the user's authorization)

- [ ] 5.1 With authorization, deploy and restart. Verify through the home-assistant MCP server:
  - the entry loads with its state kept (T_avg within 0.1 K of before);
  - the new entities exist: heat loss, both buttons and the shower flow number;
  - the system log has no entries for the integration.

  Remove the old "Shower ran cold" button's registry entry, which the rename leaves behind as an unavailable entity
  (design, Risks). Verify that it is gone. Record the result in `private/installation.md`.
- [ ] 5.2 With authorization, add the ambient sensor from `private/installation.md` in the options. Verify:
  - the recalibration runs;
  - k stays within its bounds, and the quiet-window estimates are compared with those from before;
  - the heat loss sensor reads within 20 % of `k * C * (T_avg - T_ambient)`, worked out by hand.

  Record the numbers in `private/installation.md`.
- [ ] 5.3 With authorization, update the "Hot Water" dashboard block with a targeted dashboard transform:
  - point any card that uses the old button to `button.<tank>_hot_water_ran_out`;
  - add a heat loss tile;
  - add a shower flow tile, with the shower time tile showing the range.

  Update `private/installation.md`. Verify: a dashboard search finds the new entities and no old button.
- [ ] 5.4 Live check over the next days:
  - a press with no draw in the last 20 minutes is rejected with a notification, and the diagnostics show the
    rejected event;
  - after the next showers, the shower flow history grows by one per shower of 3 minutes or more, and the flow in
    use is plausible against the meter's flow during the shower;
  - during a shower, "Shower time remaining" switches to `flow_basis` `current_shower` after 1 minute of flow, and
    its `flow` follows the meter's active flow within about 1 L/min;
  - the heat loss follows the ambient sensor.

  Record the result in `private/installation.md`. Verify: the diagnostics download shows these events.
- [ ] 5.5 **User review.** Show the user the shower flow history, the minutes range, the rejection notification and
  the backtest comparison from 1.6. Ask whether the defaults hold:
  - the 20-minute window;
  - the 3-hour fallback;
  - the 3-minute minimum;
  - the 24-hour undo after a charge;
  - whether two showers in one humidity detection should be split into two shower flow samples at a long pause,
    and at what pause (design, Risks).

  Record the decision with its date in this task, and update the docs if a default changes.

## Workflow follow-up

- Before starting group 1, archive `add-hot-water-estimator`, so that the modified capabilities exist under
  `openspec/specs/`.
- One fresh Opus review of the whole change before archiving (`openspec/config.yaml`, Review loop).
- Sync the delta specs into `openspec/specs/` and archive the change (`/opsx:archive`).
