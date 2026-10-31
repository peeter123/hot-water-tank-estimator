# The tank model

How the integration estimates the hot water left in a domestic hot water tank without a flow meter on the tank. The
code is `custom_components/hot_water_tank_estimator/model.py` (the tank) and `classification.py` (which litres are
shower water). Both are pure Python and use the symbols below. The defaults are in `const.py`.

## Symbols and units

| Symbol | Meaning | Unit |
|---|---|---|
| `t_avg` | Tank average temperature | C |
| `t_ch` | Charged temperature: the temperature of the hot layer | C |
| `t_cold` | Cold water temperature | C |
| `t_mix` | Mix temperature of the shower | C |
| `t_max` | Maximum tank temperature | C |
| `t_ambient` | Temperature around the tank | C |
| `V` | Tank volume | L |
| `f` | Cold fraction | 0-1 |
| `h` | Tank sensor height, from the bottom | fraction of the tank |
| `w` | Thermocline width | fraction of the tank |
| `u` | Usable fraction | 0-1 |
| `k` | Standing loss coefficient | per hour |
| `share` | Other-draws hot share | 0-1 |
| `S` | Start-up energy of a heating run | kWh |
| `delta` | Sensor tolerance | K |
| `m` | Sensor margin | K |
| `t_s` | Tank sensor reading | C |
| `s` | Normalised sensor reading, `(t_s - t_cold) / (t_ch - t_cold)` | 0-1 |
| `f_lo`, `f_hi` | `h - w / 2` and `h + w / 2`, each limited to 0-1 | 0-1 |
| `f_s` | Cold fraction the sensor reading implies | 0-1 |
| `t_s_avg` | Tank average the sensor reading implies | C |
| `dV` | Litres drawn in one reading (`dv` in code) | L |
| `dE` | Energy of one heat step (`de` in code) | kWh |

The volumetric heat capacity of water is taken as 1.163 Wh/(L*K), which holds near 20-60 C. The real value is about
1.5 % lower at 60 C, which is well inside the other uncertainties.

## Two layers: `t_avg` and `t_ch`

A charged tank is all at `t_ch`. Every draw replaces tank water with cold water from below, and a sharp thermocline
keeps the two apart, so the tank is a hot layer at `t_ch` above a cold layer at `t_cold`. The cold fraction is

```text
f = (t_ch - t_avg) / (t_ch - t_cold)      limited to 0-1, and 0 if t_ch <= t_cold
```

Keeping `t_avg` (its energy is `V * 1.163 * t_avg` Wh above 0 C) and `t_ch` gives three things: the energy balance
works on `t_avg` alone, the height of the tank sensor can be compared with `f`, and the outputs can say how much tank
water is still hot instead of how much energy is left. A sharply stratified tank is what a single sensor sees: it
reacts only once the cold layer reaches it.

Both temperatures cool with standing loss. `t_ch` changes only through loss, charging, heating (where
`t_ch >= t_avg`) and a sensor reading above it. After every update the model keeps
`t_cold <= t_avg <= t_ch <= t_max`.

## Draws are energy

A mixed draw is water through a thermostatic mixer. The house meter counts the hot and the cold litres together, so a
mixed litre takes `(t_mix - t_cold)` of energy from the tank. With `dV` litres drawn:

```text
mixed draw:   dt_avg = -dV * (min(t_mix, t_ch) - t_cold) / V          K
other draw:   dt_avg = -share * dV * (t_ch - t_cold) / V              K
```

- When `t_ch <= t_mix` the mixer draws only tank water, which is the `min`.
- The tank water that leaves in a mixed draw is `dV * (t_mix - t_cold) / (t_ch - t_cold)`, about 56 % of the litres at
  57 C, 38 C and 14 C.
- An other draw is any litre outside a shower: hot taps for hands and the kitchen among toilet flushes and
  appliances. A share of the litres leaves the tank at `t_ch`, the rest is cold water that bypasses it. The default
  share 0.2 is a fit on one installation, so it is learned per tank by calibration.

## Heat input

Energy counter: each increase of `dE` kWh during a heating run raises the average

```text
dt_avg = dE * 1000 / (1.163 * V)      K
```

and `t_ch = max(t_ch, t_avg)`, because a heating run circulates the tank.

Power sensor: `dE = P * dt` with `P` in W and `dt` in hours (a left Riemann sum: the previous reading holds until the
next one), applied with the same rule. A gap where the power was unavailable counts as no energy. If both a counter and
a power sensor are configured, the counter is the energy and the power only helps to detect the run.

**Start-up energy.** The first `S` kWh of each run are not applied. The counter reports energy that the circuit and the
heat exchanger keep while they warm up, and the amount depends on the plumbing. It only changes the estimate during a
run, because the charge at the end resets it, but it matters when a run is cut short, for example by a price block
that starts mid-run. The default is 0, because the value is per tank. Calibration learns it.

**Heating detection**, from the first configured source:

