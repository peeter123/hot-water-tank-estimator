# Tasks

## 1. Project scaffold

- [ ] 1.1 Add `pyproject.toml`:
  - project metadata and Python 3.13;
  - ruff config (line length 120, rules E, F, I, UP, B, SIM, RUF);
  - pytest config (`asyncio_mode = auto`, testpaths `tests`).

  Add `requirements_test.txt` with `pytest-homeassistant-custom-component` (pinned to a release for the current
  Home Assistant) and `ruff`. Verify: `python -m venv .venv`, install, then `ruff --version` and
  `pytest --version` both run.
- [ ] 1.2 Add `scripts/check.py`, which runs `ruff check`, `ruff format --check` and `pytest -q` in turn and exits
  non-zero on the first failure. Update `openspec/config.yaml` to name it as the check command. Verify:
  `python scripts/check.py` passes on the empty project (pytest "no tests" counts as a pass).
- [ ] 1.3 Add the quality hook: `.claude/settings.json` with a PostToolUse hook on Edit/Write/MultiEdit that runs
  `scripts/check_on_edit.py`. The hook runs ruff fix and format on an edited `.py` file, then the tests for its
  module, and prints failures, following the pattern of hrv-ventilation's `scripts/check-on-edit.mjs`. Verify:
  editing a file with a lint error makes the hook report it.
- [ ] 1.4 Add a minimal integration that loads:
  - `custom_components/hot_water_tank_estimator/manifest.json` (fields per the packaging spec, version 0.0.1);
  - `__init__.py` with an empty `async_setup_entry` and `async_unload_entry`;
  - `const.py` with `DOMAIN`;
  - `hacs.json`.

  Verify: a pytest smoke test imports the package and checks that `manifest.json` has the required keys.
- [ ] 1.5 Review group 1: `/code-review` on the group's changes, fix confirmed findings, commit.

## 2. Tank model (pure Python)

- [ ] 2.1 Implement `model.py` with the tank-model spec, without Home Assistant imports:
  - state;
  - draw, energy and power heat updates;
  - heating detection fallbacks (D3);
  - anchor, follow-up without heat input, standing loss, cap, bounds;
  - the cold water curve or sensor;
  - outputs (litres, percent, minutes);
  - a bounded event log.

  Verify: `tests/test_model.py` has one test per tank-model scenario, with the numbers from the spec, all passing.
- [ ] 2.2 Implement draw classification in `model.py` with the draw-classification spec:
  - meter deltas with unit conversion;
  - resets and implausible jumps;
  - sessions;
  - humidity window minimum with hysteresis;
  - the long-draw rule;
  - the recount at detection;
  - the other share.

  Verify: `tests/test_classification.py` has one test per draw-classification scenario, all passing.
- [ ] 2.3 Add serialisation of the model state (to and from a plain dict) for restore. Verify: a round-trip test
  restores a mid-shower session and the humidity window, and the next reading gives the same result as an
  unrestored model.
- [ ] 2.4 Build the replay fixture:
  - Add `scripts/history.py`, a websocket history fetch with the token from a file and entity IDs as arguments,
    reused by the backtest later.
  - Use it to export the development installation's evidence-1 and evidence-2 windows (entity IDs are in
    `private/installation.md`) into `tests/fixtures/long_shower.json`, with every entity ID replaced by a made-up
    one.

  Verify: `git grep` on the fixture finds no real entity ID, and `tests/test_replay.py` checks that:
  - the model stays above the floor until at least 200 L into the shower;
  - remaining reaches 0-40 L by the end of the shower;
  - the anchor at the end of the recharge differs from the sensor by no more than 3 K.
- [ ] 2.5 Write `docs/model.md`: every formula with symbols and units, the reason for each anchor, cap and default
  (from design D1-D6, with no installation-specific IDs), and how draws are classified. Verify: each formula in
  the doc matches the code, checked by the review in 2.6.
- [ ] 2.6 Review group 2: `/code-review` and `/simplify` on the group's changes, fix confirmed findings, commit.

## 3. Home Assistant integration

- [ ] 3.1 Implement the config flow (D7 steps) with entity selectors filtered by domain and device class, and the
  validation from the integration-setup spec:
  - volume range;
  - at least one heat source;
  - volume unit on the water meter.

  Verify: `tests/test_config_flow.py` covers a successful entry and each validation error.
- [ ] 3.2 Implement the options flow with every tuning value, its default and the optional sources. An options
  update reloads the entry. Verify: a test changes the floor temperature and checks that the tank average is
  unchanged after the reload, and the remaining litres are recalculated.
- [ ] 3.3 Implement the estimator runtime:
  - `entry.runtime_data`;
  - state change listeners for every configured source;
  - the 5-minute interval;
  - a dispatcher signal to the entities;
  - the first-start value (sensor, else full temperature).

  Verify: tests drive `hass.states.async_set` on made-up source entities through a short shower and a heating
  cycle, and check the entity states.
- [ ] 3.4 Implement the entities with names from translations, units, device and state classes, all on one device
  per entry:
  - sensors for tank average (RestoreSensor with extra stored data), remaining, percent, minutes and cold water;
  - the shower detected binary sensor.

  Verify: a restart test (`async_mock_restore_state_cache`) restores the tank average, the meter reading and the
  session, and a test checks that the binary sensor is unavailable without detection methods.
