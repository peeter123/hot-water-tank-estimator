# Proposal

## Why

The estimate goes wrong in four quiet ways, and nothing tells the user:
- **A source that fails is not reported.** Only the diagnostics show whether a source is available. A humidity
  sensor that goes silent (no reports, still "available") stops shower detection. On the development installation
  the shower of 2026-10-10, a 10.2-minute draw, ran during a 3.7-hour silence and was counted as an other draw.
  Since `improve-shower-end-detection` the long-draw rule applies only without a humidity sensor, so there is no
  backup.
- **Every heating run charges the model, however short.** A run cut off after a few minutes, for example by a
  cooling demand with a higher priority, resets the estimate to full although it did not mix the tank.
- **Heat put into the tank outside a heating run is dropped.** A heat pump can dump the heat of cooling into the
  tank with DHW demand off. In June 2026 the counter of the development installation rose by 8.1 kWh in one
  morning, about 24 K of T_avg.
- **A reload loses the calibrator's open windows.** Every options save or restart during a quiet night, or before
  the first sensor drop after a charge, loses that loss or width estimate.

This is the backlog item `harden-sources-and-heat-input`, agreed with the user on 2026-11-05. It replaces
`add-source-health-repairs` and two follow-ups of the first change's review. It changes the shower start rules, so it
waited until `improve-shower-end-detection` was archived (2026-11-06).

## What Changes

- **Repair issues for sources that stay unavailable.** One repair issue per source entity that has been unavailable
  or non-numeric for longer than its threshold. The issue names the entity, the tank and what the estimate loses
  without it. It is removed on its own when the source is back. Thresholds:
  - water meter, energy counter, power and heating detector: 30 min;
  - tank sensor: 1 h;
  - humidity: 2 h;
  - flow and return, cold water and ambient: 3 h.

  The quality-scale rule `repair-issues` becomes done.
- **A silent humidity sensor counts as unavailable.** A new option, "humidity silence time" (default 2 h, 0 turns it
  off for a sensor that reports only on change), sets how long a humidity sensor may go without any report.
- **Detection backup.** While every humidity sensor is unavailable or silent, a draw session of the next shower time
  starts a shower, as in the humid bathroom after a shower. "Shower detected" stays available, and the repair issue
  says that detection is degraded. The "Draw counts as shower" countdown follows the backup.
- **Short runs do not charge.** A heating run shorter than 15 minutes adds its heat, after the start-up energy, but
  does not set the tank to the charged temperature. The next closure, whose interval holds that run, is excluded
  from learning.
- **Heat outside a run counts.** An energy counter increase while no run is active, beyond the counter lag, raises
  T_avg by its energy. It adds no charge and uses no start-up energy. With a heat power sensor and a separate
  heating detector, power above the power threshold counts the same way. The closure equation gains this heat as a
  known input, so such intervals still count for learning. With counter-only or power-only heating detection this
  heat starts a run instead; the README says that it needs a separate heating detector.
- **The calibrator keeps its open windows.** The open quiet window (loss) and the armed first drop (thermocline
  width) are saved with the calibration state. A store without them still loads.
- **Docs.** The README (options, repair issues, troubleshooting, limitations, supported heat sources) and
  `docs/model.md` (heat input, charging, sensor bounds, closure, draw classification) describe the new rules with
  their evidence.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `tank-model`:
  - "A tank is charged at the end of a heating run": only a run of at least 15 minutes;
  - "Sensor above the charged temperature raises it": it does not count heat outside a run twice;
  - new requirements for a short run's heat and for heat outside a run.
- `draw-classification`: new requirements for a silent humidity sensor and for the detection backup.
- `calibration`:
  - "Charge closure measures the error since the previous charge": the heat outside runs is stored with the sums
    and enters the closure;
  - "Calibration state persists": the open quiet window and the armed first drop;
  - a new requirement that an interval holding a short run is excluded.
- `integration-setup`:
  - "Draw and heat defaults": the humidity silence time;
  - "State survives a restart": the time of each humidity sensor's last report;
  - "Diagnostics": the silent humidity sensors, the open repair issues and the new event kinds;
  - "Shower countdown diagnostic sensors": "Draw counts as shower" during the backup;
  - a new requirement for the repair issues.

## Impact

- **Code:**
  - `model.py`: the short run, the heat outside a run with its interval sum, the credit in the raise rule, the
    humidity reports and the saved state;
  - `classification.py`: the backup trigger;
  - `calibration.py`: the heat term, the new exclusion reason and the saved windows;
  - `estimator.py`: feeding `last_reported` on the tick, and the repair issues;
  - `__init__.py`: removing the issues on unload and removal;
  - also `const.py`, `config_flow.py`, `diagnostics.py`, `strings.json`, the translations and
    `quality_scale.yaml`.
- **Tests:**
  - model and calibration tests for the short run and the heat outside a run, with a synthetic day shaped like
    2026-06-24;
  - a reload test for the calibrator windows;
  - classifier and model tests for the silence and the backup;
  - runtime tests for the repair issues and for `last_reported`;
  - the options-flow and diagnostics tests.
- **Evidence:**
  - recorded in `private/installation.md` on 2026-11-06: the October and November exports (31 runs, the shortest
    43.5 min; no counter increase outside a run; 2 humidity gaps of at least 2 h; source outages) and the June
    cooling statistics;
  - a backtest of the October export: the 10.2-minute shower of 2026-10-10 counts as mixed, and the other results
    stay the same or are explained.
- **Docs:** `README.md`, `docs/model.md`, `private/installation.md` and `openspec/backlog.md`.
- **Live Home Assistant (the development installation), each step only with the user's authorization:**
  - deploy and restart. Verify:
    - the entry loads and the state is kept;
    - the options form shows the humidity silence time at 2 h;
    - the Repairs list has no issue of the integration while every source is available;
    - the diagnostics show the humidity sensor's last report;
    - the system log is clean.

    Roll back by deploying the previous commit and restarting. A repair issue the new code raised goes away with the
    restart, because the issues are not persistent;
  - a live check of the backup and the humidity repair issue at the next humidity silence of at least 2 h, from the
    diagnostics and the Repairs list. Nothing to roll back; a failure is a finding.

## Out of scope

- **The live check of heat outside a run in the cooling season, and the heat pump's counter during cooling.** The
  DHW demand history of June is purged, and no cooling runs before next summer. It goes back to the backlog as a
  carried-over live check. The check that the firmware's DHW counter during cooling matches the heat that reaches the
  tank is outside this project.
- **A warning for a sensor other than humidity that stays available but stops changing**, and watching a device's
  battery entity. No evidence that it happens on the other sources; no follow-up planned.
- **Persistent repair issues across restarts.** After a Home Assistant restart an unavailable source's outage starts
  again from the restart, because the state's `last_changed` restarts. No follow-up planned.
- **Telling heat outside a run from a run with counter-only or power-only heating detection.** It needs a separate
  heating detector; no follow-up planned.
- **A release.** Tagging a new version is a separate decision of the user after this change.
