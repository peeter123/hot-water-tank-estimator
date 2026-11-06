# Tasks

Read these before each group:
- `AGENTS.md`, `openspec/config.yaml` and `docs/development.md`;
- this change's proposal and design;
- its specs: `specs/tank-model/spec.md`, `specs/draw-classification/spec.md`, `specs/calibration/spec.md` and
  `specs/integration-setup/spec.md`, and the requirements they modify in `openspec/specs/`.

Each group runs in a fresh session and is committed on its own by the apply workflow. So each group must leave
`python scripts/lint.py` and the tests passing.

Applies to every group:
- Nothing installation-specific enters a tracked file. Entity IDs, history and results of the development
  installation stay in `private/`. Fixtures use made-up entity IDs.
- Never read or print `%USERPROFILE%\.ha_token`. Scripts read it themselves.
- Live Home Assistant steps (deploy, restart, config entry, dashboard) run only in the tasks that name them. They run
  after the user authorizes them in the session, through the home-assistant MCP server or the config workspace's
  `scripts/deploy.ps1`.
- Documentation follows the "Documentation" section of `AGENTS.md`, in the same group as the change it describes.
  There are no line-number citations, and superseded text is removed.
- Numbers in tests come from the spec scenarios. A test named after a scenario checks that scenario's numbers.
- `STATE_VERSION` stays the same. Every new store key is read with a default, and a store saved by this change loads
  in the previous release (design D10). The group that adds a key tests both directions.

## 1. Baseline and backlog

