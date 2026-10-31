# Tasks

Read these before each group:
- `AGENTS.md`, `openspec/config.yaml`, and `docs/development.md` once group 1 has created it;
- this change's proposal and design;
- its specs: `specs/tank-model/spec.md`, `specs/draw-classification/spec.md`, `specs/calibration/spec.md`,
  `specs/integration-setup/spec.md` and `specs/packaging/spec.md`.

Each group runs in a fresh session and is committed on its own by the apply workflow. So each group must leave
`python scripts/lint.py` (once it exists) and the tests passing.

Applies to every group:
- Nothing installation-specific enters a tracked file. Entity IDs, history and calibration results of the
  development installation stay in `private/`. Fixtures use made-up entity IDs such as `sensor.tank_temperature`.
- Never read or print `%USERPROFILE%\.ha_token`. Scripts read it themselves.
- Live Home Assistant steps (deploy, restart, config entry, dashboard) run only in the tasks that name them, after
  the user authorizes them in the session, through the home-assistant MCP server or the config workspace's
  `scripts/deploy.ps1`.
- Documentation follows the "Documentation" section of `AGENTS.md`, in the same group as the change it describes.
  There are no line-number citations, and superseded text is removed.
- Numbers in tests come from the spec scenarios. A test named after a scenario checks that scenario's numbers.

## 1. Tooling and scaffold (no model code)

- [x] 1.1 Add `pyproject.toml` with project metadata, Python 3.14.2 or later, Home Assistant core's ruff rule set
  (ruff 0.17.3) and the pytest config. Add `.yamllint` and `.codespellrc`. Done during planning on 2026-10-31, with
  the user's request to bring in the linter and quality rules. Verify: `python scripts/lint.py` exits 0.
- [x] 1.2 Add `requirements_test.txt` with an exact pin of `pytest-homeassistant-custom-component` (the release
  matching the newest Home Assistant it supports) and an empty `tests/__init__.py`. Verify:
  `uv run --no-project --with-requirements requirements_test.txt pytest --version` prints the pinned pytest, and
  `python scripts/lint.py` runs the (empty) suite and exits 0.
- [x] 1.3 Add `scripts/lint.py`, `scripts/md_format.py` (from esphome-zehnder-comfoair) and the edit hook
  `scripts/check_on_edit.py` with `.claude/settings.json`. Done during planning on 2026-10-31. Verified then:
  - lint exits 0 on the repository;
  - the hook repairs a CRLF Markdown file;
  - it reports an undefined name in a Python file with exit code 2.
- [x] 1.4 Add a minimal integration that loads:
  - `custom_components/hot_water_tank_estimator/manifest.json` (fields per the packaging spec, version 0.0.1);
  - `__init__.py` with empty setup and unload;
  - `const.py` with `DOMAIN`;
  - `hacs.json`.

  Verify: `tests/test_manifest.py` checks the manifest keys, and `python scripts/lint.py` exits 0.
- [x] 1.5 Write `docs/development.md` (tools, rules, quality scale, tests, private data) and `docs/README.md`. Done
  during planning on 2026-10-31. Verify: both pass the Markdown check.
- [x] 1.6 Add `quality_scale.yaml` to the integration, with every rule of the Integration Quality Scale as todo or
  exempt (with a reason), per `docs/development.md`. hassfest does not validate this file for custom integrations,
  so add `tests/test_quality_scale.py` with a copy of hassfest's rule list (and the date it was copied). Verify:
  the test checks that the file has exactly those rules, each `done`, `todo`, or `exempt` with a comment, and it
  passes. hassfest itself runs in CI from 7.3.

- [ ] 1.7 Remote test runner, added on 2026-10-31 at the user's request instead of WSL, which conflicts with VMware on
  the development PC. Native Windows cannot load Home Assistant's test plugin.
  - `docker/test-runner/` holds a Dockerfile and a `compose.yaml` for a long-running container on a Docker host such
    as a NAS:
    - the pinned uv and Python 3.14 image, with `requirements_test.txt` installed;
    - `sshd` on a published port, key-only, as a non-root user;
    - the authorized key passed in through the compose environment;
    - hassfest for the pinned Home Assistant version.
  - `scripts/remote_test.py` (standard library) syncs the files `git ls-files` lists, never `private/` or `.git`,
    into the container over SSH. It then runs pytest, or hassfest, there and returns their exit code.
  - The runner's address and key path come from a git-ignored file in `private/`, so no hostname enters a tracked
    file.
  - `scripts/lint.py` and the edit hook use the runner when it is configured, and fall back to the native
    run otherwise.
  - `docs/development.md` describes the setup.

  Verify: on the user's runner, the suite passes through `python scripts/lint.py`, and hassfest passes.

## 2. Tank model and draw classification (pure Python)

