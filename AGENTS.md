# Hot Water Tank Estimator

A Home Assistant custom integration that estimates the hot water left in a domestic hot water tank without a tank
flow meter. It is generic and published for HACS. It is developed against one live installation, whose details live
only in the git-ignored `private/` folder.

- Code: `custom_components/hot_water_tank_estimator/`. `model.py` is pure Python with no Home Assistant imports, so
  unit tests and `scripts/backtest.py` can run it directly.
- Tests: `tests/`, using pytest and `pytest-homeassistant-custom-component`. Fixtures use made-up entity IDs.
- Check everything with `python scripts/lint.py` once it exists (ruff, Markdown format, tests). Pinned tool
  versions and architecture rules are in `docs/development.md`.
- Planning: OpenSpec in `openspec/`. When applying a change, follow "Implementation workflow" and "Review loop" in
  `openspec/config.yaml`:
  - the main session only briefs and reviews;
  - one Sonnet subagent (`model: "sonnet"`, never a fork) implements each task group;
  - a read-only Opus subagent (`model: "opus"`) reviews it;
  - after a clean review the group gets its own commit (explicit paths, no push). That rule is the standing
    authorization for those commits only.
- Live Home Assistant changes (deploy, restart, config entries, dashboards) need the user's explicit
  authorization. Do them through the home-assistant MCP server or the deploy script in the author's config
  workspace (`scripts/deploy.ps1` there; its path is in `private/installation.md`), never by copying files by hand.
- Never read or print `%USERPROFILE%\.ha_token`. Scripts read it themselves.
- Plain text only in names, labels and UI strings: no emoji.

## Vocabulary

- **Charged:** the state at the end of a heating run. The run has mixed the tank above the heat source (by
  circulation, or by convection above a coil low in the tank), so the model counts all of it at the **charged
  temperature**: the mean of the heater's flow and return temperature just before the run ends (the tank sensor if
  those are not configured). This holds whether or not the run reached the setpoint. The colder water below a low
  coil is carried by the start-up energy (energy) and the usable fraction (litres).
- **Tank water litres:** litres of tank water at the charged temperature that can still be drawn before the outlet
  runs cold.
- **Shower litres:** litres of mixed water at the shower mix temperature that the tank water still makes, after
  mixing with cold water.
- **Mixed draw:** water drawn through a thermostatic mixer. The house water meter counts both the hot and the cold
  part, so the model takes `litres * (T_mix - T_cold)` of energy from the tank.

## Documentation

`docs/README.md` is the entry point once it exists (doc map, link to `docs/model.md` and `docs/development.md`).
Keep the docs up to date: after any new learning (backtest, live check, history analysis), check and update them in
the same change and group.

- Formulas, defaults and the reasons for them go to `docs/model.md`, without installation-specific entity IDs.
- User-facing setup, options, entities and tuning go to `README.md`.
- Tooling, pinned versions and architecture rules go to `docs/development.md`.
- Installation-specific facts go to `private/installation.md`:
  - entity IDs;
  - calibration evidence and backtest results, with dates;
  - the deploy mapping and dashboard placement.

  Raw recorder exports go to `private/history/<from>_<to>/`, and analysis scripts with their outputs go to
  `private/analysis/`. The recorder keeps only 30 days, so export history before it is purged when it is needed
  as evidence.
- No line-number citations. Remove superseded text instead of leaving it beside the new text.
