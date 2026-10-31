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

Home Assistant does not run on native Windows, so the pytest step depends on the platform (`pytest_command` in
`scripts/lint.py`, shared with the edit hook):
- Linux and macOS: pytest runs directly through `uv run`.
- Windows with a running Docker engine (Docker Desktop's Linux engine needs WSL): the same command runs in the
  `ghcr.io/astral-sh/uv:0.13.1-python3.14-trixie-slim` container, with the repository mounted and a `hwte-uv-cache`
  volume for the uv cache.
- Windows without Docker: pytest runs natively with the Home Assistant plugin disabled and prints a warning. Pure
  Python tests pass; tests that need Home Assistant fail, so lint exits 1.

After Docker becomes available, run `python scripts/lint.py` once to warm the uv cache volume: the first container
run can exceed the edit hook's timeout.

hassfest (manifest and integration checks) runs through Docker, locally and in CI, not in `scripts/lint.py`. Run it
from PowerShell, or prefix it with `MSYS_NO_PATHCONV=1` in Git Bash:

```sh
docker run --rm -v "$PWD:/github/workspace" ghcr.io/home-assistant/hassfest
```

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
| uv image (Windows with Docker) | `ghcr.io/astral-sh/uv:0.13.1-python3.14-trixie-slim` | `scripts/lint.py` |
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

- `model.py`, `classification.py` and `calibration.py` in `custom_components/hot_water_tank_estimator/` are pure
  Python: standard library only, no Home Assistant imports, and no I/O. They take timestamps and numbers and return
  state and events. Tests, the setup fit and `scripts/backtest.py` all run the same code.
- One `TankEstimator` per config entry, kept in `entry.runtime_data`. It owns the subscriptions
  (`async_track_state_change_event`, a 5-minute `async_track_time_interval`) and the model. Entities read from it
  through a dispatcher signal. There is no coordinator, because nothing is polled.
- Heavy work (the setup fit's history read and replay) runs in the recorder's executor and the default executor,
  never in the event loop.
- Model state persists in the tank average sensor's restore data, and calibration state in a `Store` per entry.
- All user-facing text lives in `strings.json` and `translations/en.json`. Plain text, no emoji.
- Formulas in code use the symbols of `docs/model.md` (`t_avg`, `t_ch`, `t_cold`, `f`, `h`, `w`, `u`) and give
  units in names or comments.

## Quality scale

Home Assistant's Integration Quality Scale is the checklist for integration code. The integration keeps a
`quality_scale.yaml` with the status of each rule (`done`, `todo` or `exempt` with a comment). hassfest does
not validate this file for custom integrations, so `tests/test_quality_scale.py` checks it against a copy of
hassfest's rule list. The target for the first release is Silver, plus these Gold rules that apply to a calculated
helper:
- diagnostics;
- entity translations and icon translations;
- entity categories and device classes;
- reconfiguration through the options flow;
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

## Private data

- `private/installation.md` holds the development installation's entity IDs, calibration evidence and results.
- `private/history/` holds raw recorder exports. The recorder keeps only 30 days, so export what may be needed as
  evidence.
- `private/analysis/` holds analysis scripts and their outputs.
- Scripts read the Home Assistant token from `%USERPROFILE%\.ha_token` themselves. Never read or print it in a
  session.
