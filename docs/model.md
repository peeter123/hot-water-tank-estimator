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
| `t_ambient` | Ambient temperature in use: the temperature around the tank | C |
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

and `t_ch = max(t_ch, t_avg)`, because a heating run mixes the tank above the heat source.

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

At the end of a heating run the tank above the heat source is evenly mixed, whether or not the run reached the
setpoint. An external circuit circulates the tank and its return is tank-bottom water. A coil low in the tank mixes
the tank above it by convection, and its return is the coil's outlet. The model counts the whole tank at `t_charge`
by convention:

```text
t_avg = t_ch = t_charge
```

- `t_charge` is the highest mean of the heater's flow and return temperature over the 2 minutes before the run ended
  (for a run ended by the counter timeout, before its last counter increase).
  With an external circuit the return is water taken from the tank bottom, so it shows the whole tank; with a coil
  it is the coil's outlet. Flow and return start falling up to 40 seconds before a demand sensor turns off, which is
  why the highest mean is used and not the last reading.
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

### Ambient temperature in use

`t_ambient` is not a fixed value when an ambient temperature sensor is configured. The model's
`ambient_temperature(now)` returns:
- the sensor's reading, while it is available;
- its last reading, for `ambient_fallback` hours after the sensor became unavailable (default 3, range 0-24);
- the `ambient_temperature` option otherwise, which is also the value without a sensor, and the value before the first
  reading of a history that starts late.

The loss step, the loss sums of the calibration intervals, the quiet-window estimate and the heat loss output all call
it, so they cannot disagree about the room. The loss of a step uses the value in force during the step (the reading
before a change arrives).

Why 3 hours. Over a month, an air sensor next to a tank in a basement read within a 2.5 K span (18.7-21.25 C), moved at
most 1.3 K within one day, and its daily mean drifted 1.5 K over the month. A reading 3 hours old is therefore within
about 1 K of the true room temperature, which against a tank-to-room difference near 38 K is under 3 % of the loss
rate. That covers the short radio or battery outages of wireless sensors. After a longer outage the reading may belong
to another part of the day, so the configured value is the better guess. 0 turns the hold off and 24 holds a day.

A removed cold water or ambient sensor has no say: its last reading is dropped, so the seasonal curve, or the
`ambient_temperature` option, applies at once.

Changing the ambient source recalibrates, because `k` fitted against a fixed 20 C and `k` fitted against a sensor are
different parameters: the loss coefficient is defined against `t_ambient`, so keeping the old value would bias it.

### Heat loss output

```text
heat_loss_w = k * C * max(0, t_avg - t_ambient) * 1000        C = 1.163 * V / 1000 in kWh per K
```

`k` per hour times `C` in kWh per K times the excess in K is kW; `* 1000` gives W. It uses `t_avg`, not `t_ch`, because
the loss acts on the whole tank and the loss step applies the same rate to `t_avg`. For a 285 L tank with `k = 0.0039`
per hour at 58 C in a 19.5 C room it is `0.0039 * 0.331 * 38.5 * 1000 = 50` W. It is a main sensor rather than a
diagnostic one, because it answers what keeping the tank hot costs. On the development installation it reads about
50 W, against a rated 58 W at that temperature difference: the learned `k` sits a little below the rated value.

## The tank sensor as a measurement

The sensor sits at height `h` (configurable 20-80 %, default 50 %), because outside that range it would see only one
layer for most of the cycle. `h` is the share of the water volume below the sensor, not of the outer height of the
tank: the water column starts above the floor (base, bottom insulation, dished bottom). On a tank whose sensor sleeve
is at 1020 mm of 1660 mm outer height (0.61), `h` is about 0.58 of the water. A wrong height shows as a bias in the
charge errors: on the development installation 0.50 instead of 0.58 raised the fitted error from 1.5 to 1.9 K. The
thermocline is `w` wide (default 0.35). While heating is not active, with
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
- **The default `w = 0.35`** is a generic starting value, and the setup fit replaces it. The evidence of the
  development installation is two drains. A 141 L shower at a cold fraction of about 0.31 did not move the sensor,
  and in a long drain the sensor reached 50 C (`s = 0.89`) at a cold fraction of about 0.35 and 40 C at about 0.46.
  Together they give `h - w / 2` of about 0.31-0.35. With that tank's measured height of about 0.58,
  `w = 2 * (h - f)` is about 0.46-0.54, and the full thermocline rule applied to the 50 C point gives about 0.59. Its
  setup fit gives 0.44. At mid height the same drains read as `w` of about 0.35, which is why the
  default stays. The tolerance of 1.5 K covers the slow loss of the top layer between charges.