1. A heating-active binary sensor gives exact run edges.
2. Otherwise, heat power above the threshold (default 100 W, above standby readings and below any heating power).
3. Otherwise, 10 minutes after the last counter increase. Counters update at least every few minutes while heating.
   The timeout only finds the end: the run ends at the last increase, because after it the heater may circulate
   space heating water or stand still, and its flow and return no longer show the tank.

The first configured source decides. Sources go unavailable for seconds around restarts and reloads, so an unavailable
source holds the heating state instead of handing over at once, which would end or start a run and charge the tank to
a wrong temperature. After 15 minutes unavailable, the next configured source decides until it returns.

**Binary sensor only.** Without an energy counter or power sensor, `t_avg` and `t_ch` rise to the tank sensor whenever
heating is active and the sensor is higher, because a heating tank's sensor eventually rises.

## Charging at the end of a run

At the end of a heating run the heater has circulated the whole tank, so it is evenly mixed, whether or not it reached
the setpoint:

```text
t_avg = t_ch = t_charge
```

- `t_charge` is the highest mean of the heater's flow and return temperature over the 2 minutes before the run ended
  (for a run ended by the counter timeout, before its last counter increase).
  The return is water taken from the tank bottom, so it shows the whole tank. Flow and return start falling up to 40
  seconds before a demand sensor turns off, which is why the highest mean is used and not the last reading.
- Without flow and return sensors, or when their readings are unavailable, `t_charge` is the tank sensor reading. It
  agreed with the flow and return mean within 1.3 K on the development installation, but the heater's own
  temperatures do not depend on where the sensor sits.
- When neither is available, the modelled values stay.
- The charge makes errors in the heat input (counter overhead, losses during the run) irrelevant at every run end.

## Standing loss

At least every 5 minutes, and before every input is applied:

```text
t -= k * (t - t_ambient) * dt          for t_avg and t_ch, dt in hours
```

There is no loss below `t_ambient`. The default `k = 0.004` per hour is the median of quiet windows (5-10 hours with
no draw and no heating, where the tank sensor fell 0.08-0.24 K/h). Higher values follow evenings with draws, when the
cold layer was already near the sensor.

## The tank sensor as a measurement

The sensor sits at height `h` (configurable 20-80 %, default 50 %), because outside that range it would see only one
layer for most of the cycle. The thermocline is `w` wide (default 0.35). While heating is not active, with
`delta = 1.5 K` and `m = 2 K`, and `h - w / 2` and `h + w / 2` limited to 0-1:

| Sensor reading `t_s` | Meaning | Rule |
|---|---|---|
| `t_s >= t_ch - delta` | The cold layer is still below the sensor: `f <= h - w / 2` | Lower bound: `t_avg >= t_ch - (h - w / 2) * (t_ch - t_cold)` |
| in between | The thermocline is at the sensor | Cap: `t_avg <= t_s_avg + m`, below |
| `t_s <= t_cold + delta` | The cold layer has passed the sensor: `f >= h + w / 2` | Cap: `t_avg <= t_ch - (h + w / 2) * (t_ch - t_cold)` |
| `t_s > t_ch + delta` | Heat the model did not see | `t_ch = t_s`, and `t_avg` rises by the same step |

Raising `t_avg` with `t_ch` keeps `t_ch - t_avg`, so the outputs do not fall when heat arrives. The rules after it
use the new `t_ch`. With `f_lo = h - w / 2` and `f_hi = h + w / 2`, the lower bound is
`t_avg >= t_ch - f_lo * (t_ch - t_cold)` and the cold cap is `t_avg <= t_ch - f_hi * (t_ch - t_cold)`. For the reading
in between, the linear model of the thermocline gives

```text
s       = (t_s - t_cold) / (t_ch - t_cold)
f_s     = f_hi - s * (f_hi - f_lo)
t_s_avg = t_ch - f_s * (t_ch - t_cold)
```

`f_lo` and `f_hi` are limited to 0-1 before use, so the in-between reading spans the limited range and meets the two
other rules at its ends. When neither is limited, `f_s = h + w / 2 - s * w`.

- **The tolerance is critical.** A reading just below `t_ch - delta` caps `t_avg` near the top of the thermocline
  (about 12.5 K below `t_ch` with the defaults), while one just above it only sets the lower bound. A tank sensor that
  reads more than `delta` below the flow and return charge right after a run, or that cools faster than the tank,
  therefore drops the estimate by about a quarter of the tank at once. If the sensor sits below the charged
  temperature after a run, raise the tolerance until the sensor reads within it right after a run.

- **The lower bound** corrects overcounted small draws and keeps the model from emptying while the sensor still reads
  hot. A 141 L shower at a cold fraction of about 0.31 left the sensor unchanged, which is within `h - w / 2 = 0.325`.
- **The in-between reading is only an upper cap, never a raise.** In a long drain the linear reading fits the start
  and then reads too warm, because the thermocline widens during a long draw. Raising the model towards it would show
  water that is not there. As a cap it only pulls the model down when draws went uncounted, such as a shower that was
  not detected.
