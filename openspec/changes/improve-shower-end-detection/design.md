# Design

## Context

See proposal.md, Why. The draw classifier is pure Python, beside the model. It decides per meter increase whether
a litre is mixed, and today a shower is "detected" exactly while the bathroom humidity holds: from the rise to the
fall below the window minimum plus half the rise. The same flag ends the shower in progress, so the shower flow
sample and the rolling flow ("Shower time remaining" with `flow_basis: current_shower`) last as long as the
humidity. The long-draw rule sets a second flag for the length of one session, whether or not a humidity sensor is
configured.

The classifier only sees time when it is called: on every meter or humidity reading, and on the runtime's tick every
5 minutes. The setup fit and `scripts/backtest.py` replay history through the same model, with the same 5-minute
tick.

A model state that fails to restore is dropped as a whole: the tank then starts charged at the tank sensor's
reading. The classifier's saved state is part of it, and today's restore requires every key it writes.

The evidence below is from the October export of the development installation (2026-10-01 to 2026-10-31: humidity,
bathroom temperature and water meter), replayed by scratch scripts during the exploration of 2026-11-05. Task 1
redoes it with the real classifier and adds November.

## Goals / Non-Goals

**Goals:**
- One shower lifecycle, separate from the humidity, so that the shower ends when the water stops, whatever started
  it.
- The shower end is seen on time in the runtime, not at the next 5-minute tick.
- Replays (setup fit, backtest) give the same classification as the runtime, whatever their tick.
- A rollback to the previous release keeps the model state.

**Non-Goals:**
- No change to the start rule, the session gap, the reclassify window or the shower flow learning itself.
- No new entity and no new diagnostics event: the shower flow event already marks a shower's end.

## Decisions

### D1: A shower lifecycle beside the humidity hold

The classifier keeps two things apart:
- **Humid:** today's per-sensor rule, unchanged. On at the rise above the window minimum, off below the window
  minimum plus half the rise.
- **Shower in progress:** starts on one of three triggers and ends by the water (D2).

```
                    bathroom becomes humid (rise edge)
   +--------+  --------------------------------------->  +-----------+
   |  idle  |                                           |  SHOWER   |  every litre is mixed
   +--------+  <-------------------+                    +-----------+
     ^   |                         |                       |     ^
     |   | no humidity sensor:     | not humid             |     | still humid and a session
     |   | a session of the        |                       |     | has lasted the next
     |   | long-draw duration      |       no water for    |     | shower time (M)
     |   +-------------------------|-----> the shower end  |     |
     |        (to SHOWER)          |       time (N)        v     |
     |                        +------------------------------------+
     +------------------------|  ended, humid: other draws, and   |
          not humid           |  no humidity edge can occur       |
                              +------------------------------------+
```

- The humidity start is the **edge** of humid, as today, so a bathroom that is still humid after a shower cannot
  restart one from the humidity. The edge state is saved (D5), so a restart in the humid tail does not create one.
- When a shower ends and the bathroom is no longer humid, the classifier is idle. When it is still humid, a new
  shower needs a draw of the next shower time (D3). Nothing else is needed for that state: it is "humid and no
  shower in progress".
- The binary sensor and `detected` mean "shower in progress". The rolling flow, the shower report and the mixed
  classification all follow that one flag, as they do today.

Alternative considered: keep humidity as the end and shorten the window, or end on a fall from the peak. Rejected:
in October the humidity had fallen only 1-3 points from its peak 10 minutes after the water stopped in most showers
(the bathroom stays at 85-90 %), so either rule would still be late or would need a threshold that also fires during
a shower. The bathroom temperature was rejected as well: it rose 0.2-0.9 K per shower, peaked 2-25 minutes after the
water stopped, and its sensor reported a median of 15 minutes apart.

### D2: The water ends a shower, dated at its deadline

A shower ends at `t_end = t_ref + N`, where `t_ref` is the later of its last meter increase and its start (its
start when it has drawn nothing, or when its last increase came before the start, as with litres a humidity edge
takes over), and `N` is the shower end time in minutes. Every call into the classifier first ends a shower whose
`t_end` is at or before the call's time, **dated `t_end`**, before it handles the new reading. So a meter increase
after `t_end` is classified as the first litre after the shower, whether the call comes from the runtime, the setup
fit or the backtest, and whatever their tick. A pause shorter than `N` keeps the shower: the next increase moves
`t_ref`. The shower's litres and minutes do not depend on the call time either. The shower flow event is logged by
the call that ends the shower, at that call's time: in the runtime the timer below makes that `t_end`; in a replay
it is the next reading or tick (decided 2026-11-05, group 2 review).

The runtime notices `t_end` on time with a one-shot timer: the model exposes the next shower end (`t_end` of the
shower in progress, or none), and the estimator reschedules a point-in-time callback to it after every update. The
callback runs the same path as the tick.

Alternatives considered:
- A 1-minute tick: still up to a minute late, and it runs the standing loss and the sensor bounds 5 times as often
  for no other gain.
- The 5-minute tick alone: the binary sensor and "Shower time remaining" would stay on the finished shower for up to
  10 minutes after the water stopped.

### D3: Defaults and bounds of the two new options

| Option | Default | Bounds, step | Unit |
|---|---|---|---|
| Shower end time (`shower_end_minutes`, N) | 5 | 2-30, 0.5 | min |
| Next shower time (`next_shower_minutes`, M) | 5 | 1-30, 0.5 | min |