- [ ] 3.5 Implement the `set_tank_average` action (`services.yaml`, translated fields), with and without a
  temperature. Verify: tests for both scenarios in the spec, including the error when the sensor is unavailable.
- [ ] 3.6 Handle unavailable sources and counter resets per the integration-setup spec. Verify: tests for a water
  meter that is offline briefly, an energy counter reset, and a tank sensor that is unavailable at anchor time.
- [ ] 3.7 Implement diagnostics: options, state, source availability and the last 50 events. Verify: a diagnostics
  test checks the keys.
- [ ] 3.8 Write `strings.json` and `translations/en.json` (plain text, no emoji). Write the README sections on
  configuration fields, options and entities. Verify: hassfest passes locally, or in CI once 7.2 exists, and every
  config and options field appears in the README.
- [ ] 3.9 Review group 3: `/code-review` and `/simplify` on the group's changes, fix confirmed findings, commit.

## 4. Backtest and tuning

- [ ] 4.1 Implement `scripts/backtest.py`: fetch history through `scripts/history.py`, replay it through
  `model.py` with options from command-line arguments or a JSON file, and print:
  - the error before each anchor;
  - each shower with the litres before and after;
  - a grid search over the other share and the floor that minimises the anchor error.

  Verify: running it on the test fixture prints the expected anchor error.
- [ ] 4.2 Run the backtest on the development installation's last 10 days. Record the results and the chosen
  values in `private/installation.md`. If a default should change, update the defaults scenarios in the
  integration-setup spec, design D4/D5, `const.py`, the README and `docs/model.md` together. Verify: the backtest
  output with the chosen values shows a mean absolute anchor error of 3 K or less.
- [ ] 4.3 Document the backtest's usage in `docs/model.md` and the README's tuning section. Verify: the documented
  command runs as written against the fixture.
- [ ] 4.4 Review group 4: `/code-review` on the group's changes, fix confirmed findings, commit.

## 5. Rollout on the development installation

- [ ] 5.1 In the author's Home Assistant config workspace, add a `$Mappings` entry to `scripts/deploy.ps1` for
  `custom_components/hot_water_tank_estimator/` -> `custom_components/hot_water_tank_estimator/`, and document it
  in that workspace's `docs/deploy.md`. Deploy, then restart Home Assistant. Verify: the deploy hook reports the
  upload, and "Hot Water Tank Estimator" appears among the integrations that can be added.
- [ ] 5.2 Add the config entry with the entities from `private/installation.md` and the tuned options. Verify:
  - all six entities exist and the tank average is within 3 K of the tank sensor (state check through the
    home-assistant MCP server);
  - the next water draw shows up in the diagnostics events.
- [ ] 5.3 Live check over the next shower and heating cycle:
  - shower detected turns on within 2 minutes of the shower starting;
  - remaining drops by about 0.6 times the shower volume;
  - at the end of the cycle the anchor event shows an error of 3 K or less.

  Record the result in `private/installation.md`. Verify: the diagnostics download shows these events.
- [ ] 5.4 Review group 5: check that nothing installation-specific was committed to this repo
  (no real entity ID such as one from `private/installation.md` appears in `git grep`; product names in
  the README are fine), then commit.

## 6. Dashboard on the development installation

- [ ] 6.1 In the development installation's heating dashboard, add a "Hot Water" block next to the DHW Price
  Block section:
  - tiles for remaining (L), percent and shower minutes;
  - a 24 h history graph of the tank average, the tank sensor and shower detected.

  Edit with a targeted dashboard transform, not a full rewrite. Document it in the config workspace's
  `docs/dhw-price-block.md` and in `private/installation.md`. Verify: a dashboard search for the new entities
  returns the cards, and their states render (or a Puppet screenshot if the dashboard is reachable there).
- [ ] 6.2 Add stock-card dashboard example YAML to the README, with made-up entity IDs. Verify: the README
  example uses only core cards and only `hot_water_tank_estimator` entity names.
- [ ] 6.3 Review group 6: `/code-review` on the group's changes, fix confirmed findings, commit.

## 7. Packaging and release

- [ ] 7.1 Complete the README:
  - purpose and requirements;
  - HACS and manual install;
  - configuration and options (from 3.8);
  - entities;
  - model summary linking `docs/model.md`;
  - tuning (from 4.3);
  - dashboard example (from 6.2);
  - limitations (from design Risks).

  Verify: every README requirement in the packaging spec has its section.
- [ ] 7.2 Add GitHub Actions: `validate.yml` (hassfest and the HACS action) and `tests.yml` (ruff check, ruff format
  check, pytest) on push and pull request. Verify: the workflows pass on GitHub after the repository is published.
  Ask the user before creating the GitHub repository and pushing.
- [ ] 7.3 Set the manifest version to 0.1.0, tag `v0.1.0` and create a GitHub release with notes. Verify: HACS
  shows version 0.1.0 when the repository is added as a custom repository on the development installation.
- [ ] 7.4 Review group 7: `/code-review` on the group's changes, fix confirmed findings, commit.

## Workflow follow-up

- Sync the delta specs into `openspec/specs/` and archive the change once every group is reviewed
  (`/opsx:archive`).
- Update the author's config workspace `CLAUDE.md` project note from "planned" to "live".
