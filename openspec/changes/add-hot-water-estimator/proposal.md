# Proposal

## Why

A domestic hot water tank usually has one temperature sensor and no flow meter of its own, so Home Assistant
cannot say how much shower water is left. That matters most when reheating is blocked or slow, for example during
an evening price block on a heat pump. On the development installation, four showers in a row ran a full 281 L
tank down to 23 C at its sensor, and the house had no warning beforehand.

The tank sensor alone is a poor gauge. On that installation it sits low in the tank and hardly moves during the
first 100 L of a shower. Most homes do have a whole-house water meter, the heater's energy counter and a bathroom
humidity sensor. Together these allow an energy balance of the tank.

## What Changes

- A new HACS custom integration, `hot_water_tank_estimator` ("Hot Water Tank Estimator"), set up from the UI. Each
  config entry models one tank.
- An energy balance model keeps the tank's average temperature:
  - Water drawn lowers it. The draw comes from a whole-house water meter and is weighted by whether a shower or
    bath is running.
  - Heat from the heater's thermal energy counter, or from its heat power, raises it.
  - Standing loss lowers it slowly.
  - At the end of each heating cycle it is anchored to the tank sensor. While the sensor reads lower than the model,
    the sensor caps it.
- Shower and bath detection from a rise in bathroom humidity. Other draws count as hot at a set share.
- Sensors:
  - Estimated tank average temperature.
  - Hot water remaining, as litres of water at the shower mix temperature.
  - Percent full.
  - Shower minutes left.
  - Cold water temperature in use: a seasonal curve, or a sensor if the user has one.
- A binary sensor for shower detection.
- An action to set the tank average by hand.
- Diagnostics.
- An options flow for the tuning values. Defaults come from calibration on the development installation.
- A pure Python model module with unit tests, a replay test on an anonymised shower fixture, and a backtest script
  that replays Home Assistant history to tune the parameters.
- A README with install, configuration, model explanation and tuning, plus `docs/model.md`, `hacs.json` and
  GitHub Actions (hassfest, HACS validation, ruff, pytest).
- Rollout on the development installation: deploy, set up the config entry, and add a hot water block to its
  heating dashboard.

## Capabilities

### New Capabilities

- `tank-model`: the energy balance of the tank, covering:
  - updates from water drawn, heat added and standing loss;
  - anchoring to and capping by the tank sensor;
  - the cold water temperature;
  - the derived outputs (litres at the mix temperature, percent, shower minutes).
- `draw-classification`: deciding how much of each litre drawn from the house water meter came out of the tank.
  This covers shower and bath detection from bathroom humidity and the share for other draws.
- `integration-setup`: how a user adds and tunes a tank, covering:
  - the config and options flows and their validation;
  - the entities and their units;
  - the set-average action;
  - restoring the model state after a restart;
  - how unavailable sources and counter resets are handled;
  - diagnostics.
- `packaging`: how the integration is distributed and documented: HACS metadata, the manifest, README and model
  documentation, CI validation and the release.

### Modified Capabilities

None. The repository has no specs yet.

## Out of scope

- **Acting on the estimate**, such as a phone warning when hot water runs low during a price block, or releasing a
  block or starting a heating cycle. The first version only displays. A follow-up change,
  `add-low-hot-water-actions`, can add a threshold binary sensor and blueprint once the estimate has proven itself.
- **Learning the tuning values automatically.** Examples are the usable floor temperature from showers that ran
  cold, the other-draws share from cycle-end errors, and the loss coefficient. For now the backtest script and the
  options flow cover tuning. Follow-up: `add-parameter-learning`.
- **More than one temperature sensor per tank**, to resolve stratification, and **tanks with a resistive backup
  heater that has its own energy meter**. The design keeps room for a second heat input. Follow-up:
  `add-multi-sensor-tanks`.
- **A Lovelace card.** The README shows how to use stock cards.

## Impact

- New repository `hot-water-tank-estimator`, with code in `custom_components/hot_water_tank_estimator/`, tests in
  `tests/`, tooling in `scripts/` and docs in `docs/`. It is published on GitHub for HACS.
- Dependencies: Home Assistant core only, no third-party Python packages at runtime. Development needs `pytest`,
  `pytest-homeassistant-custom-component` and `ruff`.
- Development installation:
  - The author's Home Assistant config workspace gets a deploy mapping for the integration folder. A Python
    change there needs a restart.
  - One config entry is added and a dashboard block is added.
  - No existing entity, automation or dashboard card changes behaviour.
