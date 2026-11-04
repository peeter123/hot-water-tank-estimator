# Proposal

## Why

The user reviewed the first live rollout of the estimator on 2026-11-03 and asked for more insight and safer controls.
- **Standing loss.** It is learned, but not shown as the power it costs.
- **Ambient temperature.** It is a fixed 20 C, so the learned loss coefficient absorbs seasonal swings of the room
  around the tank.
- **The "Shower ran cold" button.** One mistaken press resets the usable fraction and empties the tank estimate,
  with no way back. Its name does not fit a tap that runs cold, which is the same evidence.
- **Shower minutes.** They use one fixed shower flow, which is wrong for a household where people shower at different
  flows, such as one person with a rain head.

## What Changes

- **Heat loss sensor.** A new sensor gives the standing heat loss in W, `k * C * (T_avg - T_ambient)`.
- **Ambient temperature sensor.** It is an optional source and replaces the fixed ambient temperature for loss, for
  quiet-window loss learning and for the setup fit's replay.
  - When the sensor is unavailable for too long, the fixed option applies again.
  - Adding or removing the sensor starts a recalibration, because the learned loss coefficient depends on it.
  - The history export and the backtest carry the sensor.
- **"Hot water ran out" replaces "Shower ran cold"**, and counts for any tap or shower that runs cold. **BREAKING**
  (development only): the button's key, and so its entity ID, change. The user accepted this on 2026-11-03.
  - **Timing.** A press applies to the model as it was when the last draw ended, up to 20 minutes before the press.
    That leaves time to leave the shower and reach a phone. Heat added since then is kept.
  - **Rejected presses.** A press is ignored if no draw ended in the last 20 minutes, or if the tank sensor still
    read hot at the end of that draw. In both cases a notification says why.
  - **Undo.** A new "Undo hot water ran out" button reverses the last accepted press until the next charge: the
    usable fraction comes back and the tank average drop is added back. After that charge, it restores the usable
    fraction only, for 24 hours. The button is unavailable when there is nothing to undo.
- **Shower flow is learned** from each detected shower: litres per minute of actual flow.
  - Shower minutes use the median of the last 10 showers, and attributes give the minutes at the lowest and highest
    of those flows.
  - During a shower, the minutes use that shower's own rolling flow over its last 2 minutes of flow, so whoever is
    showering sees the minutes at their own flow.
  - A "Shower flow" number entity shows the flow in use. Setting it locks the learned flow. The `shower_flow` tuning
    option is replaced by that lock.
  - A "Shower flow locked" switch shows the lock and turns it on or off next to the number, so the way back to the
    learned flow does not go through the options. Added at the user's request after the rollout review on
    2026-11-03.
- **Tank sensor temperature.** A diagnostic sensor shows the tank sensor reading as the model receives it. It has
  the source entity and the sensor height as attributes, so the device page links directly to the source data.
  Added at the user's request on 2026-11-03.
- **Docs.** The README and `docs/model.md` describe all of the above. They also note that a high-flow shower can make
  a tank run cold a little earlier, which the model does not represent.

## Capabilities

### New Capabilities

None. Every change extends an existing capability.

### Modified Capabilities

These capabilities are added by `add-hot-water-estimator`, which must be archived first, so that they exist under
`openspec/specs/`.
- `tank-model`:
  - standing loss uses the ambient sensor when there is one;
  - a new heat loss output;
  - shower minutes from the learned shower flow, with a range.
- `calibration`:
  - the cold-shower requirement becomes "Hot water ran out", with the press timing, the checks, the notification and
    undo;
  - quiet-window loss learning uses the ambient in use;
  - the shower flow becomes a learned parameter, with its bounds and lock;
  - the setup fit replays the ambient sensor.
- `draw-classification`:
  - a detected shower reports its own flow, for shower flow learning, and its rolling flow while it runs;
  - the end of the last draw is kept, for the "Hot water ran out" press.
- `integration-setup`:
  - the ambient sensor is an optional source, in the config flow, the options and reconfigure;
  - the entities: the heat loss sensor, the renamed button, the undo button, the shower flow number, the "Shower flow
    locked" switch and the "Tank sensor temperature" diagnostic sensor;
  - the `shower_flow` option is replaced by its lock;
  - the defaults: the ambient fallback time;
  - the restored state: the last draw end, the last reset, the shower in progress and the last ambient reading;
  - the diagnostics: the new event kinds, the shower flow history and the undo record.

## Impact

- **Code:**
  - `model.py`: ambient in loss, the heat loss output, the state at the last draw end, the shower flow history and
    the minutes range;
  - `calibration.py`: the press, undo, the ambient in quiet windows, the shower flow learning, the setup fit replay;
  - `estimator.py` and `button.py`;
  - a new `number.py` and a new `switch.py`, and the tank sensor temperature in `sensor.py`;
  - `sensor.py`, `config_flow.py`, `const.py`, the strings and translations, `icons.json`, `diagnostics.py`;
  - `scripts/backtest.py`, for the ambient sensor. `scripts/history.py` needs no change, because its roles are
    generic (D8).
- **Tests:** the model, calibration, button, number, switch, entity and options-flow tests, the replay fixtures where
  the ambient matters, and the backtest.
- **Docs:** the README (entities, options, tuning, limitations, the dashboard example) and `docs/model.md` (the heat
  loss formula, the ambient fallback, the press rules, the shower flow learning).
- **Live Home Assistant (the development installation), each step only with the user's authorization:**
  - deploy and restart. Verify that the entry loads, the state is kept, and the new entities exist. Roll back by
    deploying the previous commit and restarting;
  - add the basement air temperature sensor as the ambient source through the options flow. Verify that the
    recalibration runs and the loss coefficient stays within its bounds. Roll back by removing the source in the
    options;
  - point the dashboard at the renamed button, and add the heat loss and shower flow entities, with a targeted
    dashboard transform. Verify with a dashboard search. Roll back by reversing the transform;
  - remove the old "Shower ran cold" button's orphaned registry entry after the first deploy. Verify that a lookup
    finds no entity. There is no rollback, because the entity is gone from the integration;
  - deploy and restart for the lock switch (group 6). Verify that the switch exists and locks and unlocks the number.
    Add its tile to the dashboard, and verify with a dashboard search. Roll back by deploying the previous commit,
    restarting and removing the tile;
  - deploy and restart for the tank sensor temperature (group 7). Verify that the sensor is diagnostic, matches its
    source and names it. Roll back by deploying the previous commit and restarting.
- **Release (group 8, moved here from `add-hot-water-estimator` on 2026-11-04):** with the user's authorization, set
  the manifest version to 0.1.0, then tag and publish `v0.1.0` on GitHub. Verify that the workflows pass and that
  HACS shows the version. Roll back by deleting the release and the tag.

## Out of scope

- **A second heat source**, such as an electric element, which heats only the water above it. It needs a model with
  two zones and evidence from a tank that has one. It is in `openspec/backlog.md` as the follow-up change
  `add-second-heat-source`. The development installation has no element.
- **Named shower profiles per person**, for example two flow numbers with their own minutes sensors. The minutes
  range covers the need without setup. They can be added later on top of the shower flow history.
- **A usable fraction that depends on the draw flow** (a fast draw mixes the cold inflow more). It is noted as a
  limitation in the docs, with no follow-up planned.
- **Repair issues.** A rejected press uses a notification, not a repair issue, so the quality-scale rule
  `repair-issues` stays todo.