- **N = 5 min.** Pauses within one wash were at most 2 minutes in October (1.6 and 2.0), and the spec keeps a
  3-minute pause as one shower. The second showers of a pair started 5.0 and 5.7 minutes after the first ended. N = 8
  merged the 5.7-minute pair. The shower end time must be longer than the session gap (default 60 s, configurable
  5-600 s), so that a session always ends before its shower does. Otherwise a pause longer than N but shorter than
  the gap would end the shower inside a session that has already lasted M, and the next litre would start a new
  shower at once, splitting one wash. The options form rejects a shower end time that is not longer than the session
  gap, with an error on the field (decided 2026-11-05, group 2 review).
- **M = 5 min.** In the humid tail, the draws of 2.0-4.5 minutes were the cold washbasin (the user, 2026-11-05),
  while the two second showers ran 6.7 and 30.5 minutes. Replayed with N = 5:

  | M | New showers in the humid tail | Litres counted as mixed in October |
  |---|---|---|
  | 3 min | 2 washbasin draws and both second showers | 2799 L |
  | 4 min | 1 washbasin draw and both second showers | 2772 L |
  | 5 min | both second showers only | 2749 L |
  | 6 min | both second showers only | 2749 L |

  The shipped rule counted 2934 L as mixed over the same month.
- **Effect on the energy balance.** A litre wrongly counted as mixed instead of as an other draw costs
  `((T_mix - T_cold) - share * (T_ch - T_cold)) / V` K of T_avg. At T_mix 38 C, T_cold 13.6 C, share 0.16, T_ch
  57.1 C and V 285 L that is 0.061 K per litre. The 185 L less mixed in October is about 11 K over 24 showers, so
  about 0.5 K per shower, all on the side of showing less hot water than there is.

### D4: The long-draw rule needs no humidity sensor

The classifier is told whether a humidity sensor is configured, through its options, from the entry's sources. It
does not infer it from readings, because a configured sensor may not have reported yet. With a sensor configured,
the long-draw duration starts nothing. In October, the draws of at least 3 minutes that the humidity did not catch
ran up to 8.1 minutes, apart from two: a 14.2-minute draw at 4.2 L/min with the humidity flat (the garden hose, the
user, 2026-11-05) and a 10.2-minute draw during an hour without humidity readings. A long-draw backup would only
have been right for the second, which belongs to the sensor outage (proposal, Out of scope).

A long-draw shower ends by D2 like any other, so a pause in it no longer ends it. Without a humidity sensor there is
no humid state, so the next shower time does not apply; a new shower after the end needs the long-draw duration
again.

The option keeps its place in the options form. Its description says that it applies only without a humidity
sensor.

### D5: Saved state and rollback

The classifier's saved state gains the time each shower started (for a shower with no water, D2) and saves the
humid edge state in the previous release's `was_detected` key (no separate key, decided 2026-11-05 in group 2). It
keeps writing every key the previous release reads (`long_active` as false), so that a rollback restores the model
instead of dropping it. Restore accepts a state without the
new keys: a shower without a start time uses its last increase, or the time of the next call.

### D6: Replays and the evidence

The setup fit and the backtest need no change for the rules: they run the classifier through the model, and D2
makes the result independent of their tick. The backtest's output is extended so the old and new rules can be
compared from it alone:
- the shower list gives each shower's start, end, litres, minutes and its flow sample. A shower's sample is the first
  one reported after its last litre and before the next draw counted as other, else "no sample";
- a separate list gives every shower flow sample the model reported (time, litres, minutes, flow), so samples of
  fragments and of small detections are visible too;
- the totals give the litres drawn, counted as mixed and reclassified, per options set.

The shower list counts the litres a detection reclassifies into the session they came from (decided 2026-11-05,
group 1 review: before, a reclassified shower read too few mixed litres or fell out of the list). The comparison
runs the backtest on the same export at the previous rule and at the change.

## Risks / Trade-offs

- [A second shower shorter than M while the bathroom is humid stays other draws, about 1.5-2 K for a 30 L shower.]
  → M is an option; October had none.
- [A wash with the water off for longer than N splits. Its second part counts as mixed only if it runs for M.]
  → N is an option; October's longest pause within a wash was 2 minutes.
- [A bath topped up after more than N with a draw shorter than M counts the top-up as other draws.] → The top-up is
  small against the fill, and the error is on the side of showing more.
- [An entry with both a humidity sensor and a long-draw duration changes behaviour.] → The README says so (BREAKING
  in the proposal). Shipped default is 0, so only an entry that set it is affected.
- [The `back_to_back` replay fixture expects both showers fully mixed.] → Checked on 2026-11-05: its first shower
  (88 L, 12.5 min) ends exactly 5.0 minutes before a 4 L draw, which a 66 s gap separates from the second shower
  (200 L, 30.5 min). Under the new rule the first shower ends at that 4 L draw, which stays an other draw, and the
  second shower starts after 5 minutes of its session with all of it reclassified. Both showers stay fully mixed,
  so the test should pass unchanged. The 4 L draw is the toilet-or-washbasin kind the change means to leave out.
- [A missed timer (for example during a restart) leaves the shower on.] → Every call ends a due shower first (D2),
  and the 5-minute tick still runs.

## Migration Plan

- Existing entries have no value for the two new options and use their defaults (integration-setup scenario
  "Existing entry after the update").
- Deploy and restart on the development installation with authorization (proposal, Impact). A shower in progress
  at the restart continues and ends by D2.
- Rollback: deploy the previous commit and restart. D5 keeps the model state.
