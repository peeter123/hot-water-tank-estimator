# Design

## Context

See proposal.md (Why) for the motivation and the specs for the behaviour. This document records how the model was
derived and why each choice was made.

The repository is new: no code and no specs yet. The calibration evidence below comes from the development
installation's Home Assistant history, from 21 to 31 October 2026. That installation has:
- a 281 L effective tank (manufacturer figure) heated by a ground source heat pump;
- one tank temperature sensor;
- the heat pump's thermal DHW energy counter (kWh) and a DHW-demand binary sensor;
- a whole-house water meter (m3, 1 L resolution, readings every 5 s during flow);
- one bathroom humidity sensor in the only room with a shower and a bath.

An evening price block keeps the heat pump from reheating between 16:00 and 23:00.

### Evidence

1. **Long shower, 29 October 18:40-19:14.**
   - 239 L were drawn at 7-8 L/min with no reheating.
   - The tank sensor fell from 54.0 to 50.0 C over the first 96 L, then roughly linearly: 40 C at 146 L, 30 C at
     205 L, 23 C at 239 L. It settled at 21.9 C half an hour later.
   - The user confirmed that the last shower was still warm at the end.
2. **Recharge, 23:00-01:08.**
   - The energy counter rose by 10.64 kWh. Heat capacity of 281 L is 281 * 1.163 Wh/(L*K) = 0.327 kWh/K.
   - So the average rose by 32.6 K and ended at the 50.5 C the sensor showed. The tank average before the recharge
     was therefore about 18 C, which is below the sensor's 22 C, as expected with cold water at the bottom.
   - The energy balance closes within the uncertainty of the cold water temperature.
3. **Cycle ends.**
   - The night cycle stopped at 50.5 C and the next midday cycle reached 58.5 C (setpoint 58 C). A cycle does not
     always end at the setpoint.
   - After a cycle the sensor stays flat apart from slow loss, so the tank is evenly mixed then.
4. **Standing loss.**
   - With no draws overnight the sensor fell 0.14 K/h at about 37 K above room temperature, so k is about
     0.0037 per hour.
5. **Humidity.**
   - The bathroom sensor rose from 61 to 72 % within a minute of the shower starting, peaked at 92 % and took about
     45 minutes to fall back near its baseline.
   - Other days show the same 25-30 point peaks.
6. **Small draws.**
   - A day of toilet flushes and taps (about 100 L) moved the sensor no more than standing loss alone.

## Goals / Non-Goals

**Goals:**
- An estimate that is right at the moments that matter: during and after showers while reheating is blocked.
- An estimate that cannot drift over days, because it is corrected by measurements every heating cycle and
  whenever the sensor shows the tank emptying.
- Every parameter is explained and has a default backed by data, so a new user only needs to tune one or two.
- The model is testable without Home Assistant.

**Non-Goals:**
- Resolving the temperature layers inside the tank. One average with a floor temperature is enough for this
  question.
- Exact physics of mixing at the thermocline. The floor temperature absorbs it.
- Predicting future use.

## Decisions

### D1: The state is the tank's average temperature

All changes to the tank are energy flows: draws, heat input and loss. The tank's heat content above 0 C is
`V * 1.163 * T_avg` Wh, so tracking `T_avg` is the same as tracking the energy. Three reasons to prefer
temperature over litres:
- the unit can be checked directly against the sensor;
- it does not depend on the cold water temperature, which changes with the season;
- heat input converts to it without knowing how full the tank is.

Litres remaining are derived from it only for display.

- Alternative, litres of hot water as the state: needs a "hot" temperature for every litre, double-counts when the
  heating stops at a partial charge, and becomes wrong as the cold water warms through the year.

### D2: Energy balance plus sensor corrections, not a sensor-only curve

- Draws: `dT = -dV_hot * (T_draw - T_cold) / V` in K, with dV in L and V in L. A thermostatic shower mixer takes
  the energy for `dV_mix * (T_mix - T_cold)` out of the tank whatever the tank temperature is.
  `T_draw = min(T_mix, T_avg)`, because a tank colder than the mix temperature delivers less energy per litre.
- Heat: `dT = dE * 1000 / (1.163 * V)` in K, with dE in kWh. 1.163 Wh/(L*K) is the volumetric heat capacity of
  water near 20-60 C. The real value is about 1.5 % lower at 60 C, which is well inside the other uncertainties.
- Power input is integrated with the left Riemann sum between readings: `dE = P * dt`, P in W, dt in h. A gap
  while unavailable counts as zero.

**Corrections from the sensor:**
- **Anchor when heating stops:** `T_avg = T_sensor`. Evidence 2 and 3: the tank is evenly mixed after heating, so
  the sensor reads the average. This also makes up for any heat input error, such as a counter that includes
  pipe losses.
