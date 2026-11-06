# Backlog

Follow-up changes that are agreed but not yet proposed. Each one becomes an OpenSpec change (`/opsx:propose`)
when it is taken up. Installation-specific evidence stays in `private/installation.md`; the items here only point
to it.

## harden-sources-and-heat-input

Agreed 2026-11-05 in an exploration with the user. It replaces three earlier items: `add-source-health-repairs`
(2026-11-03), "Short heating runs charge the model" and "Persist the calibrator's open windows" (both 2026-11-04),
and adds heat put into the tank outside a heating run. Propose it after `improve-shower-end-detection` is archived:
it changes the shower start rules in `draw-classification`, so its delta must be written against the synced spec.

**Problem.**
- **A source that fails is handled quietly.** Only the diagnostics show whether a source is available. On the
  development installation the humidity sensor never went unavailable from 2026-10-01 to 2026-11-05: it went silent.
  The shower of 2026-10-10 (a 10.2-minute draw) ran during a 3.7-hour silence and was counted as an other draw.
  Since `improve-shower-end-detection` the long-draw rule applies only without a humidity sensor, so a silent or
  unavailable sensor has no backup.
- **Every heating run charges the model, however short.** A DHW run cut off after a few minutes, for example when a
  cooling demand with a higher priority takes the heat pump, resets T_avg = T_ch to the charged temperature although
  the run did not mix the tank. Calibration already excludes such a closure (`short_run`), but the next interval
  starts from that charge and its closure counts. None occurred in the 31 runs from 2026-10-01 to 2026-11-05 (the
  shortest ran 43.5 minutes); they are expected in the cooling season.
- **Heat outside a heating run is dropped.** A heat pump can dump the heat of cooling into the tank (high temperature
  recovery) with DHW demand off, up to its own setpoint. The model only applies heat while a run is active. In the
  hourly statistics of the development installation the DHW energy counter rose at about 1.2-1.7 kW during cooling:
  2.6 kWh on 2026-06-23 and about 8 kWh over 6 hours on 2026-06-24, about 24 K of T_avg on 285 L.
- **A reload loses the calibrator's open windows.** The open quiet window (loss) and the armed first drop
  (thermocline width) are not stored, so every options save or restart during a quiet night or before the first
  sensor drop loses that estimate.

**Decisions (2026-11-05).**
- **Repair issues per source**, created when the source has been unavailable for longer than its threshold, naming
  the entity and what the estimate loses, and removed when it returns: water meter, energy counter, power and heating
  detector 30 min; humidity 2 h; tank sensor 1 h; flow and return, cold water and ambient 3 h. The heat inputs'
  dropouts of under 10 s and the one of 19 minutes (2026-10-09) stay below their threshold.
- **Humidity silence counts as unavailable.** New option "humidity silence time", default 2 h, 0 turns it off (for
  a sensor that reports only on change). The runtime reads `State.last_reported`, which Home Assistant updates on
  every report, also an unchanged one; the replays use the gaps between recorded changes. A 2-hour threshold gave 3
  silences from 2026-10-01 to 2026-11-05, among them 2026-10-10.
- **Detection backup.** While every humidity sensor is unavailable or silent, a draw session of the next shower time
  starts a shower, as in the humid tail. "Shower detected" stays available; the repair issue says that detection is
  degraded.
- **Short runs.** A run shorter than 15 minutes (as for closures) does not charge: its heat counts as energy, after
  the start-up energy. A closure whose interval contains such a run is excluded with a new reason.
- **Heat outside a run.** A counter increase while no run is active (beyond the counter lag) counts as energy only:
  no charge and no start-up energy. The interval sums gain a heat term, a known input to the closure equation, so
  such closures are kept. Counter-only heating detection cannot tell this heat from a run; the README says that it
  needs a separate heating detector.
- **Calibrator windows.** The open quiet window and the armed first drop are stored with the calibration state; a
  store without them still loads.
- The quality-scale rule `repair-issues` (todo since 0.1.0) then becomes done.

**Evidence and checks.**
- A backtest of the October export with the humidity silence of 2026-10-10: the 10.2-minute shower counts as mixed.
- Synthetic fixtures for a short run and for a day of heat outside runs shaped like 2026-06-24; a reload test for
  the calibrator windows.
- The hourly statistics of 2026-06-23 and 2026-06-24 go into `private/installation.md` when the change is proposed.
- A live check of the heat outside runs in the next cooling season.
- Outside this project: the heat pump's firmware on the development installation now derives the DHW heat power
  during cooling from the full condensing power. Check before the cooling season that its counter matches the heat
  that reaches the tank (about 1.3 kW in June 2026), since the model trusts the counter.

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

Added 2026-11-04, from the review before that change was archived. It is not blocking; it is kept here so it is not
lost. The other two items of that review moved to `harden-sources-and-heat-input`.

- **Guard the fixtures against real entity IDs.** The packaging scenarios "Fixture from real history" and
  "Markdown with CRLF" were verified once by hand (tasks 3.2 and 1.3). Add tests: one that every entity ID in
  `tests/fixtures/` is one of the made-up IDs, and one that the Markdown check rejects a CRLF file.

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
