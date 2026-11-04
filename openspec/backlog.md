# Backlog

Follow-up changes that are agreed but not yet proposed. Each one becomes an OpenSpec change (`/opsx:propose`)
when it is taken up. Installation-specific evidence stays in `private/installation.md`; the items here only point
to it.

## improve-shower-end-detection

Added 2026-11-03 at the user's request, after the live shower check of `add-tank-insights-and-controls` (task 5.4).

**Problem.**
- Humidity detection ends when the reading falls to less than half the rise (3 points by default) above the
  lowest reading in the humidity window (60 minutes by default). The pre-shower readings set that minimum and stay
  in the window, so detection lasts about one window after the rise, even though the bathroom humidity drops
  sharply once the water stops.
- On the development installation on 2026-11-03, the shower ended at 20:45. The humidity peaked at 83.8 % at 20:49
  and was at 69.3 % at 20:57. Detection began at 20:40 and ended only at 21:39.
- While detection is on, every draw counts as mixed and adds to the shower's flow sample. That holds for a toilet
  flush or a washbasin in the tail as well: about 0.4 K too much for a 7 L flush.
- The shower end, and so its flow sample, is reported late.
- While detection is on, "Shower time remaining" keeps `flow_basis: current_shower`, with the rolling flow of the
  shower's last 2 minutes of flow, long after the water stopped. On 2026-11-03 it still showed 6.54 L/min and
  current_shower at 21:20, 35 minutes after the shower.
- It is related to the open question in `add-tank-insights-and-controls` task 5.5: two showers one after the other
  within one detection make one shower flow sample.

**Options to evaluate.**
- End on a fall from the peak. For example, end when the reading has fallen a set number of points below the
  highest reading since detection began, or when it keeps falling after the water has stopped.
- End at the end of the last draw session, once the humidity is falling and no water has run for a few minutes.
- A shorter humidity window. This is the simplest option, but it also changes the start rule, for example for a
  bath that fills slowly or a bathroom that warms up slowly.
- A combination: humidity for the start, water flow and a falling humidity for the end.

**Evidence needed.**
- An export of humidity, meter and detection history over several showers, including tail draws and back-to-back
  showers.
- A backtest of each option: shower start and end times, the litres classified as mixed, the shower flow samples,
  and the charge errors.

**Must keep.**
- A shower with a short pause (the 3-minute pause scenario) stays one shower.
- The 60 s session gap stays, the user's decision of 2026-11-03.

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
