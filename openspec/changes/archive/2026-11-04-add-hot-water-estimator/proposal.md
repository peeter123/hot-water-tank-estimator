# Proposal

## Why

A domestic hot water tank usually has one temperature sensor and no flow meter of its own, so Home Assistant
cannot say how much hot water is left. That matters most when reheating is blocked or slow, for example during an
evening price block on a heat pump. On the development installation, evening showers of 240-360 L ran a 285 L tank
down to 22-28 C at its sensor five times in October 2026, with no warning beforehand.

The tank sensor alone is a poor gauge. On that installation it sits a little above halfway, and showers of 95-150 L
did not move it at all. It only starts falling when the cold layer from below reaches it, and then it falls fast.
Most homes do have a whole-house water meter and the heater's energy counter, often also the heater's flow and
return temperatures and a bathroom humidity sensor. Together these allow an energy balance of the tank, and the
sensor's known height turns its reading into a measurement of how far the cold layer has risen.

## What Changes

- A new HACS custom integration, `hot_water_tank_estimator` ("Hot Water Tank Estimator"), set up from the UI. Each
  config entry models one tank.
- A two-layer energy balance model of the tank. It keeps two values: the tank's average temperature, and the
  charged temperature of its hot layer. From these follows the fraction of the tank that is cold.
  - Water drawn takes energy out. A shower or bath is mixed water, so the house meter's litres take
    `litres * (T_mix - T_cold)`. Other draws take a configured hot share of their litres at the charged
    temperature.
  - Heat from the heater's energy counter, or from its heat power, puts energy in. An optional start-up energy per
    run is subtracted.
  - Standing loss cools both values slowly.
  - At the end of each heating run the tank is charged. Both values are set to the charged temperature: the mean of
    the heater's flow and return temperature, or the tank sensor when those are not configured.
  - The tank sensor's height (20-80 % of the tank, default 50 %) and a thermocline width turn its reading into
    bounds on the cold fraction. While the sensor still reads the charged temperature, the cold layer is below it.
    Once it falls, its reading places the thermocline.
- Shower and bath detection from a rise in bathroom humidity. Litres drawn just before detection are reclassified.
  An optional long-draw rule covers homes without a humidity sensor.
- Sensors:
  - hot water remaining (L), litres of tank water at the charged temperature that can still be drawn (the model's
    "tank water remaining");
  - shower water remaining (L), the litres of mixed water at the shower mix temperature those make;
  - charge level, the model's percent charged against the last charge;
  - shower minutes left;
  - charged temperature;
  - estimated tank average temperature;
  - cold water temperature in use (a seasonal curve, or a sensor).
- A shower detected binary sensor, an action to set the tank state by hand, and diagnostics.
- Self-calibration, so that every installation gets values for its own house. The development installation's
  values are only the starting defaults. They were fitted to 30 days of its history (26 heating runs, 25 periods
  between runs, 13 showers, 28 quiet nights).
  - At setup, and through a `recalibrate` action, the model replays up to 30 days of the entry's recorder history.
    From it, it fits the other-draws hot share, the start-up energy, the loss coefficient and the thermocline
    width.
  - At every heating run end, the run's energy gives the true tank average at its start. The difference from the
    model refines the hot share, the start-up energy and the loss coefficient, within bounds and after enough
    samples.
  - The first sensor drop after each charge refines the thermocline width.
  - A "Shower ran cold" button sets the usable fraction.
  - Diagnostic sensors show each parameter in use and its source, the calibration samples, and the last and mean
    charge error.
  - An options flow sets the starting values and can lock any learned parameter.
- A pure Python model module with unit tests. Replay tests cover several anonymised scenarios from that history,
  and a backtest script replays Home Assistant history to tune the parameters.
- Documentation and packaging:
  - README with install, configuration, model explanation and tuning;
  - `docs/model.md` and `docs/development.md`;
  - `hacs.json` and GitHub Actions (hassfest, HACS validation, lint, tests).
- Rollout on the development installation: deploy, set up the config entry, and add a hot water block to its
  heating dashboard.