- The rules are re-evaluated on every sensor reading, every 5-minute tick and after every draw, so the bounds hold
  through a long shower.

## Outputs

| Output | Formula | Unit |
|---|---|---|
| Tank water (shown as hot water remaining) | `max(0, V * (u - f))` | L, whole litres |
| Shower water | tank water `* (t_ch - t_cold) / (t_mix - t_cold)`; equal to tank water when `t_ch <= t_mix` | L, whole litres |
| Percent charged (shown as charge level) | `(u - f) / u * 100`, limited to 0-100 | %, whole percent |
| Shower minutes | shower water / shower flow | min, whole minutes |

- `u` is the usable fraction: the cold fraction at which the outlet runs cold. It covers the thermocline and the
  outlet position. The default 0.85 is just above a drain that was still warm at about 0.78, and below 1, the limit
  of an ideal tank. A tank with a worse thermocline runs cold earlier, so the "Hot water ran out" button lowers `u`
  after hot water ran out early.
- Right after a charge `f` is 0, so tank water is `V * u`, less than the tank volume `V`. The unusable `1 - u`
  covers the lukewarm layer that cold inflow mixes at the bottom during draws and, for a coil low in the tank, the
  colder water below the coil, which cannot be drawn hot. The energy that this colder water lacks is not in `u`: the
  start-up energy that the closures learn carries it.
- Shower water is the energy identity of the mixed draw read backwards. It uses the unrounded tank water, and shower
  minutes use the unrounded shower water.
- Percent charged is 100 % right after any charge. Charged is by convention whatever the heater reached, so percent
  compares with the last charge, not with the setpoint. The litres show the absolute amount.
- A coil low in the tank is supported: the colder water below it is carried as litres by `u` and as energy by the
  start-up energy. A coil or element high up in the tank, or a second heat source such as an electric element, is not
  supported yet: the charged state assumes that the run heats the whole tank from one heater.
- The default shower flow 7.5 L/min is a round value near the median flow of single showers (about 7.3 L/min;
  6.2-10.0 L/min for single showers). The default mix
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
- **Reclassify window.** Humidity rose 0.9-6.3 minutes after a shower started on the development installation, and
  the long-draw rule fires only after its duration. When detection starts, the litres of the current session that
  were drawn within the last 10 minutes (the window) and counted as other draws become mixed draws, and the model is
  corrected by the energy difference
  `dV * (min(t_mix, t_ch) - t_cold) / V - share * dV * (t_ch - t_cold) / V`. With a 3-minute window, six showers of
  the month kept 8-21 L as other draws, up to about 1.2 K of T_avg each; 10 minutes covers every case seen. The
  window still bounds the reclassification, so a long session in which other draws ran into a shower does not take
  mix energy for all of it. The data had no such session, so this is a safeguard, not evidence.

## Calibration and backtest

The code is `calibration.py` (closures, the fitter, quiet windows, the width) and `setup_fit.py` (the replay of
history). Both are pure Python. Each tank fits its own parameters, because the hot share of tap water, the start-up
energy of the plumbing, the insulation and the thermocline differ per house. The defaults are only where it starts.

| Parameter | Bounds | Learned from |
|---|---|---|
| other-draws hot share `share` | 0-0.6 | charge closures |
| start-up energy `S` | 0-3 kWh | charge closures |
| loss coefficient `k` | 0.001-0.015 per hour | charge closures, quiet windows |
| thermocline width `w` | 0.1-0.6 | first sensor drop after a charge |
| usable fraction `u` | 0.5-0.98 | the "Hot water ran out" button |