- **The margin** lets the energy balance smooth sensor noise and steps of 0.1 K. 2 K is about the sensor's change for
  20 L of shower in the thermocline.
- **The default `w = 0.35`** comes from two drains with the sensor at mid height. A 141 L shower at a cold fraction of
  about 0.31 did not move the sensor, so `h - w / 2 >= 0.31` and `w` is at most about 0.38. In a long drain the sensor
  reached 50 C (`s = 0.89`) at a cold fraction of about 0.35, which gives `w` of about 0.38, and 40 C at about 0.46,
  which gives about 0.28. So `w` is about 0.35. The tolerance of 1.5 K covers the slow loss of the top layer between
  charges.
- The rules are re-evaluated on every sensor reading, every 5-minute tick and after every draw, so the bounds hold
  through a long shower.

## Outputs

| Output | Formula | Unit |
|---|---|---|
| Tank water | `max(0, V * (u - f))` | L, whole litres |
| Shower water | tank water `* (t_ch - t_cold) / (t_mix - t_cold)`; equal to tank water when `t_ch <= t_mix` | L, whole litres |
| Percent charged | `(u - f) / u * 100`, limited to 0-100 | %, whole percent |
| Shower minutes | shower water / shower flow | min, whole minutes |

- `u` is the usable fraction: the cold fraction at which the outlet runs cold. It covers the thermocline and the
  outlet position. The default 0.85 is just above a drain that was still warm at about 0.78, and below 1, the limit
  of an ideal tank. A tank with a worse thermocline runs cold earlier, so users lower `u` after a shower that ran
  cold.
- Shower water is the energy identity of the mixed draw read backwards. It uses the unrounded tank water, and shower
  minutes use the unrounded shower water.
- Percent charged is 100 % right after any charge. Charged is by convention whatever the heater reached, so percent
  compares with the last charge, not with the setpoint. The litres show the absolute amount.
- The default shower flow 7.5 L/min is the median flow of single showers (6.3-7.6 L/min). The default mix
  temperature 38 C is a common thermostatic setting.

## Cold water temperature

A sensor when configured and available, otherwise a seasonal curve:

```text
t_cold = mean - amplitude * cos(2 * pi * (day_of_year - coldest_day) / 365)
```

The defaults are mean 12.5 C, amplitude 5 K and coldest day 46 (mid February). They follow published Dutch
drinking-water temperatures (about 7-8 C in February, 17-18 C in August), where ground temperature lags the air by
about six weeks. Other regions set their own values or give a sensor. A 2 K error in `t_cold` changes the shower
litres by about 8 %, and every charge absorbs it.

## Draw classification

Litres come from a whole-house water meter that also counts toilet flushes, cold taps and appliances. A litre is a
mixed draw while a shower or bath is detected, and an other draw otherwise.

- **Meter deltas.** The litres drawn are the increase between two readings, converted from the meter unit (m3, L, gal
  or ft3). A decrease is a meter reset: no draw, and that reading is the new starting point. A non-numeric or
  unavailable reading is no draw, and the last valid reading stays the starting point, so a meter that was offline
  applies the change since that reading when it returns.
- **Implausible jumps.** An increase above the maximum per reading (default 100 L) is ignored, becomes the new starting
  point and logs a warning. No household draws that much in 5-15 seconds, so such a jump is a meter catching up after
  being offline.
- **Sessions.** Increases no more than 60 s apart belong to one session. At 1 L resolution and the lowest realistic
  shower flow (about 2.5 L/min), increases are at most 24 s apart. A session starts at its first increase.
- **Humidity detection.** Each humidity sensor is compared with its own lowest value of the last 60 minutes (the
  value in force during the window counts). A shower is detected while any sensor reads at least the rise (default 6
  points) above that minimum. It lasts until every sensor that reached the rise is below its minimum plus half the
  rise, so detection holds until the room has dried most of the way. A sensor that never reached the rise does not
  hold it. Shower rises are 13-40 points while other draws stay within 2. A tap used in the drying time counts as
  mixed, which errs on the side of showing less.
- **Long-draw rule.** When set (minutes, default 0 = off), a session that has lasted that long counts as a shower
  until it ends. It is for homes without a humidity sensor, and it also fires on garden watering.
- **Reclassify window.** Humidity lags the start of a shower by up to a minute, and the long-draw rule fires only after
  its duration. When detection starts, the litres of the current session that were drawn within the last 3 minutes
  (the window) and counted as other draws become mixed draws, and the model is corrected by the energy difference
  `dV * (min(t_mix, t_ch) - t_cold) / V - share * dV * (t_ch - t_cold) / V`. Only the window is reclassified, not the
  whole session, because a slow night trickle can merge with a later shower in one session, and reclassifying all of
  it would take far too much energy.

## Calibration and backtest

Calibration is documented when it is implemented.