## Capabilities

### New Capabilities

- `tank-model`: the two-layer energy balance of the tank, covering:
  - the updates from water drawn, heat added and standing loss;
  - charging at the end of a heating run;
  - bounds from the tank sensor's height;
  - the cold water temperature;
  - the derived outputs: tank water litres, shower litres, percent charged and shower minutes.
- `draw-classification`: deciding which litres from the house water meter are mixed shower or bath water and which
  are other draws, covering:
  - meter deltas;
  - sessions;
  - humidity detection;
  - the long-draw rule;
  - reclassification at detection.
- `calibration`: fitting each tank's parameters, covering:
  - the setup fit from recorder history and the recalibrate action;
  - learning from charge closures and quiet windows;
  - the width from the first sensor drop;
  - the cold-shower button;
  - bounds, locks and persistence;
  - the diagnostic sensors.
- `integration-setup`: how a user adds and tunes a tank, covering:
  - the config and options flows and their validation;
  - the defaults;
  - the entities and their units;
  - the set-state action;
  - restoring the model after a restart;
  - how unavailable sources and counter resets are handled;
  - diagnostics.
- `packaging`: how the integration is distributed, documented and checked: HACS metadata, the manifest, README and
  docs, the lint and test tooling, CI and the release.

### Modified Capabilities

None. The repository has no specs yet.

## Live Home Assistant changes

Each needs the user's explicit authorization when its task runs.

| Change | Verify | Roll back |
|---|---|---|
| A deploy mapping for the integration folder in the author's config workspace, then a restart | The integration can be added | Remove the folder and restart |
| One config entry | The entity states, and the diagnostics events across a shower and a heating run | Remove the entry |
| A hot water block on the heating dashboard | A dashboard search finds the new cards | Remove the cards |

No existing entity, automation or card changes behaviour.

## Out of scope

- **Tagging and publishing the first release** (`v0.1.0`). The packaging capability defines what a release must
  meet, but the release itself moved on 2026-11-04 to `add-tank-insights-and-controls` (group 8), so that it
  includes that change.
- **Acting on the estimate**, such as a phone warning when hot water runs low during a price block, or releasing a
  block or starting a heating run. The first version only displays. Follow-up change:
  `add-low-hot-water-actions`.
- **Learning the sensor height.** The user enters it from the data sheet. The calibration error sensors show a
  wrong height as a steady bias. Follow-up if needed: `add-sensor-height-learning`.
- **Learning the usable fraction without user feedback**, for example from a drop in shower flow or bathroom
  temperature. Follow-up: `add-cold-shower-detection`.
- **More than one tank sensor**, or a temperature probe on the hot outlet, and **tanks heated high up** (a coil or
  element in the upper part), where charging does not mix the water below the heat source. A coil low in the tank
  is in scope: convection mixes the water above it. Follow-up: `add-multi-sensor-tanks`.
- **A Lovelace card.** The README shows stock cards.
- **Further sensors and controls from the user's review of the live rollout (2026-11-03).** Follow-up change
  `add-tank-insights-and-controls`:
  - a standing heat loss sensor in W (`k * C * (T_avg - T_ambient)`);
  - an optional ambient temperature sensor instead of the fixed ambient temperature, for loss and its learning;
  - recovery from a "Shower ran cold" press made by mistake: an undo for a limited time, and a guard that ignores a
    press without a recent shower;
  - the shower flow learned from detected showers, with a number entity to override it;
  - an electric heating element in the tank as a second heat source, which heats only the water above it.

## Impact

- New repository `hot-water-tank-estimator`:
  - code in `custom_components/hot_water_tank_estimator/`;
  - tests in `tests/`;
  - tooling in `scripts/`;
  - docs in `docs/`;
  - private evidence in the git-ignored `private/`.

  It is published on GitHub for HACS once the user authorizes it.
- Dependencies: Home Assistant core only, with no third-party Python packages at runtime. Development uses pinned
  `ruff` and `pytest-homeassistant-custom-component`.
- Development installation: see Live Home Assistant changes.