- **Cap while not heating:** `T_avg = min(T_avg, T_sensor + margin)`. Evidence 1 and 6: a sensor low in the tank
  misses small draws and the first part of a long one, so it may read *higher* than the true average. That is why
  the model never raises itself to the sensor outside heating. Once the sensor falls, the cold layer has reached
  it and the average cannot be much above it:
  - At 146 L into the shower the model said 41.3 C and the sensor 40 C.
  - At 239 L the pure model said about 33 C, while the recharge energy implies about 18-26 C.
  - With the cap margin at 3 K, the cap gives 26 C.
  - The 3 K default allows for the 1.4 K the sensor read below the model at 146 L, plus sensor noise. It still
    pulls the model down to a value consistent with the recharge energy by the end of the shower.
- **Bounds:** `T_cold <= T_avg <= T_max`. These keep a long chain of misclassified draws or a bad counter from
  producing impossible values. `T_max` defaults to 95 C, which is safe for any tank with a resistive heater.

**Alternatives:**
- A curve from sensor temperature to litres remaining, fitted to evidence 1. It is simple, but flat over the first
  100 L, so it shows a full tank for the first third of a shower. It also depends on where the sensor sits in each
  tank, so it does not generalise.
- An automation with input_number helpers, the first plan in the author's config workspace. It works for one house
  but cannot be shared, needs about 10 helpers per tank, and spreads the logic over Jinja templates that are hard
  to test. Rejected in favour of an integration.
- A Kalman filter that blends sensor and model. It needs a measurement model of where the sensor sits. That is
  more parameters than the anchor-and-cap rules, for no clear gain at this resolution.

### D3: Heating detection falls back through three sources

1. A heating-active binary sensor gives exact cycle edges for the anchor.
2. Otherwise, heat power above a threshold (default 100 W, which is above standby readings and well below any
   heating power).
3. Otherwise, a 10-minute window after the last energy counter increase. Counters update at least every few
   minutes while heating, so 10 minutes rides through gaps without delaying the anchor much.

With no heat input source at all, only a binary sensor, the model rises to the sensor while heating. A tank cannot
heat without the sensor rising eventually, so this keeps the model from only ever going down.

### D4: Draw classification by humidity rise, with a recount per session

- Litres come from the whole-house meter. `w = 1` for litres drawn while a shower is detected, and
  `w = other_share` otherwise.
- Detection uses a rise of at least 6 points over the window minimum of the last 60 minutes. Evidence 5: an 11
  point jump within a minute, while normal daily swings stay within 2-3 points.
- Hysteresis is half the rise. Detection ends once the humidity has fallen most of the way back, which at the
  development installation is about 45 minutes after the shower. A tap used in that time counts as hot, which errs
  on the safe side.
- Humidity lags the start of the shower by up to a minute, so when detection starts the litres already drawn in the
  current session are recounted to `w = 1`. Sessions are increases no more than 60 s apart. At 1 L resolution and
  the lowest realistic shower flow (about 2.5 L/min), increases are at most 24 s apart.
- The long-draw rule, off by default, is for homes without a humidity sensor: a session longer than N minutes is a
  shower and is recounted the same way. It is off by default because watering a garden would also trigger it.
- Other share is 0.3. Toilet flushes (cold, about 6 L) are the most frequent draws, and hand washing and kitchen
  taps mix hot and cold. The anchor and cap reset whatever error this leaves. The backtest compares the model with
  the sensor at each cycle end, so this value can be tuned.
- Jumps over 100 L in one reading are ignored. No household draws that much in 5-15 s. A jump that large is a
  meter catching up after being offline, and applying it all at once would empty the model.

Alternatives:
- A bathroom flow meter or a temperature probe on the hot pipe would be best, but few homes have one. They can be
  added later as optional sources.
- The rate of humidity rise (derivative) was rejected. It is near zero during a long shower once the room
  saturates, so detection would stop in the middle of the shower.

### D5: Outputs use a usable floor temperature

- `litres = V * (T_avg - T_floor) / (T_mix - T_cold)`.
- In a fully mixed tank the shower turns cold when the outlet reaches T_mix, which would make `T_floor = T_mix`.
- In a perfectly layered tank the hot top layer lasts until the whole tank is cold, which would make
  `T_floor = T_cold`. Real tanks fall between the two.
- Evidence 1: the shower was still warm with the average at about 26 C, so on that tank `T_floor` is at most about
  26 C.
- The default is 25 C. That is close to the evidence and slightly conservative, because a tank with a worse
  thermocline than the development tank runs cold earlier, and showing too much is worse than showing too little.