- [x] 2.1 Implement the tank-model spec in `model.py`:
  - state (T_avg, T_ch, f);
  - mixed and other draws;
  - energy and power heat with start-up energy;
  - heating detection (D3);
  - charging at run end with the 2-minute flow and return ring (D4);
  - binary-only follow-up;
  - standing loss on both temperatures;
  - the sensor rules (D5: lower bound, thermocline cap, cold cap, raise of T_ch);
  - physical bounds;
  - the cold water curve or sensor;
  - outputs (tank litres, shower litres, percent charged, minutes);
  - a bounded event log.

  Verify: `tests/test_model.py` has one test per tank-model scenario, all passing.
- [x] 2.2 Implement the draw-classification spec in `model.py`:
  - meter deltas with unit conversion;
  - resets and implausible jumps;
  - sessions;
  - the humidity window minimum with hysteresis;
  - the long-draw rule;
  - the reclassify window;
  - mixed and other draws.

  Verify: `tests/test_classification.py` has one test per scenario, all passing.
- [x] 2.3 Add serialisation of the full model state to and from a plain dict: both temperatures, meter and energy
  readings, run state, session, humidity window and flow/return ring. Verify: a round-trip test restores a
  mid-shower, mid-run state, and the next readings give the same results as an unrestored model.
- [x] 2.4 Write `docs/model.md` from design D1-D8: every formula with symbols and units, the reason for each charge
  rule, sensor bound and default, and the draw classification. Do not include installation-specific IDs. Verify:
  the Markdown check passes, and each formula appears in `model.py` with the same symbols, checked by the group
  review.

## 3. Test data from recorded history

- [x] 3.1 Add `scripts/history.py`: a REST history export with the token read from a file (never printed), entity
  IDs per role and the time range as arguments, and JSON per role as output, in the format of the files in
  `private/history/`. Add `scripts/anonymise.py`, which cuts a window from an export into a fixture with made-up
  entity IDs and only the roles the model uses. Verify: running anonymise on
  `private/history/2026-10-01_2026-10-31/` for a 1-hour window gives a fixture in which `git grep` finds no real
  entity ID.
- [x] 3.2 Build the six fixtures of design D10 (`long_shower`, `shower_unseen`, `back_to_back`, `late_detection`,
  `quiet_days`, `week`) into `tests/fixtures/`, using the role mapping in `private/installation.md`. Verify: the
  fixtures are each under 500 kB, a scan for every entity ID in `private/installation.md` finds none of them, and a
  replay of each fixture equals a replay of the same window built from the raw export. A fixture thinned with
  `--thin` may lag inside heating runs by up to 0.1 K of T_avg; each charge agrees within 0.001 K.
- [x] 3.3 Add `tests/test_replay.py`, which replays each fixture with the default options and checks:
  - `long_shower`: shower water stays above 0 until at least 200 L into the session; tank water is 0-60 L at its
    end; the charge at the end of the recovery run is within 3 K of the model before the charge, once the
    start-up energy of 1.8 kWh is set in the options.
  - `shower_unseen`: the lower sensor bound holds T_avg at or above `T_ch - 0.325 * (T_ch - T_cold)` through the
    141 L shower, and shower water stays above 150 L.
  - `back_to_back`: shower detection reclassifies the litres from the start of the first session. No litre of
    either session stays an other draw: the second starts while detection still holds. The cold cap or the
    thermocline cap acts during the second session.
  - `late_detection`: detection 6.3 minutes into the session reclassifies every litre the session drew before it,
    with the default 10-minute window.
  - `quiet_days`: no output falls more than 10 % in a night without draws.
  - A fixture's first charge starts from the sensor reading, and is labelled a sensor-start charge in the
    recorded numbers. Later charges are closures, and only those count towards the closure errors.

  Verify: the tests pass. Record the replayed numbers in `private/installation.md` under "Replay results" with the
  date.
- [x] 3.4 **User review.** Show the user the replay numbers from 3.3 (litres and charge errors per fixture), and
  ask whether the outputs match what they remember of those evenings. Record their answer with its date in this
  task and in `private/installation.md`. Verify: the decision is recorded.
  - 2026-10-31: the user confirmed that the outputs match. None of the showers on 13, 14, 22 or 29 October ran cold
    or lukewarm, so the model is right that hot water was left at the end of each. The user also kept the
    reclassify window default at 10 minutes.

## 4. Calibration (pure Python, plus the backtest)

