# Development rules

The rules for code, tests, scripts and docs in this repository. `scripts/lint.py` enforces them with pinned tools.
They apply to every file a change creates or edits.

## Lint commands

`scripts/lint.py` is the single entry point. It uses only the Python standard library and runs every tool through
`uvx` or `uv run` at an exact version, never from `PATH` (Docker, where used, comes from `PATH` and runs a pinned
image), so it needs no venv; it does need [uv](https://docs.astral.sh/uv/). Exit status: `0` clean, `1` findings,
`2` a tool could not be run.

```sh
python scripts/lint.py          # ruff check, ruff format --check, Markdown format, codespell, yamllint, pytest
python scripts/lint.py --fix    # apply ruff fixes, ruff format and Markdown line-ending fixes, then check
```

Home Assistant does not run on native Windows, so the pytest step uses the first of these that applies
(`pytest_command` in `scripts/lint.py`, shared with the edit hook; the choice is printed):
1. The remote test runner, when the git-ignored file `private/test-runner.json` exists. Set `HWTE_TEST_RUNNER=off`
   to skip it.
2. Windows with a running local Docker engine: the same command runs in the
   `ghcr.io/astral-sh/uv:0.13.1-python3.14-trixie-slim` container, with the repository mounted and a `hwte-uv-cache`
   volume for the uv cache. Run `python scripts/lint.py` once after Docker becomes available to warm that cache: the
   first container run can exceed the edit hook's timeout.
3. Linux and macOS: pytest runs directly through `uv run`.
4. Windows without Docker: pytest runs natively with the Home Assistant plugin disabled and prints a warning. Pure
   Python tests pass; tests that need Home Assistant fail, so lint exits 1.

A runner that cannot be used (no connection, bad config) is a tool failure: `remote_test.py` exits 255, as ssh does,
and lint exits `2`. pytest's own exit code 2 (collection errors) stays a finding.

## Remote test runner

`docker/test-runner/` builds a long-running container for a Docker host such as a NAS. It runs `sshd` (key login only,
port 2222, non-root user `runner`) and holds the pinned test requirements in `/opt/venv`. On the runner, hassfest runs
from Home Assistant core at the tag of the `homeassistant` version in the test venv, in a separate venv
(`/opt/hassfest-venv`) built from the test venv's frozen package set plus the extras hassfest needs (installed as wheels
only), so its dependencies never change the test environment. `docker/test-runner/README.md` explains deployment and the
config file.

`scripts/remote_test.py` (standard library only) copies the files `git ls-files` lists (never `private/` or `.git`)
into a folder of its own in the container over SSH, runs the command there, removes the folder afterwards, and returns
the command's exit code. Folders left by an interrupted run are removed after a day:

```sh
python scripts/remote_test.py pytest [args]    # default -q
python scripts/remote_test.py hassfest
python scripts/remote_test.py shell "cmd; cmd" # the string runs in the remote shell, in the synced folder
python scripts/lint.py --hassfest              # lint plus hassfest on the runner
```

`scripts/brand.py` draws the images in `brand/` from the MDI `radiator` and `water-boiler` glyphs and writes eight
files (icon and logo at 256 and 512 px, each with a `dark_` variant). Run it with
`uv run --with svg.path==7.1 --with pillow==13.0.0 scripts/brand.py <mdi-svg-folder>` (usage in its docstring).

Rebuild the container (`docker compose up -d --build`) after a change to `requirements_test.txt` or the
Dockerfile.

The Claude Code hook in `.claude/settings.json` runs `scripts/check_on_edit.py` after every Edit or Write. It
handles each file type differently:
- an edited `.py` file: ruff fix, ruff format and ruff check, then that module's tests (`tests/test_<module>.py`)
  when they exist;
- an edited `.md` file: the line endings and final newline are repaired and the format is checked;
- an edited YAML file: yamllint.

Findings come back with exit code 2, so the editing agent sees them and fixes them before moving on.

## Tool versions

The tool versions and the ruff rules are Home Assistant core's, so the integration is held to the same standard as
core integrations:

| Tool | Version | Source |
|---|---|---|
| ruff | 0.17.3 | core `requirements_test_pre_commit.txt` (dev branch, 2026-10-31) |
| codespell | 2.4.3 | same |
| yamllint | 1.38.0 | same |
| Python | 3.14.2 or later | core `pyproject.toml` `requires-python` |
| hassfest core tag | derived from `requirements_test.txt` | the `homeassistant` version in the test venv |
| uv image (local Docker and the remote test runner) | `ghcr.io/astral-sh/uv:0.13.1-python3.14-trixie-slim` | `scripts/lint.py` |
| uv in CI | 0.13.1 | the version of that image, set in `lint.yml` |
| `actions/checkout`, `actions/setup-python` | v7 | tags (latest majors, 2026-11-03) |
| `astral-sh/setup-uv` | SHA of v10.3.3 | its README's pin |
| `home-assistant/actions/hassfest`, `hacs/action` | `master`, `main` | documented without release tags |
| pytest-homeassistant-custom-component | 0.13.375 | `requirements_test.txt`; targets Home Assistant 2026.10.4 |