- [x] 1.1 Export the November history of the development installation from 2026-11-01 to the day of the export,
  with every role of `private/history/2026-11-01_2026-11-05/`, into `private/history/2026-11-01_<to>/` using
  `scripts/history.py`. This reads the recorder only. Run `private/analysis/harden_sources_evidence.py` and
  `private/analysis/silence_gaps.py` on it. Record in `private/installation.md` the runs, the counter increases
  outside runs, the humidity gaps of at least 2 h (settle whether the exploration's third silence exists) and the
  outages. Verify: the export has one file per role covering the window, and the summary is in
  `private/installation.md` with the date.
- [x] 1.2 Run `scripts/backtest.py` at this group's commit (before any code change of this change) on the October
  export and on the export of 1.1. Save both outputs in `private/analysis/` as the baseline. Record in
  `private/installation.md` the shower of 2026-10-10 17:54-18:05 UTC (counted as other draws), the charge error of
  the closure after it, and the mean and worst charge errors. Verify: both output files exist, and the summary is in
  `private/installation.md` with the date.
- [x] 1.3 Update `openspec/backlog.md`:
  - remove the item `harden-sources-and-heat-input` (it is this change);
  - add a carried-over live check: heat outside a run in the cooling season, and the check before that season that
    the heat pump's DHW counter during cooling matches the heat that reaches the tank (proposal, Out of scope).

  Verify: `python scripts/lint.py`.

## 2. Short runs

- [x] 2.1 Move `MIN_RUN_MINUTES` (15) to `const.py`. In `model.py`, end a run shorter than it without a charge
  (design D1):
  - keep T_avg, T_ch, the last reset, the interval sums and the previous charged temperature;
  - apply the counter lag after a short run to T_avg, after any start-up energy left;
  - emit a `short_run` event;
  - count the short runs since the last charge, and put the count in the next charge's change.

  Save the count with the model state (read with a default of 0). Verify:
  - tests for the tank-model scenarios "Run cut off by a cooling demand" and "Run of 15 minutes";
  - a test that a counter-timeout run uses its last increase as its end for the length;
  - a test that a short run's counter lag raises T_avg;
  - the store tests of D10 for the new key;
  - `python scripts/lint.py`.
- [x] 2.2 In `calibration.py`, exclude a closure whose charge change has short runs as `short_run_in_interval`
  (design D2). Remove the check on a closure's own run length, keeping the `short_run` reason readable in stored
  closures. Treat the `short_run` event as a run end for the quiet-window settle time. Verify:
  - tests for the calibration scenarios "Run cut off before a full run" and "Next interval counts again";
  - a test that a quiet window does not open within 1 hour after a short run;
  - a test that a stored closure with the reason `short_run` still loads;
  - `python scripts/lint.py`.
- [x] 2.3 Update `docs/model.md` ("Charging at the end of a run", "The charge closure") with the short-run rule, the
  exclusion and the evidence of design D1. Update the README where it says that every run charges the tank ("How the
  estimate updates", "The model in short"), and the diagnostics text for the new event and reason. Verify: `python
  scripts/lint.py` (including `tests/test_readme.py`).

## 3. Heat outside a run

- [ ] 3.1 In `model.py`, apply heat outside a run (design D3):
  - a counter increase with no run active and outside the counter lag raises T_avg and the balance, and T_ch becomes
    at least T_avg, with no start-up energy and no charge;
  - without an energy counter, heat power above the power threshold counts the same way, while no run is active;
  - add `heat` to the interval sums, and mark the heat event `outside_run`.

  Save the new sums key with a default of 0. Verify:
  - tests for the tank-model scenarios "Heat of cooling with the DHW demand off", "Heat outside a run reaches the
    charged temperature", "Counter lag after a run" and "Power below the threshold";
  - a test that a counter-only entry still starts a run on an increase;
  - the store tests of D10 for the new key;
  - `python scripts/lint.py`.
- [ ] 3.2 Credit the heat outside runs and the heat of short runs in the raise rule (design D4), with
  `heat_uncredited` reset at a charge and at `set_tank_state`, and saved with a default of 0. Verify: tests for the
  tank-model scenarios "Unmetered heat" and "Sensor sees heat outside a run", a test that a short run's heat is
  credited the same way, a test that a charge clears the credit, and `python scripts/lint.py`.
- [ ] 3.3 In `calibration.py`, store `heat` in each closure (0 for a stored closure without it) and add it to the
  closure fit as a known input (design D3). Verify:
  - a test for the calibration scenario "Interval with heat outside a run";
  - a test that a closure without `heat` loads;
  - a synthetic fixture with the made-up entity IDs of `tests/fixtures`: a day with the hourly counter increases of
    2026-06-24 (0.35, 1.67, 1.15, 1.28, 1.42, 1.57 and 0.67 kWh, 06:00-13:00) while the heating-active binary
    sensor is off, then a run. Through the model and the calibrator the closure is kept, and its error is 0 within
    0.1 K when the charged temperature matches the heat;
  - `python scripts/lint.py`.
- [ ] 3.4 Run the backtest on the October export and the export of 1.1. Verify: the outputs equal the baseline of
  1.2, apart from timestamps, because neither export has a short run or heat outside a run. Report any difference to
  the orchestrator instead of changing a test.
- [ ] 3.5 Update `docs/model.md` ("Heat input", "The tank sensor as a measurement", "The charge closure") with the
  heat outside a run, the credit and the closure equation, with the June evidence of design D3 (without entity IDs).
  Update the README's "Supported heat sources" and "Limitations": heat outside DHW runs needs a heating-active binary
  sensor, and counter-only or power-only detection counts it as a run. Verify: `python scripts/lint.py`.

## 4. Calibrator windows

- [ ] 4.1 Save the open quiet window and the first-drop state with the calibration state, and restore them with
  defaults (design D5). Verify:
  - tests for the calibration scenarios "Options saved during a quiet night", "Reload before the first sensor drop"
    and "Store from before the change", through a reload of the entry in the runtime;
  - a test that a calibration saved by this change loads in a copy of the previous release's `Calibrator.restore`;
  - `python scripts/lint.py`.
- [ ] 4.2 Update `docs/model.md` ("Learning") on what survives a reload. Remove the item "Persist the calibrator's
  open windows" wherever the docs still name it as open. Verify: `python scripts/lint.py`.

## 5. Humidity silence and the detection backup

- [ ] 5.1 Add the option "Humidity silence time" (`humidity_silence`, hours, default 2, 0-24, step 0.5) to
  `const.py`, `ModelOptions` and the draws step of the options flow, with strings and translations (design D6).
  Verify: tests for the integration-setup scenarios "Fresh entry, draws and heat" and "Existing entry after the
  update", and `python scripts/lint.py --hassfest`.
- [ ] 5.2 In `model.py`, track each humidity sensor's last report and whether its last state was unavailable, the
  silent state and the degraded state (design D6). Save the reports with a default of none. In `estimator.py`, pass
  each humidity state's `last_reported` with every humidity state fed (at start too) and on every tick. Verify:
  - tests for the draw-classification scenarios "Sensor goes quiet", "Unchanged reports" and "Silence check off";
  - the integration-setup scenario "Reload during a humidity silence" through the runtime, with a `State` whose
    `last_reported` is older than its feed time;
  - the store tests of D10 for the new key;
  - `python scripts/lint.py`.
- [ ] 5.3 In `classification.py`, let the degraded state start a shower on a session of the next shower time, and
  count down to it in `session_shower_time` (design D7). Verify:
  - tests for the draw-classification scenarios "Shower during a silence", "Short draw during a silence", "Sensor
    unavailable", "One of two sensors still reports" and "Sensor reports again";
  - a test for the integration-setup scenario "Draw while the humidity sensor is silent";
  - `python scripts/lint.py`.
- [ ] 5.4 Add to the diagnostics each humidity sensor's last report and silent state, and the degraded flag (design
  D9). Verify: the part of the integration-setup scenario "Silent humidity sensor in the diagnostics" without the
  repair issue (group 6 adds that), and `python scripts/lint.py`.
- [ ] 5.5 Run the backtest on the October export and the export of 1.1, and compare with the baseline of 1.2
  (design D11). Record the comparison in `private/installation.md`:
  - the shower of 2026-10-10 (start, end, litres mixed, flow sample);
  - every other shower whose classification changed, with the reason;
  - the charge errors (mean and worst), and the charge error of the closure after 2026-10-10.

  Put the evidence without entity IDs into `docs/model.md`. Verify: the comparison is in `private/installation.md`
  with the date, and `python scripts/lint.py`.
- [ ] 5.6 **User review.** Show the user the comparison of 5.5 and ask whether the silence time default of 2 h
  holds. Record the decision with its date in this task, and update the docs and the default if it changes.
- [ ] 5.7 Update `docs/model.md` ("Draw classification") with the silence, the backup and the evidence of design D6
  and D7. Update the README: the options table, "How the estimate updates", the troubleshooting entry on missed
  showers, and the limitations (a 5-minute draw counts as a shower while no humidity sensor reports). Verify: `python
  scripts/lint.py` (including `tests/test_readme.py`).

## 6. Repair issues

- [ ] 6.1 In `estimator.py`, raise and remove the repair issues of design D8: the thresholds in `const.py`, the
  out-since rule, a check on every tick and on every source state change, and the issue id, severity and flags.
  Remove the entry's issues on unload, and on removal in `__init__.py`. Add one translation per role in
  `strings.json` and `translations/en.json` that names the tank and the entity and says what the estimate loses.
  Verify:
  - tests for the integration-setup scenarios "Water meter out for 40 minutes", "Short dropout", "Source back",
    "Silent humidity sensor" and "Entry removed";
  - a test that a reload raises the issue again at once for a source still out since before the reload;
  - `python scripts/lint.py --hassfest`.
- [ ] 6.2 Add the entry's open repair issues to the diagnostics (design D9). Set the quality-scale rule
  `repair-issues` to done, with a comment that names the issues. Verify: the whole integration-setup scenario
  "Silent humidity sensor in the diagnostics", `tests/test_quality_scale.py`, and `python scripts/lint.py`.
- [ ] 6.3 Update the README: a "Repair issues" section with the thresholds and what each issue means, and the
  troubleshooting entries that point to it. Update `docs/development.md` ("Quality scale") if it lists the rule as
  todo. Verify: `python scripts/lint.py` (including `tests/test_readme.py`).

## 7. Rollout

- [ ] 7.1 **Requires the user's authorization.** Deploy and restart from master after group 6 is committed. Verify
  through the home-assistant MCP server:
  - the entry loads, and the state is kept (T_avg, T_ch, the shower flow, the calibration samples);
  - the draws step of an aborted options flow shows the humidity silence time at 2 h;
  - the Repairs list has no issue of the integration while every source is available;
  - the diagnostics show the humidity sensor's last report and the degraded flag off;
  - the system log has no entries for the integration.

  Record the result in `private/installation.md`. Roll back by deploying the previous commit and restarting.
- [ ] 7.2 **Requires the user's authorization** (reading the history, the diagnostics and the Repairs list only, no
  change). Live check at the next humidity silence of at least 2 h:
  - the humidity repair issue appears 2 h after the last report and goes at the next report;
  - the diagnostics show the sensor silent and the fallback on;
  - a draw of at least 5 minutes in that time counts as a shower, if there is one;
  - the diagnostics' last report against the last recorded change shows whether the sensor reports unchanged values
    (design, Risks).

  Record the evidence in `private/installation.md`. Verify: the diagnostics and the Repairs list during the silence,
  and the history after it.

## Workflow follow-up

- One fresh Opus review of the whole change before archiving (`openspec/config.yaml`, Review loop).
- Sync the delta specs into `openspec/specs/` and archive the change (`/opsx:archive`).