- The README explains how to lower it once a shower is known to have run cold at a reported remaining above zero.
- Percent uses `T_full` as 100 %. This is the setpoint entity when one is given, because users think of a full
  tank as one at its setpoint, and otherwise 55 C.
- Minutes uses a typical shower flow of 7.5 L/min, from evidence 1 (7-8 L/min).

### D6: Seasonal cold water curve

- `T_cold = mean - amplitude * cos(2 * pi * (doy - coldest_day) / 365)`.
- Defaults: 12.5 C mean, 5 K amplitude, coldest on day 46 (mid February). This follows published Dutch
  drinking-water temperatures (about 7-8 C in February, 17-18 C in August): ground temperature lags the air by
  about six weeks.
- Users elsewhere set their own values, or give a sensor.
- A 2 K error in T_cold changes the remaining litres by about 8 %, and anchors absorb it, so a sensor is optional.

### D7: Home Assistant structure

- `model.py` is a pure Python class with the formulas from D2-D6. It takes timestamps and numbers and returns
  events. It has no Home Assistant imports, so unit tests and the backtest script run it directly.
- `__init__.py` sets up the entry, keeps one `TankEstimator` runtime object in `entry.runtime_data`, and registers
  the action.
- The estimator subscribes with `async_track_state_change_event` to:
  - the water meter;
  - the energy counter or power sensor;
  - the heating binary sensor;
  - the tank sensor;
  - the humidity sensors;
  - the cold water sensor.

  It also runs a 5-minute `async_track_time_interval` for loss and cap. Listening to events instead of polling
  keeps each litre and each heat step exact.
- Entities subscribe to the estimator through a dispatcher signal and render from its state. There is no
  coordinator because nothing is polled.
- The tank average sensor is a `RestoreSensor`. Its extra stored data holds:
  - the last valid meter reading and the last valid energy reading;
  - the session state;
  - the humidity samples of the last window, at most one per minute per sensor.

  All of these are needed to apply changes correctly after a restart.
- The config flow has steps: tank (name, volume, tank sensor), water meter, heat input, shower detection, cold
  water and setpoint. Entity selectors are filtered by domain and device class. The options flow holds every
  tuning value plus the optional sources, and an options update reloads the entry. The model state survives the
  reload through the restore data, so the options requirement holds.
- Diagnostics: options, state, source availability and a ring buffer of the last 50 events (time, kind, input
  change, T_avg before and after).
- Translations go in `strings.json` and `translations/en.json`, with plain text names.

### D8: Backtest script

`scripts/backtest.py` fetches the recorder history of the configured source entities over the websocket API for a
date range. The token is read from a file and the entity IDs come from command-line arguments, so nothing is
installation-specific. It replays the history through `model.py` and prints:
- the model against the sensor at every anchor (the error just before the anchor);
- the model and remaining litres through each detected shower;
- a summary that suggests the other share and floor that minimise the anchor error.

The replay test fixture is a trimmed, anonymised copy of evidence 1 and 2.

## Risks / Trade-offs

- [The sensor sits high in some tanks, not low] -> The cap still holds: the sensor reads at least the average
  near the top. The anchor is unaffected. Only the early-shower lag differs, and that makes the model more accurate,
  not less.
- [Several bathrooms, or showers in a room without a humidity sensor] -> Several humidity sensors are allowed. The
  long-draw rule covers rooms without one. Showers that are not detected count at the other share, and the cap
  corrects the error once the sensor falls.
- [Garden watering in summer counts at the other share] -> At most 0.3 of the volume is wrongly counted, the cap
  corrects it, and the next cycle anchor resets it.
- [A humidity rise without a shower (cooking, humid weather)] -> No meter increase means no effect. If water runs
  meanwhile, it errs towards showing less hot water.
- [The water meter misses low flows] -> Small trickles are lost, which errs towards showing more water. The cap
  catches large errors.
- [A recount after a reload mid-shower] -> The session state is restored, so a recount still applies.
- [A floor temperature set too low shows water that is not there] -> The default is conservative, and the README
  explains how to tune it.

## Migration Plan

There is no existing integration to migrate from. Rollout on the development installation:
1. Deploy the integration folder over SSH (the author's workspace deploy script gets a mapping) and restart.
2. Add the config entry with that installation's entities (listed in the git-ignored `private/installation.md`)
   and the defaults.
3. Compare with the sensor for a week through diagnostics and the backtest. Tune the options.
4. Add a dashboard block.

Rollback: remove the config entry and the folder. Nothing else depends on it.

## Open Questions

- Whether to exclude dishwasher and washing machine fills with their own water sensors, where the appliance
  integration reports them. This can be added as optional "cold appliance" water sensors later without changing the
  model.
- Which display name and icon the HACS brands repository should get. This can wait until after the first release.