- `.python-version` (3.14) makes `uv run` pick a Python that Home Assistant supports, not the newest installed one.
- The ruff `[tool.ruff.lint]` section in `pyproject.toml` is a copy of core's: selected and ignored rules, banned
  APIs, isort settings, mccabe complexity 25 and the Google docstring convention. Only paths are adapted:
  first-party `custom_components`, and `scripts/*` may print.
- When the ruff pin changes, copy core's section again at that version and update this table.
- Core bans `voluptuous` in favour of `probatio` and the old `config_validation` helpers it replaces, so config and
  options flow schemas use `probatio`.

## Markdown format

`scripts/md_format.py` (from esphome-zehnder-comfoair, same author) checks every tracked Markdown file outside
`.claude/` and `openspec/changes/archive/`:
- LF line endings only;
- exactly one final newline;
- lines of at most 120 characters, except table rows, fenced code and lines with no space to break at (a long URL
  alone).

`--fix` repairs only line endings and final newlines. Prose is never rewrapped automatically.

## Architecture rules

- `model.py`, `classification.py`, `calibration.py` and `setup_fit.py` in
  `custom_components/hot_water_tank_estimator/` are pure Python: standard library only, no Home Assistant imports,
  and no I/O. They take timestamps and numbers and return state and events. Tests, the setup fit and
  `scripts/backtest.py` all run the same code. `setup_fit.py` replays a neutral `History` (per source: role, entity
  ID, unit and `(time, state)` rows), which a fixture, a recorder export and Home Assistant's recorder states can all
  be turned into; the reading of files and of the recorder stays outside the pure modules.
- One `TankEstimator` (`estimator.py`) per config entry, kept in `entry.runtime_data`. It owns the subscriptions
  (`async_track_state_change_event`, a 5-minute `async_track_time_interval`), the model and the calibrator. Entities
  read from it through a dispatcher signal. There is no coordinator, because nothing is polled.
  - A source state goes to the model with the state's `last_updated` as its time: the moment the reading was
    produced. `last_changed` only moves with the value.
  - After every input and tick, `Calibrator.observe` sees the model's events and learns. Changed options go back to
    the model with `set_options`.
  - Temperatures are converted to C, the energy counter to kWh and the power sensor to W (`readings.py`). The
    model converts the water meter's unit itself, from the state's attributes.
  - `async_setup_entry` loads the store, creates the estimator (which restores the model and the calibration from
    it), sets up the platforms and only then starts the listeners.
