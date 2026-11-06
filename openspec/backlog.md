# Backlog

Follow-up changes that are agreed but not yet proposed. Each one becomes an OpenSpec change (`/opsx:propose`)
when it is taken up. Installation-specific evidence stays in `private/installation.md`; the items here only point
to it.

## Live check carried over: heat loss follows the ambient sensor

This check was moved out of `add-tank-insights-and-controls` (task 5.4) at the user's request on 2026-11-03. Over a
few days with a changing room temperature, check that the "Heat loss" sensor follows
`k * C * (T_avg - T_ambient)` with the ambient sensor's reading, and that it falls back to the configured ambient
temperature after a long sensor outage. Record the result in `private/installation.md`. It can be done
in any later change that touches the loss model, or on its own.

## Live check carried over: heat outside a heating run

Carried over from `harden-sources-and-heat-input`, which counts a counter increase outside a heating run as energy
only (no charge, no start-up energy), with the heat in the closure equation, while the option "Count heat outside
heating runs" is on (default off; on for the development installation). No such heat occurred from 2026-10-01 to
2026-11-06; it is expected in the cooling season.
- **Evidence.** A heat pump can dump the heat of cooling into the tank with DHW demand off, up to its own setpoint. The
  hourly statistics of the development installation show the DHW energy counter rising during cooling in June 2026,
  and it is not known whether that came in DHW runs. The numbers are in `private/installation.md`, section
  "Evidence for harden-sources-and-heat-input".
- **Check before the cooling season (outside this project).** The heat pump's firmware on the development
  installation now derives the DHW heat power during cooling from the full condensing power. Check that its counter
  matches the heat that reaches the tank (about 1.3 kW in June 2026), since the model trusts the counter.
- **Check in the cooling season.** With a separate heating detector, check that heat outside a run raises T_avg by
  `E * 1000 / (1.163 * V)` K (E in kWh, V in litres) and that the closures that contain it stay within the usual
  charge error. A backtest of that time needs the option on (`scripts/backtest.py --options` with `outside_heat`),
  as the live entry has it. Record the result in `private/installation.md`.

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
