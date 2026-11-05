# Backlog

Follow-up changes that are agreed but not yet proposed. Each one becomes an OpenSpec change (`/opsx:propose`)
when it is taken up. Installation-specific evidence stays in `private/installation.md`; the items here only point
to it.

## add-source-health-repairs

Added 2026-11-03 at the user's request. The trigger is a battery-powered humidity sensor: on the development
installation its battery was at 30 % on 2026-10-31.

**Problem.** A source that goes unavailable is handled quietly, and nothing tells the user.
- **Humidity sensor.** Its readings are dropped, so humidity detection never starts. "Shower detected" stays off
  instead of showing that detection is not working. Every shower then counts as an other draw at the other-draws hot
  share instead of as a mixed draw.
  - The 70 L shower of 2026-11-03 would then have cost 70 * 0.16 * 43.5 / 285 = 1.7 K instead of 6.0 K.
  - The tank average is then about 4.3 K too high, or about 4.3 * 285 / 43.5 = 28 L of tank water, until the next
    charge or a sensor bound corrects it.
  - The shower flow history also stops filling.
- **The other sources.** The tank sensor, the meter, the heat inputs, flow and return, cold water and ambient each
  have their own fallback:
  - a closure is excluded when a source was unavailable for more than 10 % of the interval;
  - the ambient sensor falls back after 3 hours;
  - an unavailable heating detector holds its state for 15 minutes.

  Only the diagnostics show whether each source is available.

**What to build.**
- A repair issue per source that has been unavailable for longer than a threshold. It names the entity and what the
  estimate loses without it. It is removed on its own when the source is back.
- A threshold per kind of source. For example, a short one for the water meter and the tank sensor, and hours for a
  battery-powered humidity or ambient sensor. Short dropouts must not raise an issue: the tank sensor goes
  unavailable for 1-2 s now and then.
- "Shower detected" unavailable while no detection method works, that is, every humidity sensor is unavailable and
  the long-draw rule is off. Today it is unavailable only when no method is configured.
- A long-draw backup while the humidity sensor is unavailable. `improve-shower-end-detection` makes the long-draw
  duration apply only without a humidity sensor, so a configured sensor that is unavailable has no backup. In
  October the shower of 2026-10-10 (a 10.2-minute draw) ran during an hour without humidity readings and was counted
  as an other draw. Option: while every humidity sensor is unavailable, start a shower on a session of the long-draw
  duration, as without a sensor, and drop the backup when a reading returns.
- To decide: also a warning for a sensor that stays available but stops changing, for a device that keeps its last
  value. And whether to watch the device's battery entity, if there is one.
- The quality-scale rule `repair-issues` (todo since 0.1.0) then becomes done.

**Evidence needed.**
- Recorder history of real outages per source, to set the thresholds.
- A backtest of an estimate with the humidity sensor removed for a few days, to measure the error that the repair
  warns about.

## Live check carried over: heat loss follows the ambient sensor

This check was moved out of `add-tank-insights-and-controls` (task 5.4) at the user's request on 2026-11-03. Over a
few days with a changing room temperature, check that the "Heat loss" sensor follows
`k * C * (T_avg - T_ambient)` with the ambient sensor's reading, and that it falls back to the configured ambient
temperature after a long sensor outage. Record the result in `private/installation.md`. It can be done
in any later change that touches the loss model, or on its own.

## add-second-heat-source

From `add-tank-insights-and-controls` (proposal, Out of scope).
- A second heat source, such as an electric element, heats only the water above it. It needs a model with two zones,
  and evidence from a tank that has one.
- The development installation has no element.

## Small follow-ups from the whole-change review of add-hot-water-estimator

Added 2026-11-04, from the review before that change was archived. Neither is blocking; they are kept here so they
are not lost.

- **Persist the calibrator's open windows.** The armed first-drop state (thermocline width) and the open quiet
  window (loss) are not stored. A reload, including every options save, between a charge and the first sensor drop
  loses that width estimate, and a reload during a quiet night loses that loss estimate. Store both with the
  calibration state, and test that a reload keeps them.
- **Guard the fixtures against real entity IDs.** The packaging scenarios "Fixture from real history" and
  "Markdown with CRLF" were verified once by hand (tasks 3.2 and 1.3). Add tests: one that every entity ID in
  `tests/fixtures/` is one of the made-up IDs, and one that the Markdown check rejects a CRLF file.
- **Short heating runs charge the model.** Every heating run ends with T_avg = T_ch = the charged temperature,
  however short. Calibration already ignores runs under 15 minutes, because a short run does not mix the tank. A
  2-minute demand blip on a 40 %-drawn tank resets the estimate to full, and while the sensor still reads the hot
  layer nothing corrects it until the cold layer reaches the sensor or a real run ends. Option: no charge for runs
  shorter than a minimum (15 minutes, as for closures), with the heat counted as energy only. Evidence needed: how
  often short runs occur in the recorder history, and a backtest. Decided as a backlog item by the user on
  2026-11-04.

## Manifest categories, after the next Home Assistant release

Added 2026-11-04 at the user's request, taken out of `add-tank-insights-and-controls` (it was task 8.1 there).

- **Why.** The first CI run on GitHub (2026-11-04) had the HACS action warn "The integration manifest has no
  categories". The user chose `"categories": ["climate.water_heaters", "helpers.calculate_value"]` (1-3 values from
  https://contributors.home-assistant.io/core/integrations/categories/).
- **Why not yet.** hassfest in Home Assistant 2026.10.4, the version the test pin
  (`pytest-homeassistant-custom-component` 0.13.375) targets and the runner builds hassfest from, rejects the key:
  "Invalid manifest: not a valid option at 'categories'". The 2026.11 release candidate (2026.11.0b5) and the dev
  branch accept it; CI's `hassfest@master` would too. Home Assistant 2026.10 does not validate the manifest at
  runtime, so the key is harmless for older versions.
- **Steps, once a Home Assistant release accepts the key and a matching
  `pytest-homeassistant-custom-component` exists:**
  1. Bump the test pin in `requirements_test.txt` and the pin table in `docs/development.md`.
  2. Rebuild the remote test runner image, so hassfest comes from the new release tag.
  3. Add the categories to the manifest in hassfest's key order, with a check in `tests/test_manifest.py`, and add
     them to the packaging spec's "Installable through HACS" requirement (a MODIFIED delta).
  4. Verify with `python scripts/lint.py --hassfest`, and after a push the HACS action no longer warns.