The value in use is the option value until a parameter has been learned, then the learned value. A parameter the
user locks keeps its option value and is never learned; removing the lock discards the value learned before it, so
the option value applies until the next fit. The source of a value is option, setup fit, learned or locked.

### The charge closure

The balance in `model.py` keeps a second copy of `t_avg` and `t_ch` that leaves out the sensor bounds, and sums,
since the previous charge, the three terms that change `t_avg`: `loss` (the sum of `(t_avg - t_ambient) * dt`, in
K*h), `other` (the sum of `dV * (t_ch - t_cold) / V` over other draws, in K, for a share of 1) and `mixed` (the
mixed-draw drops, in K). So learning measures the balance and not the corrections.

At the end of a run the model counts the tank at `t_charge`, so the true average at the start of the run follows from
the run's energy `E_run` (kWh), the start-up energy `S` and the draws and loss during the run. With
`C = 1.163 * V / 1000` kWh/K:

```text
t_true_start = t_charge - (E_run - S) / C + mixed_run + share * other_run + k * loss_run
t_ch_prev - t_true_start = k * loss + share * other + mixed          (the interval before the run)
```

- The charge error is the model's `t_avg` at the run start (with its sensor bounds) minus `t_true_start`. A sensor
  bound that corrected a missed shower shows as a smaller error, so the error measures the whole estimate.
- The `_run` sums are the same three terms inside the run. Showers and loss do not stop while the heater runs, and a
  run that starts during a shower is common.
- Together the two lines are linear in `k`, `share` and `S`:
  `t_ch_prev - t_charge + E_run / C - mixed_total = k * loss_total + share * other_total + S / C`, with the totals
  over the interval and the run. The fit solves this.
- **Counter lag.** When a binary sensor or the heat power decides the run, the energy counter can report the last
  step after the run ended. Counter increases up to 10 minutes after the end count towards `E_run`. The model has
  charged by then, so only the closure uses them.
- A run ended by the counter timeout is found 10 minutes late. Its sums are those at the last counter increase.

A closure is excluded from the fit and from the error statistics when:
- the run lasted less than 15 minutes, because a short run does not mix the tank;
- a source was unavailable for more than 10 % of the interval. The model counts the unavailable seconds of every
  source it was given: water meter, energy counter, power, heating sensor, flow and return, tank sensor, cold water
  sensor and each humidity sensor. The ambient sensor does not count: the model always has an ambient value (the
  sensor, its last reading or the option), and it enters only the loss term, where a 1 K error moves a closure by
  about 0.03 K over 8 hours;
- the "Hot water ran out" button reset the model in the interval or at its start. The model then starts from a guessed
  state, so the interval has no charged start;
- the run has no charged temperature (no flow and return and no tank sensor). The model keeps its values, and the
  next interval is excluded too, because it has no known charged start.

The first charge of a replay is a sensor start and not a closure: the model starts at the sensor's reading, which
ignores the draws since the real last charge. Its error is information only. The same holds live: a new entry starts
at the tank sensor's reading, so its first heating run is a sensor start and does not raise the number of
calibration samples. The run after it is the first closure. Without an energy counter or power
sensor there are no closures, and `k` comes from quiet windows only.

### Learning

- **Closure fit.** After each valid closure the fitter solves the equation above for `k`, `share` and `S` over the
  stored closures (at most 100) by weighted least squares. The newest closure has weight 1 and each older one 0.95
  times the next. A locked parameter moves to the right-hand side and leaves the unknowns. The fit is applied only
  with at least 5 closures stored. From 3 quiet-window estimates on, `k` is held at their mean and counts as locked
  here, so the closures fit only `share` and `S` (see below why).
- **Bounds and steps.** Every update of a learned parameter (closure fit, quiet-window `k` and width alike) is first
  limited to the bounds, then moves from the value in use by at most a quarter of the bound range. The button is
  the exception: it is the user's observation. A share of 0.2 and a fit of 0.5 give 0.35. One odd interval (a guest's
  bath, a leaking tap) cannot throw the values off, and a fit that wanders needs several updates to get anywhere.