- Heavy work (the setup fit's history read and replay) runs in the recorder's executor and the default executor,
  never in the event loop. `history.py` turns recorder states into the pure `History`. The fit itself runs as a
  background task of the entry.
- The model state and the calibration state persist together in a `Store` per entry, not in entity restore data, so
  disabling or renaming an entity loses nothing. The estimator asks for a save after every input (it
  requests one only when none is pending, because `Store.async_delay_save` would move a pending write later with
  every request, so the store is written 60 s after the first input and then at most once per 60 s while inputs
  keep arriving) and saves at unload.
  - A replaced water meter or energy counter entity starts a new baseline (`TankModel.forget_reading`).
  - Fits run one at a time. The fit works on a copy of the calibrator, and a button press or manual reset made
    while it ran is kept when it is applied.
  - Calibration changes are logged as `calibration` events with the old and new values and the source.
- Actions (`set_tank_state`, `recalibrate`) are registered in `async_setup` (`services.py`) and resolve their target
  to loaded entries with `async_extract_config_entry_ids`.
- The config flow stores everything in the entry options. The sensor height and the thermocline width are
  percentages there, and fractions in the model.
- All user-facing text lives in `strings.json` and `translations/en.json`. Plain text, no emoji.
- Formulas in code use the symbols of `docs/model.md` (`t_avg`, `t_ch`, `t_cold`, `f`, `h`, `w`, `u`) and give
  units in names or comments.

## Continuous integration

Two workflows in `.github/workflows/` run on every push and pull request:
- `validate.yml` runs hassfest (`home-assistant/actions/hassfest`) and the HACS action (`hacs/action`, category
  integration). The HACS check needs the repository's description, topics and issues, so it fails until the GitHub
  repository has them.
- `lint.yml` sets up Python (from `.python-version`) and uv (pinned, see the table) and runs `python scripts/lint.py`.
  On Linux that runs pytest through `uv run` with the pinned `requirements_test.txt`, with no remote runner.

Check the workflow files with
`uvx check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/*.yml`.

## Quality scale

Home Assistant's Integration Quality Scale is the checklist for integration code. The integration keeps a
`quality_scale.yaml` with the status of each rule (`done`, `todo` or `exempt` with a comment). hassfest does
not validate this file for custom integrations, so `tests/test_quality_scale.py` checks it against a copy of
hassfest's rule list. The target for the first release is Silver, plus these Gold rules that apply to this
integration:
- diagnostics;
- entity translations and icon translations;
- entity categories and device classes;
- reconfiguration (a reconfigure step in the config flow);
- documentation of the data and the known limitations.

Rules about discovery, network connections and authentication are `exempt`, with the reason. The integration has one
device per entry, so only the rules about devices appearing or disappearing at runtime are `exempt`.

## Tests

- pytest with `pytest-homeassistant-custom-component` and `asyncio_mode = auto`.
- A test named after a spec scenario checks that scenario's numbers.
- Fixtures in `tests/fixtures/` come from `scripts/anonymise.py`: made-up entity IDs and only the roles the model
  uses. No real entity ID, hostname or serial enters the repository; the real ones stay in the git-ignored
  `private/` folder.
- `tests/test_replay.py` replays the fixtures through the model with a tick every 5 minutes. A fixture is one JSON
  file: tank volume and sensor height, the window, and the states per made-up entity with its role and unit. The
  format is in the docstring of `scripts/anonymise.py`. The tests read the tank parameters from the fixture, so
  no installation fact is hard-coded.
- `scripts/history.py` exports recorder history over the REST API (one JSON file per role, token read from a file),
  and `scripts/anonymise.py` cuts a window from such an export into a fixture. Both use only the standard library
  and run under the system Python 3.13; `pyproject.toml` sets ruff's target to py313 for `scripts/*.py`, so ruff does
  not rewrite syntax 3.13 cannot parse. An export whose files are not named by role needs a mapping from file stem
  to role (`--map-file`); that mapping holds the installation's naming, so it stays in `private/`. A fixture must
  stay under 500 kB (a test checks it): identical consecutive states are merged, 32-bit float noise is shortened,
  times are rounded to the millisecond, and `--thin` can thin a counter (the `week` fixture uses 20 s on the energy
  counter, keeping the rows around every heating change so each increase stays in its run).
- Home Assistant tests share `tests/common.py`: made-up source entity IDs, entry options, and a `Rig` that changes
  the sources and feeds the same inputs to a reference `TankModel` to compare the entities with. `TID251` (banned
  `tests` import) is ignored under `tests/` for these relative imports. A test with the recorder asks for
  `recorder_mock` before `hass`, and for `enable_custom_integrations` itself (`tests/conftest.py` explains why);
  `tests/test_calibration_runtime.py` writes a fixture into the recorder at its own times with `freezer`.
- `tests/test_calibration.py` has a test per calibration scenario, named after it, and the closure rules: the
  exclusions, the counter lag, the in-run draws. A model with known parameters generates a month of history and the
  fitter has to find them again within 5 %. `tests/test_setup_fit.py` runs the setup fit on the `week` fixture.
- `scripts/backtest.py` runs the setup fit and the comparison with the given options on a fixture or a history export
  (usage in `docs/model.md`). The package `__init__` imports Home Assistant, so the script does not import the package.
  It registers the folder of the pure modules as a package of its own (`hwte_pure`) and imports `const`, `model`,
  `calibration` and `setup_fit` from it, so no Home Assistant and no package is needed. Those modules need Python 3.14
  (the annotations in `model.py` and `calibration.py` refer to their own class, which 3.14 evaluates lazily), so unlike
  `history.py` and `anonymise.py` it does not run under the system Python 3.13. It is run with `uv run --no-project
  scripts/backtest.py`, which picks 3.14 from `.python-version`, and exits with that command in its message on an older
  Python. The script itself has no syntax newer than 3.13. `tests/test_backtest.py` loads it by path and checks that it
  fits the same parameters as `setup_fit` and that its shower list, sample list and litre totals are right.

## Private data

- `private/installation.md` holds the development installation's entity IDs, calibration evidence and results.
- `private/history/` holds raw recorder exports. The recorder keeps only 30 days, so export what may be needed as
  evidence.
- `private/analysis/` holds analysis scripts and their outputs.
- Scripts read the Home Assistant token from `%USERPROFILE%\.ha_token` themselves. Never read or print it in a
  session.