- [x] 4.1 Implement the closure sums and the fitter in `calibration.py`, per the calibration spec and design D11:
  - interval sums from the energy balance without sensor bounds;
  - the true start average;
  - weighted least squares with forgetting factor 0.95;
  - at least 5 intervals before applying;
  - the step limit;
  - bounds and locks;
  - the excluded closures;
  - counter increases within 10 minutes after a run end count towards that run's energy (D11, counter lag). The
    model of group 2 drops them, so extend its charge event or interval data for this;
  - draws and loss during a run belong in its closure:
    `T_true_start = T_charge - (E_run - S) / C + mixed_run + share * other_run + k * loss_run`. Group 2's model
    leaves the in-run sums out, so extend its charge event, and update D11 and the calibration spec to match;
  - per-source unavailable time within each interval, for the 10 % exclusion.

  Pure-module imports: the package `__init__.py` imports Home Assistant, so the backtest and the setup fit either
  run in the test environment (`uv run --no-project --with-requirements requirements_test.txt`) or load `model.py`,
  `classification.py` and `calibration.py` without the package `__init__`. Choose one and document it.

  Verify: `tests/test_calibration.py` covers each calibration scenario. A synthetic test generates intervals from
  known parameters and recovers them within 5 %.
- [x] 4.2 Implement quiet-window loss learning and the first-drop width estimator. The width estimator needs the
  cold fraction of the balance without sensor bounds at the first drop; the model keeps it in private fields, so
  expose it. Verify: tests for the quiet-night
  scenario and the sensor-drop scenario, and a test that a window with a draw is skipped.
- [x] 4.3 Implement the setup-fit replay as a pure function: history in, parameters and calibration state out,
  shared with the backtest. Verify: on the `week` fixture it returns 7 closures, share 0.1-0.3, start-up energy
  1.0-2.6 kWh, k 0.002-0.007, and a mean absolute charge error of 2.5 K or less.
- [x] 4.4 Add `scripts/backtest.py` per design D10. It runs on any history export with options from arguments or
  JSON, and prints the charge errors, the showers, the fitted parameters and the error with fitted against default
  parameters. Verify: on the `week` fixture its fitted parameters equal those of 4.3.
- [x] 4.5 Run the backtest on `private/history/2026-10-01_2026-10-31/`, and record the fit and the errors in
  `private/installation.md` under "Backtest results" with the date. Verify: the mean absolute charge error with
  the fitted parameters is 2.5 K or less.
- [x] 4.6 **User review.** Show the user the fitted parameters and the error against the shipped defaults. Ask
  whether to change any shipped default; the defaults are meant to be generic, not this tank's fit. If one changes,
  update the defaults scenarios in the integration-setup spec, design D2-D7, `const.py` and `docs/model.md`
  together. Record the decision with its date. Verify: the decision is recorded, and the lint and tests pass.
  - 2026-10-31: the user kept every shipped default. The fit on October is share 0.18, start-up energy 1.74 kWh, k
    0.0040 per hour and w 0.33, with a mean charge error of 1.92 K, against 5.42 K with the defaults. The share, k
    and w defaults are already close to it. The start-up energy stays 0: it depends on the plumbing, it only matters
    during a run, and the setup fit learns it.
- [x] 4.7 Document calibration in `docs/model.md`: the closure equation, learning, bounds and locks, the setup fit
  and the backtest's usage. Verify: the documented backtest command runs as written on the `week` fixture.

## 5. Home Assistant integration

- [ ] 5.1 Config flow (design D9 steps), with selectors filtered by domain and device class, and the validation in
  the integration-setup spec:
  - volume;
  - sensor height 20-80 %;
  - at least one heat source;
  - flow and return as a pair;
  - a volume unit on the water meter.

  Verify: `tests/test_config_flow.py` covers a successful entry and each error scenario.
- [ ] 5.2 Options flow with every tuning value and its default, the optional sources, a lock per learned parameter
  and the history days. An update reloads the entry. Verify: a test changes the sensor height, and T_avg, T_ch and
  the calibration state are unchanged after the reload.
- [ ] 5.3 Estimator runtime:
  - `entry.runtime_data`;
  - state listeners for every configured source;
  - the flow and return ring;
  - the 5-minute interval;
  - the dispatcher signal;
  - the first start, charged at the sensor reading, or 50 C if it is unavailable.

  Verify: tests drive `hass.states.async_set` on made-up sources through a shower and a heating run, and check the
  entity states against the model.
- [ ] 5.4 Calibration in the runtime:
  - a `Store` per entry;
  - the setup fit on entry creation, reading the recorder through its executor and replaying in the executor;
  - closure learning at each charge;
  - quiet-window and width learning;
  - the "Shower ran cold" button.

  Verify: a test with the recorder test fixture loads the `week` fixture as history, creates an entry, and checks
  that the samples sensor reads 7 and the parameters match 4.3. A button test checks the cold-shower scenario.