- **Loss from quiet windows.** A window is a stretch of at least 5 hours with no draw and no heating, in which the
  tank sensor reads within `delta` of `t_ch`. A window opens no earlier than 1 hour after a run end, because the
  sensor still settles then (windows opened at the run end gave estimates about half of the others). Then
  `k = rate / (t_mean - t_ambient)`, with the sensor's fall in K/h, its time-weighted mean reading, and the
  time-weighted mean of the ambient temperature in use over the window. The last 10
  windows are averaged. From 3 estimates on their mean is the loss coefficient in use, and the closure fit holds it.
  With fewer, the closure fit sets `k` once 5 closures are stored (without a heat measurement, the quiet windows
  always do). Any draw ends a window, even one litre, so busy households get few windows.
- **Width from the first drop.** When the sensor first falls below `t_ch - delta` after a charge, with heating off,
  the balance's cold fraction `f_e` is the cold fraction at the top of the thermocline, `h - w / 2`. So
  `w = 2 * (h - f_e)`. Each estimate is limited to the bounds, the width is the mean of the last 10, and it is
  applied after 3.
- **Usable fraction.** Only a person can tell that hot water ran out. The button "Hot water ran out" applies to the
  end of the last draw, not to the moment of the press, because the user leaves the shower or the tap first and a
  press up to 20 minutes later still means that draw. A draw session that is still running counts as ending now. The
  model keeps, for the last draw session, the state after its last increase: end time, `f`, `t_ch`, `t_avg`, `t_cold`,
  the tank sensor reading and `u` in use. The press then runs these steps on that record:
  1. No session running or ended within the last 20 minutes: reject (`no_recent_draw`). A tap counts like a shower,
     because a tap running cold is the same evidence.
  2. The tank sensor read at least `t_ch - delta` at the end of that draw: reject (`sensor_hot`). While the sensor
     reads hot, the cold layer is below it and cannot have reached the outlet at the top, so a cold outlet is cold
     pipe water and not an empty tank. A record without a sensor reading skips this check.
  3. Unless `u` is locked, `u = clamp(f_end, 0.5, 0.98)`, set directly because it is the user's observation.
  4. The tank is emptied at the end of that draw: `D = max(0, u - f_end) * (t_ch_end - t_cold_end)` in K is the
     `t_avg` drop that makes `V * (u - f) = 0` there (`f` rises by `dT / (t_ch - t_cold)` per K). It is applied to
     the current `t_avg`, so heat added since the draw end stays and the loss since is already in `t_avg`. With a
     learned `u` set to `f_end`, `D` is 0 and only the new `u` empties the outputs; with a locked `u`, or `u` held
     at 0.5, `D` is positive. `D` is not applied when `t_avg` was replaced after the draw end, by a charge (the end
     of a heating run), by the `set_tank_state` action or by an earlier press: that reset already replaced the
     `t_avg` that `D` would correct, so a press after a charge would lower a freshly charged tank, and a second press
     on the same draw with a locked `u` would apply `D` twice. Only `u` is learned then.

  A rejected press changes nothing, is logged as an event with the reason and its values, and shows a notification
  that names the reason (for example the sensor reading). "Cold" differs a little between a tap and a shower: a tap
  runs cold when the outlet water at the tap is cold, while a shower with a thermostatic mixer turns cold once the hot
  side falls below the mix temperature. The model treats both as the moment `f` reached the limit `u`, so a tap and a
  shower teach the same parameter, and the difference is absorbed in the learned value.
- **Precedence.** Option value, then the setup fit, then live learning, unless locked. Live learning changes a
  parameter the setup fit set from `setup_fit` to `learned`: `setup_fit` returns a calibrator that is already live
  (`Calibrator.go_live`), so only what the fit itself changed keeps the source `setup_fit`. A recalibrate replaces
  the calibration state with the new fit, but keeps the usable fraction learned from the button (and its source),
  which no replay can learn.
- **What the data can separate.** The loss sum and the other-draw sum of the closures move together (a correlation of
  0.93-0.96 in the development data), because both grow with the length of an interval. `S` is a constant per run,
  and `k` and `share` trade off against each other. Over a month (25 closures) all three separate; over a week
  (7 closures) the standard errors of `k` and `share` are wider than their bounds, and the fit gave `share` 0.00 and
  `k` 0.0094 per hour, then a different pair when one closure was left out. Quiet windows measure `k` directly from
  the sensor, so the closure fit holds `k` there and fits `share` and `S`; this gave the same values on a month as
  a free `k` did and a stable fit on a week. Without quiet windows (a busy household) `k` is fitted from the
  closures too; expect the first weeks to move the values then. The step limit and the minimum of 5 closures
  limit the damage of any single fit.

