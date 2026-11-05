# Proposal

## Why

A detected shower lasts until the bathroom humidity has dried most of the way. On the development installation that
is a median of 36 minutes, and up to 59, after the water stops. In October, 44 draw sessions in that tail counted as
mixed, and "Shower time remaining" kept the finished shower's flow. Two showers 5-6 minutes apart made one shower
flow sample, and a humidity rise with almost no water held detection for up to an hour. The bathroom temperature
cannot end a shower sooner: it peaks 2-25 minutes after the water stops, and its sensor reports about every 15
minutes. The water meter is the only source that sees the end quickly. This is the backlog item
`improve-shower-end-detection`, explored with the user on 2026-11-05.

## What Changes

- **The water ends a shower.** A detected shower ends once no water has been drawn for the shower end time (new
  tuning option, default 5 minutes). It is no longer ended by the humidity falling. A pause of up to 3 minutes stays
  one shower, and the start no longer flickers off when the humidity reading dips while the water runs.
- **Another shower while the bathroom is still humid.** After a shower has ended, while the humidity still holds
  (at least half the rise above its window minimum), a draw session that lasts the next shower time (new tuning
  option, default 5 minutes) is a new shower. Its session's litres are reclassified as mixed, as at detection.
  Shorter draws, such as the cold washbasin, stay other draws.
- **The long-draw rule only applies without a humidity sensor.** **BREAKING** for an entry that has both: its long
  draws no longer count as showers unless the humidity rises. The user accepted this on 2026-11-05: on the
  development installation a 14-minute garden hose draw would have counted as a shower. A long-draw shower also
  ends by the shower end time, so a pause in it no longer ends it.
- **The shower detected binary sensor means "a shower is in progress"**, from the start of detection to the shower
  end. It is no longer on through the humidity tail. The user agreed on 2026-11-05.
- **Shower flow samples** follow from the new end: a shower is reported when the water has stopped for the shower
  end time, and two showers separated by more than that are two samples.
- **Clearer names for the two options, and four diagnostic sensors.** The options are labelled "Shower end after no
  water" (the shower end time) and "New shower draw while humid" (the next shower time), and two diagnostic sensors
  with the same names show the values in use, in minutes. Two diagnostic timestamp sensors, "Shower ends" and "Draw
  counts as shower", count down to the end of the shower in progress and to the moment a running draw becomes a
  shower. Asked by the user on 2026-11-05, after the live check.
- **Docs.** The README options, entities, troubleshooting and limitations, and `docs/model.md` (draw
  classification, shower flow) describe the new rules with the evidence.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `draw-classification`:
  - "Shower detection from bathroom humidity": humidity starts a shower; the water ends it; the humidity hold only
    allows another shower;
  - "Long draws count as a shower": only without a humidity sensor, and ended by the shower end time;
  - "Shower detection is exposed": the binary sensor follows the shower in progress;
  - a new requirement for another shower while the bathroom is still humid.
- `integration-setup`:
  - "Draw and heat defaults": the shower end time and the next shower time;
  - "State survives a restart": the classifier state, including a shower that has ended while the bathroom is
    still humid;
  - "Entities and units": the four diagnostic sensors, and two new requirements for them.

## Impact

- **Code:** `classification.py` (the shower states, the end rule, the next-shower rule, the long-draw gate, the
  saved state), `model.py` (the options and the time of the next shower end), `estimator.py` (a timer for the shower
  end between ticks), `const.py`, `config_flow.py`, `sensor.py` (the four diagnostic sensors), `strings.json` and
  the translations.
- **Tests:** `tests/test_classification.py`, the model, options-flow and replay tests (the `back_to_back` fixture),
  and a test that the end timer fires between ticks.
- **Evidence:** a replay of the October export and of the November history still in the recorder (export it to
  `private/history/` first), against the current rule: shower starts and ends, litres classified as mixed, shower
  flow samples and the charge errors from `scripts/backtest.py`. Results go to `private/installation.md`.
- **Docs:** `README.md` and `docs/model.md`.
- **Live Home Assistant (the development installation), each step only with the user's authorization:**
  - deploy and restart. Verify that the entry loads, the state is kept, the options form shows the two new
    options at their defaults, and the system log is clean. Roll back by deploying the previous commit and
    restarting;
  - live check at the next shower: detection ends about 5 minutes after the water stops, a washbasin draw after
    it stays an other draw, and the shower flow sample is added at the end. Verify through the history of the
    binary sensor and the diagnostics. Nothing to roll back; a failure is a finding for the review.

## Out of scope

- **A long-draw backup while the humidity sensor is unavailable** (the shower of 2026-10-10, during an hour without
  humidity readings). It goes to the backlog item `add-source-health-repairs`, which detects the outage.
- **Missed reclassification when humidity rises after the session has ended** (a short shower whose humidity
  rises more than the session gap after the water stopped). It is existing behaviour; no follow-up planned unless
  the replays show it matters.
- **The bathroom temperature as a detection source.** The October data shows it is too slow; no follow-up planned.
- **A release.** Tagging a new version is a separate decision of the user after this change.