- [ ] 5.5 Entities, each with translated names, units and device and state classes, on one device per entry:
  - the seven sensors from the integration-setup spec, with the tank average sensor as a RestoreSensor holding the
    model state;
  - the shower detected binary sensor;
  - the button;
  - the diagnostic-category calibration sensors with their `source` attribute.

  Verify: a restart test (`mock_restore_cache_with_extra_data`) restores the model, and a test checks that the
  binary sensor is unavailable without detection methods.
- [ ] 5.6 Actions `set_tank_state` and `recalibrate` (`services.yaml`, translated fields). Verify: tests for each
  scenario in the integration-setup spec, including the error when the sensor is unavailable, and that locked
  parameters survive a recalibration.
- [ ] 5.7 Handling of unavailable sources and counter resets per the integration-setup spec. Verify: tests for the
  water meter that goes offline briefly, the energy counter reset and the tank sensor that flickers.
- [ ] 5.8 Diagnostics: options, state, source availability, the last 100 events and the calibration state. Verify:
  a diagnostics test checks the keys.
- [ ] 5.9 Write `strings.json` and `translations/en.json` (plain text), and the README sections on configuration,
  options, entities, calibration and the diagnostic sensors. Verify: every config and options field and every
  entity appears in the README, and hassfest passes locally (`uvx` or the Docker image) or in CI once 7.3 exists.

## 6. Rollout on the development installation (each task needs the user's authorization)

- [ ] 6.1 In the config workspace `<config-workspace>`, add a `$Mappings` entry to `scripts/deploy.ps1`
  for `custom_components/hot_water_tank_estimator/` -> `custom_components/hot_water_tank_estimator/`, and document
  it in its `docs/deploy.md`. With authorization: deploy and restart Home Assistant. Verify: the deploy hook reports
  the upload, and the integration appears in the list of integrations that can be added.
- [ ] 6.2 With authorization, add the config entry with the entities and sensor height from
  `private/installation.md`. Verify, through the home-assistant MCP server:
  - every entity exists;
  - the setup fit reports at least 20 samples from the recorder's 30 days;
  - its parameters agree with 4.5 within the 4.3 ranges;
  - T_avg is within 3 K of the tank sensor while the sensor reads the hot layer.

  Record the result in `private/installation.md`.
- [ ] 6.3 Live check over the next shower and the next heating run:
  - shower detected turns on within 2 minutes;
  - shower water drops by about the shower's litres;
  - the charge event's error is 3 K or less;
  - the samples sensor goes up by one.

  Record the result in `private/installation.md`. Verify: the diagnostics download shows these events.
- [ ] 6.4 With authorization, add a "Hot Water" block next to the DHW Price Block section of the heating dashboard:
  - tiles for tank water, shower water, percent charged and shower minutes;
  - a 24 h history graph of the tank average, the charged temperature, the tank sensor and shower detected.

  Edit it with a targeted dashboard transform. Document it in the config workspace's `docs/dhw-price-block.md`,
  update its `CLAUDE.md` note from "planned" to "live", and update `private/installation.md`. Verify: a dashboard
  search for the new entities finds the cards.
- [ ] 6.5 Add stock-card dashboard example YAML to the README, with made-up entity IDs. Verify: the example uses
  only core cards and `hot_water_tank_estimator` entity names.

## 7. Packaging and release

- [ ] 7.1 Complete the README:
  - purpose and requirements;
  - HACS and manual install;
  - finding the sensor height;
  - configuration and options;
  - entities;
  - calibration and how to read its diagnostic sensors;
  - a model summary linking `docs/model.md`;
  - the dashboard example;
  - limitations (from design Risks).

  Verify: every README requirement in the packaging spec has its section.
- [ ] 7.2 Bring `quality_scale.yaml` up to date: every applicable Bronze and Silver rule, plus the Gold rules in
  the packaging spec, marked done with the code that meets them. Settle the `brands` rule and the minimum Home
  Assistant version in `hacs.json`. Verify: no applicable Bronze or Silver rule is todo,
  `tests/test_quality_scale.py` passes, and hassfest passes.
- [ ] 7.3 Add GitHub Actions: `validate.yml` (hassfest and the HACS action) and `lint.yml` (`python scripts/lint.py`
  with uv set up) on push and pull request. Verify: the workflow files pass `uvx check-jsonschema` against the
  GitHub workflow schema.
- [ ] 7.4 **User review.** Ask the user to authorize creating the GitHub repository, pushing, tagging `v0.1.0` and
  publishing a release. Record the decision with its date. With authorization: set the manifest version to 0.1.0,
  push, tag and release. Verify: the workflows pass on GitHub, and HACS on the development installation shows
  version 0.1.0 when the repository is added as a custom repository.

## Workflow follow-up

- One fresh Opus review of the whole change before archiving (`openspec/config.yaml`, Review loop).
- Sync the delta specs into `openspec/specs/` and archive the change (`/opsx:archive`).