### The setup fit

When an entry is created, and when the recalibrate action runs, the history of the sources (the configured number of
days, up to 30, as far as the recorder keeps them: 10 days by default) is replayed through the same model and learner.
`setup_fit.setup_fit(history, options, locks=...)` takes a `History` (per source: role, entity ID, unit and `(time,
state)` rows, the first row being the state in force at the start). It returns the fitted options, the parameters with
their sources, the closures with their charge errors and the calibration state. `setup_fit.evaluate(history, options)`
replays with fixed options and reports the same errors, so fitted options can be compared with the defaults. A fixture
becomes a `History` with `history_from_fixture`, and a recorder export with the reader in the backtest script.

In the integration the fit runs in the background when an entry is first set up, and again at each start until it
has run once (a recorder that is missing or holds no history does not count). Sources excluded from the recorder
weaken it, because their rows are missing. The live model does not take the replay's end state: it keeps its own
state, which starts at the tank sensor's reading, and only the calibration comes from the fit.

The fit also runs at the first start after the configured ambient sensor differs from the one the calibration was
fitted with (added, removed or replaced), because `k` depends on it. The entry stores the ambient entity of its last
fit, and the fit repeats at each start until it completes or finds no history.

The replay starts the model at the tank sensor's first numeric reading and ticks every 5 minutes. A history with an
ambient series feeds it to the model like the cold water sensor, so the loss and the quiet windows of the replay use
the ambient in use (see "Ambient temperature in use"). It applies each
learned change to the model as it goes, so the fit of a long history converges the way live learning does. A parameter
with too little data keeps its option value: with fewer than 5 closures the share and `S` stay, and `k` may still come
from quiet windows.

### The backtest

`scripts/backtest.py` is the developer's view of what an entry's setup fit does. It runs the setup fit on a fixture
or on a history export, then replays the history with the options as given and with the fitted ones. It prints the
charge error at every closure for both, the outputs through every shower, the fitted parameters with their sources
and the mean absolute error for both. On a fixture:

```sh
uv run --no-project scripts/backtest.py tests/fixtures/week.json
```

On an export folder from `scripts/history.py` the tank volume is needed, and file names that are not role names need
a mapping from file stem to role:

```sh
uv run --no-project scripts/backtest.py EXPORT_DIR --volume 281 --map-file MAPPING.json
```

- `--options '{"sensor_tolerance": 2.0}'` (or `--options-file`) sets tuning values.
- `--lock PARAMETER` keeps a parameter at its option value.
- `--days N` fits the last N days only.
- `--sensor-height` (default 0.5) and `--water-unit` (default m3) are for an export.

The roles of an export are the names of the setup fit (`tank_temperature`, `water_meter`, `dhw_energy`, `dhw_power`,
`dhw_heating`, `flow_temperature`, `return_temperature`, `bathroom_humidity`, `cold_water_temperature` and
`ambient_temperature`). An export with an `ambient_temperature` file replays the ambient sensor; without it the
`ambient_temperature` option is used all through. Before the ambient sensor's first row the replay uses the option too.

Ambient sensor evidence. On a month of history, the same fit with and without the ambient sensor (a basement air
sensor averaging 19.6 C, against the 20 C default) gave quiet-window estimates that were about 0.0001 per hour lower
(0.0039 against 0.0040 per hour for `k`), and no change in the charge errors (mean absolute error 1.52 against 1.51 K
with the fitted options). In a room close to the default the sensor is not an accuracy gain, but it removes the guess
and keeps `k` right in a room that is not at 20 C: a 4 K cooler room moves a quiet-window estimate by about 10 %
(`0.1375 / 36.45` against `0.1375 / 40.45`).

A rising mean charge error points at a wrong sensor height or a changed household: check the sensor height first.
