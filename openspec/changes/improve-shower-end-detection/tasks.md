# Tasks

Read these before each group:
- `AGENTS.md`, `openspec/config.yaml` and `docs/development.md`;
- this change's proposal and design;
- its specs: `specs/draw-classification/spec.md` and `specs/integration-setup/spec.md`, and the requirements they
  modify in `openspec/specs/`.

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
- Stores saved before this change must still load, and a store saved by this change must load in the previous
  release (design D5).

## 1. Backtest shower list and the baseline

- [x] 1.1 Export the November history of the development installation before the recorder purges it: every role of
  the October export (`private/history/2026-10-01_2026-10-31/`), from 2026-11-01 to the day of the export, into
  `private/history/2026-11-01_<to>/` with `scripts/history.py`, reading the recorder only. Verify: one file per role,
  and the first and last timestamps of each cover the window (or say why a role starts later).
- [x] 1.2 Extend the shower list of `scripts/backtest.py` (design D6) with each detected shower's start and end
  times, its litres, its minutes of flow and its flow sample (or "no sample" below 3 minutes of flow). Verify: a test
  in `tests/test_backtest.py` on an existing replay fixture checks those fields for one shower, and
  `python scripts/lint.py`.
- [x] 1.3 Run the backtest at this group's commit, under the current detection rule, on the October and the November
  exports. Save both outputs in `private/analysis/` as the baseline, and record in `private/installation.md` per
  month: the number of showers, their start and end times, the litres counted as mixed, the flow samples and the
  charge errors. Verify: both output files exist, and the summary is in `private/installation.md` with the date.
- [x] 1.4 Update `openspec/backlog.md`: remove the item `improve-shower-end-detection` (it is this change), and add
  to `add-source-health-repairs` the long-draw backup while the humidity sensor is unavailable (proposal, Out of
  scope). Verify: `python scripts/lint.py`.

## 2. Shower lifecycle in the classifier

- [ ] 2.1 Implement design D1, D2 and D4 in `classification.py`, with the two new options in `ClassifierOptions`
  and `ModelOptions` (design D3: `shower_end_minutes` 5, `next_shower_minutes` 5) and whether a humidity sensor is
  configured, from the entry's sources:
  - a shower starts on the humid edge, on a session of the next shower time while humid and no shower is in
    progress, or, without a humidity sensor, on a session of the long-draw duration;
  - a shower ends at `t_ref + N`, dated then, before any reading at or after that time is handled;
  - `detected`, the rolling flow and the shower report follow the shower in progress.

  Verify: tests in `tests/test_classification.py` for the draw-classification scenarios "Shower starts", "The water
  stops", "Pause in a shower", "Humidity dips while the water runs", "Humidity rise without water", "Bathroom
  dries", "Long draw without humidity sensor", "Pause in a long-draw shower", "Long draw with a humidity sensor",
  "Second shower" and "Washbasin after a shower". Also a test that a reading after the deadline, with no call in
  between, is classified after the shower has ended.
- [ ] 2.2 Expose the next shower end from the model (the deadline of the shower in progress, or none), for the
  runtime timer of group 3. Verify: a model test with a shower in progress and one without.
- [ ] 2.3 Implement the saved state of design D5: the shower start, the humid edge state, the previous release's
  keys still written, and restore of a state without the new keys. Verify: tests that a store without the new keys
  loads, that a saved state loads in a copy of the previous release's `restore` (or checks the keys it reads), and
  the integration-setup scenarios "Restart in the humid bathroom after a shower" and "Restart during a shower" at
  the model level.
- [ ] 2.4 Run the replay tests. `back_to_back` should pass unchanged (design, Risks). Verify: `python
  scripts/lint.py`; if a replay test fails, report its data to the orchestrator instead of changing the test.
- [ ] 2.5 Update `docs/model.md` ("Draw classification", "Shower flow"): the shower lifecycle with the diagram, the
  end rule, the next shower rule, the long-draw rule only without a humidity sensor, the binary sensor's meaning, and
  the evidence of design D1, D3 and D4 (October; the backtest numbers follow in group 4). Update the README's
  entities row for "Shower detected", the troubleshooting entries on detection and the limitations (a humidity rise
  without a shower now ends after the shower end time). Verify: `python scripts/lint.py`.

## 3. Options and the end timer

- [ ] 3.1 Add the two options to the options flow (design D3 bounds and steps), with their strings and
  translations, and change the long-draw option's description: it applies only without a humidity sensor. Verify:
  tests for the integration-setup scenarios "Fresh entry, draws and heat" and "Existing entry after the update",
  and an options-flow test that saving the two options keeps T_avg and the calibration state.
- [ ] 3.2 Implement the runtime timer of design D2 in `estimator.py`: after every update, reschedule a one-shot
  callback at the model's next shower end, cancel it when there is none, and cancel it on stop. Verify: a test that
  the binary sensor turns off at the shower end time with no reading and no tick in between, and that a stopped
  entry leaves no timer.
- [ ] 3.3 Update the README: the options table (the two options, the long-draw option's new scope, marked as a
  change for entries that set both), and the "How it works" text on detection. Verify: `python scripts/lint.py`
  (including `tests/test_readme.py`) and `python scripts/lint.py --hassfest`.

## 4. Evidence and rollout

- [ ] 4.1 Run the backtest with the new rules on the October and November exports, compare with the baseline of
  1.3, and record the comparison in `private/installation.md`: shower starts and ends, litres counted as mixed,
  flow samples, charge errors (mean and worst), and every shower whose classification changed with the reason. Put
  the evidence without entity IDs into `docs/model.md`, replacing the exploration numbers where they differ. Verify:
  the comparison is in `private/installation.md` with the date, and `python scripts/lint.py`.
- [ ] 4.2 **User review.** Show the user the comparison of 4.1 and ask whether the defaults hold (shower end time
  5 min, next shower time 5 min). Record the decision with its date in this task, and update the docs and the
  defaults if one changes.
- [ ] 4.3 With authorization, deploy and restart from master after group 3 is committed. Verify through the
  home-assistant MCP server: the entry loads, the state is kept (T_avg and the shower flow), the options form shows
  the two new options at 5 min, and the system log has no entries for the integration. Record the result in
  `private/installation.md`. Roll back by deploying the previous commit and restarting.
- [ ] 4.4 Live check at the next shower (reading the history and the diagnostics only, no change): the shower
  detected binary sensor turns off about 5 minutes after the water stops, a draw shortly after it stays an other draw
  (if there is one), and the shower flow sample is added at the end. Record the evidence in
  `private/installation.md`. Verify: the history of the binary sensor and the water meter, and the diagnostics
  events.

## Workflow follow-up

- One fresh Opus review of the whole change before archiving (`openspec/config.yaml`, Review loop).
- Sync the delta specs into `openspec/specs/` and archive the change (`/opsx:archive`).
