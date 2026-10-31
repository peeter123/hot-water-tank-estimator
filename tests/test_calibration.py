"""Tests for calibration: one test per scenario of the calibration spec, and the closure rules."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import random

import pytest

from custom_components.hot_water_tank_estimator.calibration import (
    CLOSURE,
    EXCLUDED,
    SENSOR_START,
    Calibrator,
    Closure,
    bounded_step,
    charge_error,
    fit_closures,
    heat_capacity,
    true_start_average,
)
from custom_components.hot_water_tank_estimator.model import (
    ModelOptions,
    Sources,
    TankModel,
)

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
VOLUME = 281.0
CAPACITY = heat_capacity(VOLUME)


def make_options(**overrides: float) -> ModelOptions:
    """Options for a 281 L tank, cold water at 14 C all year and the default loss."""
    values: dict[str, float] = {
        "volume": VOLUME,
        "cold_mean": 14.0,
        "cold_amplitude": 0.0,
    }
    values.update(overrides)
    return ModelOptions(**values)


class Rig:
    """A model with a calibrator, driven by hand: a counter and a heating binary sensor."""

    def __init__(
        self,
        sources: Sources | None = None,
        *,
        t_avg: float = 57.0,
        locks: frozenset[str] = frozenset(),
        measures_heat: bool = True,
        **overrides: float,
    ) -> None:
        """Create the rig with a charged tank at T0 and the counter at 100 kWh."""
        self.sources = sources or Sources(
            energy_counter=True, heating_binary=True, flow_return=True
        )
        options = make_options(**overrides)
        self.model = TankModel(options, self.sources, T0, t_avg, t_avg)
        self.cal = Calibrator(options, locks=locks, measures_heat=measures_heat)
        self.kwh = 100.0
        self.litres = 1000.0
        self.model.on_heating(T0, False) if self.sources.heating_binary else None
        self.call(T0, "on_energy", self.kwh)
        self.call(T0, "on_water_meter", self.litres, "L")

    def call(self, now: datetime, method: str, *args: object) -> list:
        """Call an input method, let the calibrator observe it and apply a changed option."""
        events = getattr(self.model, method)(now, *args)
        if self.cal.observe(self.model, events, now):
            self.model.set_options(self.cal.options)
        return events

    def draw(self, now: datetime, litres: float) -> None:
        """Draw water through the meter."""
        self.litres += litres
        self.call(now, "on_water_meter", self.litres, "L")

    def run(
        self,
        start: datetime,
        minutes: int,
        kwh: float,
        charge: float | None,
        *,
        draws: dict[int, float] | None = None,
    ) -> datetime:
        """Heat for `minutes` with `kwh` of energy (one step a minute), ending at `charge` C.

        Args:
            start: When the run starts.
            minutes: The run length.
            kwh: The energy of the run.
            charge: The flow and return temperature at the end, None for no reading.
            draws: Litres drawn in the minute after the start, by minute.

        Returns:
            The end of the run.
        """
        self.call(start, "on_heating", True)
        for minute in range(1, minutes + 1):
            now = start + minute * MINUTE
            self.kwh += kwh / minutes
            self.call(now, "on_energy", self.kwh)
            if draws and minute in draws:
                self.draw(now, draws[minute])
        end = start + minutes * MINUTE
        if charge is not None:
            self.call(end, "on_flow_return", charge, charge)
        self.call(end, "on_heating", False)
        return end


def make_closure(**overrides: object) -> Closure:
    """A valid closure on the 281 L tank with figures that need no model."""
    values: dict[str, object] = {
        "run_start": T0,
        "run_end": T0 + HOUR,
        "t_charge": 55.0,
        "t_ch_prev": 57.0,
        "run_start_t_avg": 40.0,
        "energy_kwh": 5.0,
        "startup_kwh": 1.8,
        "share": 0.2,
        "loss_coefficient": 0.004,
        "volume": VOLUME,
        "hours": 20.0,
        "loss": 700.0,
        "other": 20.0,
        "mixed": 5.0,
        "loss_run": 30.0,
        "other_run": 0.0,
        "mixed_run": 0.0,
        "status": CLOSURE,
    }
    values.update(overrides)
    return Closure(**values)  # type: ignore[arg-type]


def synthetic_closures(
    count: int, *, k: float, share: float, startup: float, seed: int = 1
) -> list[Closure]:
    """Closures whose charged temperature follows from known parameters."""
    rng = random.Random(seed)
    closures = []
    for index in range(count):
        loss = rng.uniform(150, 1500)
        other = rng.uniform(1, 40)
        mixed = rng.choice([0.0, 0.0, rng.uniform(5, 25)])
        energy = rng.uniform(3, 11)
        t_prev = rng.uniform(50, 60)
        # t_ch_prev - t_charge + E / C - mixed = k * loss + share * other + S / C
        t_charge = (
            t_prev
            + energy / CAPACITY
            - mixed
            - k * loss
            - share * other
            - startup / CAPACITY
        )
        closures.append(
            make_closure(
                run_end=T0 + index * HOUR,
                t_charge=t_charge,
                t_ch_prev=t_prev,
                energy_kwh=energy,
                loss=loss,
                other=other,
                mixed=mixed,
            )
        )
    return closures


# ----- the closure equation ---------------------------------------------------------------


def test_error_at_a_recovery_run() -> None:
    """E_run 10.64 kWh, T_charge 49.9 C, S 1.8 kWh and T_avg 25.0 C: true start 22.9 C, error +2.1 K."""
    closure = make_closure(
        t_charge=49.9, energy_kwh=10.64, run_start_t_avg=25.0, loss_run=0.0
    )
    true_start = true_start_average(closure, 1.8, 0.2, 0.004)
    assert true_start == pytest.approx(49.9 - 8.84 * 1000 / 326.8, abs=0.01)
    assert true_start == pytest.approx(22.9, abs=0.05)
    error = charge_error(closure, 1.8, 0.2, 0.004)
    assert error == pytest.approx(2.1, abs=0.06)


def test_error_at_a_recovery_run_from_the_model() -> None:
    """The same run through the model: the charge event gives the closure and its error."""
    rig = Rig(t_avg=25.0, startup_energy=1.8, loss_coefficient=0.0, sensor_height=0.5)
    rig.run(T0 + HOUR, 60, 10.64, 49.9)
    rig.cal.flush()
    (closure,) = rig.cal.closures
    assert closure.energy_kwh == pytest.approx(10.64)
    assert closure.error == pytest.approx(2.15, abs=0.01)


def test_in_run_draws_and_loss_belong_to_the_closure() -> None:
    """With the model's own parameters the true start is the model's start, even with a shower in the run."""
    rig = Rig(startup_energy=1.8, loss_coefficient=0.004, humidity_rise=6.0)
    rig.sources = rig.model.sources
    rig.call(T0 + HOUR, "on_humidity", "bath", 50.0)
    rig.draw(T0 + 2 * HOUR, 30.0)  # an other draw before the first run
    # A run with a shower in it. Its charge is what the energy balance gives at its end.
    start = T0 + 3 * HOUR
    rig.call(start, "on_heating", True)
    rig.call(start + 5 * MINUTE, "on_humidity", "bath", 50.0)
    rig.call(start + 10 * MINUTE, "on_humidity", "bath", 70.0)
    rig.draw(start + 10 * MINUTE, 5.0)
    for minute in range(11, 61):
        now = start + minute * MINUTE
        if minute == 30:
            rig.call(
                now, "on_humidity", "bath", 50.0
            )  # the room has dried: the shower is over
        rig.kwh += 0.1
        rig.call(now, "on_energy", rig.kwh)
        rig.draw(now, 2.0)
    end = start + 61 * MINUTE
    # The model's tank average now is the true one at the run end.
    expected = rig.model.t_avg
    rig.call(end, "on_flow_return", expected, expected)
    rig.call(end, "on_heating", False)
    rig.cal.flush()
    (closure,) = rig.cal.closures
    assert closure.mixed_run > 1.0 and closure.other_run > 0.0
    assert closure.error == pytest.approx(0.0, abs=0.02)
    # Leaving the in-run terms out gives an error of several tenths of a kelvin.
    without = replace(closure, mixed_run=0.0, other_run=0.0, loss_run=0.0)
    assert abs(charge_error(without, 1.8, 0.2, 0.004)) > 0.5


def test_bound_applied_during_the_interval() -> None:
    """A sensor bound that raised T_avg by 3 K or more leaves the interval's sums as they were."""
    rig = Rig(t_avg=57.0, startup_energy=1.8, loss_coefficient=0.0)
    rig.call(T0 + 5 * MINUTE, "on_tank_sensor", 57.0)
    rig.draw(T0 + 10 * MINUTE, 50.0)  # other draw: 50 * 0.2 * 43 / 281 = 1.53 K
    rig.call(T0 + 20 * MINUTE, "on_humidity", "bath", 50.0)
    rig.call(T0 + 30 * MINUTE, "on_humidity", "bath", 70.0)
    for minute in (30, 31, 32):  # mixed draws: 3 * 95 * 24 / 281 = 24.3 K
        rig.draw(T0 + minute * MINUTE, 95.0)
    sums = rig.model.interval_sums
    balance = 57.0 - 50 * 0.2 * 43 / 281 - 3 * 95 * 24 / 281
    # The sensor still reads hot, so the lower bound lifts T_avg far above the balance.
    assert rig.model.t_avg > balance + 3.0
    assert sums.other == pytest.approx(50 * 43 / 281)
    assert sums.mixed == pytest.approx(3 * 95 * 24 / 281, rel=1e-3)
    rig.call(T0 + 33 * MINUTE, "on_tank_sensor", 57.0)
    assert rig.model.interval_sums.other == sums.other
    assert rig.model.interval_sums.mixed == sums.mixed


# ----- the fit --------------------------------------------------------------------------------


def test_too_few_intervals() -> None:
    """With 4 intervals stored, the option values stay in use."""
    cal = Calibrator(make_options())
    for closure in synthetic_closures(4, k=0.006, share=0.4, startup=2.0):
        cal.add_closure(closure)
    assert cal.sample_count == 4
    assert cal.values == {}
    assert cal.options == make_options()
    assert cal.source_of("other_hot_share") == "option"


def test_step_limit() -> None:
    """The share in use is 0.2 and the fit gives 0.5: it becomes 0.35, a quarter of the 0-0.6 range up."""
    locks = frozenset({"loss_coefficient", "startup_energy"})
    cal = Calibrator(make_options(startup_energy=1.8), locks=locks)
    closures = synthetic_closures(6, k=0.004, share=0.5, startup=1.8)
    for closure in closures[:5]:
        cal.add_closure(closure)
    assert cal.options.other_hot_share == pytest.approx(0.35)
    assert cal.source_of("other_hot_share") == "learned"
    # The next update moves on towards 0.5.
    cal.add_closure(closures[5])
    assert cal.options.other_hot_share == pytest.approx(0.5)


def test_locked_parameter() -> None:
    """With the share locked at 0.25, the model uses 0.25 and learning neither changes nor reports it."""
    cal = Calibrator(
        make_options(other_hot_share=0.25), locks=frozenset({"other_hot_share"})
    )
    for closure in synthetic_closures(8, k=0.006, share=0.5, startup=1.0):
        cal.add_closure(closure)
    assert cal.options.other_hot_share == 0.25
    assert "other_hot_share" not in cal.values
    assert cal.source_of("other_hot_share") == "locked"
    assert cal.source_of("startup_energy") == "learned"


def test_out_of_bounds_fit() -> None:
    """The start-up energy in use is 2.9 kWh and a fit gives 4.2 kWh: the learned value is 3 kWh."""
    assert bounded_step("startup_energy", 2.9, 4.2) == pytest.approx(3.0)
    assert bounded_step("startup_energy", 2.9, -1.0) == pytest.approx(2.15)
    cal = Calibrator(make_options(startup_energy=2.9))
    closures = synthetic_closures(5, k=0.004, share=0.2, startup=4.2)
    for closure in closures:
        cal.add_closure(closure)
    # The first update is the fit at 5 intervals: 4.2 is limited to the bound 3.0.
    assert cal.options.startup_energy == pytest.approx(3.0)
    assert cal.source_of("startup_energy") == "learned"


def test_synthetic_intervals_recover_the_parameters() -> None:
    """Intervals generated from known parameters give them back within 5 %, also with noise."""
    truth = {"loss_coefficient": 0.005, "other_hot_share": 0.25, "startup_energy": 1.5}
    closures = synthetic_closures(30, k=0.005, share=0.25, startup=1.5)
    in_use = {"loss_coefficient": 0.004, "other_hot_share": 0.2, "startup_energy": 0.0}
    fit = fit_closures(closures, in_use, forgetting=1.0)
    assert fit is not None
    for name, value in truth.items():
        assert fit[name] == pytest.approx(value, rel=0.05)
    rng = random.Random(7)
    noisy = [replace(c, t_charge=c.t_charge + rng.gauss(0, 0.3)) for c in closures]
    fit = fit_closures(noisy, in_use, forgetting=0.95)
    assert fit is not None
    for name, value in truth.items():
        assert fit[name] == pytest.approx(value, rel=0.15)
    # The calibrator applies it in steps and ends on the truth.
    cal = Calibrator(make_options())
    for closure in closures:
        cal.add_closure(closure)
    for name, value in truth.items():
        assert cal.value_of(name) == pytest.approx(value, rel=0.05)


def test_fit_weights_newer_intervals_more() -> None:
    """With a forgetting factor below 1 the fit follows a change of the share."""
    old = synthetic_closures(10, k=0.004, share=0.1, startup=1.8, seed=3)
    new = synthetic_closures(10, k=0.004, share=0.4, startup=1.8, seed=4)
    in_use = {"loss_coefficient": 0.004, "other_hot_share": 0.2, "startup_energy": 1.8}
    locks = ("loss_coefficient", "startup_energy")
    flat = fit_closures([*old, *new], in_use, locks, forgetting=1.0)
    weighted = fit_closures([*old, *new], in_use, locks, forgetting=0.95)
    assert flat is not None and weighted is not None
    assert 0.1 < flat["other_hot_share"] < weighted["other_hot_share"] < 0.4


def test_fit_needs_determined_unknowns() -> None:
    """Closures without any draw leave the share undetermined: no fit."""
    closures = [
        replace(c, other=0.0)
        for c in synthetic_closures(6, k=0.004, share=0.2, startup=1.8)
    ]
    assert fit_closures(closures, {}, ()) is None


# ----- from model events to closures ---------------------------------------------------------


def test_closures_from_the_model() -> None:
    """The first charge is a sensor start; the next ones are closures with errors."""
    rig = Rig(startup_energy=1.8)
    end = rig.run(T0 + HOUR, 60, 5.0, 55.0)
    rig.draw(end + HOUR, 30.0)
    end = rig.run(end + 3 * HOUR, 60, 5.0, 56.0)
    rig.cal.flush()
    first, second = rig.cal.closures
    assert first.status == SENSOR_START
    assert second.status == CLOSURE
    assert second.t_ch_prev == pytest.approx(55.0, abs=0.01)
    assert second.hours == pytest.approx(4.0, abs=0.1)
    assert rig.cal.sample_count == 1


def test_short_runs_are_excluded() -> None:
    """A run shorter than 15 minutes does not mix the tank."""
    rig = Rig()
    end = rig.run(T0 + HOUR, 60, 5.0, 55.0)
    rig.run(end + 2 * HOUR, 14, 1.0, 55.0)
    rig.cal.flush()
    closure = rig.cal.closures[-1]
    assert closure.status == EXCLUDED
    assert closure.reason == "short_run"
    assert rig.cal.sample_count == 0


def test_a_source_unavailable_for_over_ten_percent_is_excluded() -> None:
    """The water meter was unavailable for 2 of 10 hours: the interval is not used."""
    rig = Rig()
    end = rig.run(T0 + HOUR, 60, 5.0, 55.0)
    rig.call(end + HOUR, "on_water_meter", None, "L")
    rig.call(end + 3 * HOUR, "on_water_meter", rig.litres, "L")
    rig.call(end + 8 * HOUR, "tick")
    rig.run(end + 9 * HOUR, 60, 5.0, 55.0)
    rig.cal.flush()
    closure = rig.cal.closures[-1]
    assert closure.status == EXCLUDED
    assert closure.reason == "source_unavailable:water_meter"
    # Under 10 %: 1 of 10 hours is fine.
    rig = Rig()
    end = rig.run(T0 + HOUR, 60, 5.0, 55.0)
    rig.call(end + HOUR, "on_water_meter", None, "L")
    rig.call(end + 2 * HOUR, "on_water_meter", rig.litres, "L")
    rig.call(end + 8 * HOUR, "tick")
    rig.run(end + 9 * HOUR, 60, 5.0, 55.0)
    rig.cal.flush()
    assert rig.cal.closures[-1].status == CLOSURE


def test_the_cold_shower_button_excludes_the_interval() -> None:
    """The reset of the model by the button makes the interval, and the one it starts, no closure."""
    rig = Rig(t_avg=57.0)
    end = rig.run(T0 + HOUR, 60, 5.0, 55.0)
    rig.call(end + HOUR, "on_tank_sensor", 55.0)
    rig.cal.cold_shower(rig.model, end + 2 * HOUR)
    rig.run(end + 5 * HOUR, 60, 8.0, 55.0)
    rig.cal.flush()
    assert rig.cal.closures[-1].status == EXCLUDED
    assert rig.cal.closures[-1].reason == "after_manual_reset"
    # The interval after that is a closure again.
    rig.run(rig.cal.closures[-1].run_end + 5 * HOUR, 60, 5.0, 55.0)
    rig.cal.flush()
    assert rig.cal.closures[-1].status == CLOSURE


def test_a_run_without_a_charged_temperature_is_excluded_with_the_next_interval() -> (
    None
):
    """No flow, return or tank sensor: the model keeps its values, and the next interval has no charged start."""
    rig = Rig()
    rig.run(T0 + HOUR, 60, 5.0, None)
    end = rig.run(T0 + 4 * HOUR, 60, 5.0, 55.0)
    rig.cal.flush()
    first, second = rig.cal.closures
    assert (first.status, first.reason) == (EXCLUDED, "no_charge_temperature")
    assert first.error is None
    assert (second.status, second.reason) == (EXCLUDED, "after_no_charge_temperature")
    rig.run(end + 3 * HOUR, 60, 5.0, 55.0)
    rig.cal.flush()
    assert rig.cal.closures[-1].status == CLOSURE


def test_counter_increases_after_the_run_end_count_towards_the_run() -> None:
    """A counter step 5 minutes after a binary-sensor run end is part of the run; one after 11 is not."""
    rig = Rig()
    end = rig.run(T0 + HOUR, 60, 5.0, 55.0)
    rig.kwh += 0.7
    rig.call(end + 5 * MINUTE, "on_energy", rig.kwh)
    rig.kwh += 0.4
    rig.call(end + 11 * MINUTE, "on_energy", rig.kwh)
    rig.call(end + 12 * MINUTE, "tick")
    (closure,) = rig.cal.closures
    assert closure.energy_kwh == pytest.approx(5.7)
    assert not rig.model.heating


def test_heat_measurement_is_needed_for_closures() -> None:
    """With only a heating binary sensor there are no closures, and the share and start-up energy stay."""
    rig = Rig(Sources(heating_binary=True), measures_heat=False)
    rig.run(T0 + HOUR, 60, 0.0, None)
    rig.run(T0 + 4 * HOUR, 60, 0.0, None)
    rig.cal.flush()
    assert rig.cal.closures == []
    assert rig.cal.values == {}


def test_binary_only_heating_source() -> None:
    """Only a heating-active binary sensor: no charge error, and the share and start-up energy stay."""
    rig = Rig(Sources(heating_binary=True), measures_heat=False, other_hot_share=0.25)
    end = T0
    for _ in range(6):
        end = rig.run(end + 4 * HOUR, 60, 0.0, None)
        rig.draw(end + HOUR, 20.0)
    rig.cal.flush()
    assert rig.cal.closures == []
    assert rig.cal.sample_count == 0
    assert rig.cal.last_error is None
    assert rig.cal.mean_abs_error() is None
    assert rig.cal.options.other_hot_share == 0.25
    assert rig.cal.source_of("other_hot_share") == "option"
    assert rig.cal.source_of("startup_energy") == "option"


def test_calibration_state_survives_a_restart() -> None:
    """After learning a share of 0.22 the restored calibrator uses 0.22."""
    locks = frozenset({"loss_coefficient", "startup_energy"})
    cal = Calibrator(make_options(startup_energy=1.8), locks=locks)
    for closure in synthetic_closures(8, k=0.004, share=0.22, startup=1.8):
        cal.add_closure(closure)
    assert cal.options.other_hot_share == pytest.approx(0.22, abs=0.01)
    saved = json.loads(json.dumps(cal.to_dict()))
    restored = Calibrator(make_options(startup_energy=1.8), locks=locks)
    restored.restore(saved)
    assert restored.options == cal.options
    assert restored.closures == cal.closures
    assert restored.source_of("other_hot_share") == "learned"
    with pytest.raises(ValueError, match="Invalid calibration state"):
        restored.restore({})


def test_diagnostic_figures() -> None:
    """The samples, the last charge error and the mean absolute error of the last 10."""
    cal = Calibrator(make_options())
    errors = [1.0, -3.0, 2.0]
    for index, error in enumerate(errors):
        cal.add_closure(make_closure(run_end=T0 + index * HOUR, error=error))
    cal.add_closure(make_closure(status=EXCLUDED, reason="short_run", error=9.0))
    assert cal.sample_count == 3
    assert cal.last_error == 2.0
    assert cal.mean_abs_error() == pytest.approx(2.0)


def test_mean_error_covers_the_last_ten_closures() -> None:
    """Two old closures of 100 K fall out of the mean once 10 newer ones are stored."""
    cal = Calibrator(make_options(), learn=False)
    for index, error in enumerate([100.0, -100.0, *[1.0, -3.0] * 5]):
        cal.add_closure(make_closure(run_end=T0 + index * HOUR, error=error))
    assert cal.sample_count == 12
    assert cal.mean_abs_error() == pytest.approx(2.0)
    assert cal.mean_abs_error(last=None) == pytest.approx((200 + 20) / 12)
    assert cal.last_error == -3.0


def test_after_a_week_of_use() -> None:
    """Nine closures: the samples count them, the errors show the last and the mean of all nine."""
    cal = Calibrator(make_options())
    closures = synthetic_closures(9, k=0.004, share=0.3, startup=1.8)
    for index, closure in enumerate(closures):
        cal.add_closure(replace(closure, error=float(index - 4)))
    assert cal.sample_count == 9
    assert cal.last_error == 4.0
    assert cal.mean_abs_error() == pytest.approx(20 / 9)
    assert cal.source_of("other_hot_share") == "learned"
    assert cal.source_of("usable_fraction") == "option"


def test_a_simulated_month_recovers_the_parameters() -> None:
    """A model with known parameters produces the charges; the calibrator, started on others, finds them."""
    rng = random.Random(5)
    true = {"loss_coefficient": 0.006, "other_hot_share": 0.3, "startup_energy": 1.4}
    sources = Sources(
        energy_counter=True,
        heating_binary=True,
        flow_return=True,
        humidity_sensors=("bath",),
    )
    truth = TankModel(make_options(**true), sources, T0, 57.0, 57.0)
    model = TankModel(make_options(), sources, T0, 57.0, 57.0)
    cal = Calibrator(make_options())
    kwh, litres = 100.0, 1000.0

    def both(now: datetime, method: str, *args: object) -> None:
        getattr(truth, method)(now, *args)
        events = getattr(model, method)(now, *args)
        if cal.observe(model, events, now):
            model.set_options(cal.options)

    def draw(now: datetime, amount: float) -> None:
        nonlocal litres
        litres += amount
        both(now, "on_water_meter", litres, "L")

    both(T0, "on_heating", False)
    both(T0, "on_energy", kwh)
    both(T0, "on_water_meter", litres, "L")
    both(T0, "on_humidity", "bath", 50.0)
    midnight = T0.replace(hour=0)
    for day in range(1, 31):
        base = midnight + timedelta(days=day)
        for offset in (7.0, 7.2, 8.5):
            draw(base + timedelta(hours=offset), rng.uniform(2, 15))
        if rng.random() < 0.7:
            start = base + timedelta(hours=11 + rng.uniform(0, 1))
            capacity = heat_capacity(VOLUME)
            target = rng.uniform(50, 58)
            energy = max(
                1.5, (target - truth.t_avg) * capacity + true["startup_energy"]
            )
            both(start, "on_heating", True)
            for minute in range(1, 61):
                kwh += energy / 60
                both(start + minute * MINUTE, "on_energy", kwh)
                # The heater's flow and return read the tank, a minute at a time.
                both(
                    start + minute * MINUTE, "on_flow_return", truth.t_avg, truth.t_avg
                )
            both(start + 61 * MINUTE, "on_heating", False)
        draw(base + timedelta(hours=13.5), rng.uniform(2, 15))
        if rng.random() < 0.6:
            both(base + timedelta(hours=18, minutes=20), "on_humidity", "bath", 50.0)
            both(base + timedelta(hours=18, minutes=30), "on_humidity", "bath", 72.0)
            for minute in range(6):
                draw(
                    base + timedelta(hours=18.5, minutes=2 * minute),
                    rng.uniform(15, 25),
                )
            both(base + timedelta(hours=19, minutes=40), "on_humidity", "bath", 50.0)
        draw(base + timedelta(hours=21), rng.uniform(2, 15))
        both(base + timedelta(hours=23), "tick")
    cal.flush()
    assert cal.sample_count >= 15
    for name, value in true.items():
        assert cal.value_of(name) == pytest.approx(value, rel=0.05)
    assert cal.mean_abs_error() < 0.2


# ----- loss from quiet windows -------------------------------------------------------------


def quiet_rig() -> Rig:
    """A charged tank at 57 C with T_ambient 20 C, sensor reading 57.0 C."""
    rig = Rig(sensor_tolerance=1.5)
    rig.call(T0, "on_tank_sensor", 57.0)
    return rig


def test_quiet_night() -> None:
    """The sensor falls from 57.0 to 55.9 C over 8 hours: k is 0.1375 / 36.45 = 0.0038 per hour."""
    rig = quiet_rig()
    for hour in range(1, 9):
        rig.call(T0 + hour * HOUR, "on_tank_sensor", 57.0 - 1.1 * hour / 8)
    assert rig.cal.quiet_estimates == []
    rig.draw(T0 + 8 * HOUR, 5.0)  # the window ends with a draw
    (estimate,) = rig.cal.quiet_estimates
    assert estimate == pytest.approx(0.0038, abs=0.0001)
    # There are no closures yet, so the estimate is the loss coefficient in use.
    assert rig.cal.options.loss_coefficient == pytest.approx(estimate)
    assert rig.cal.source_of("loss_coefficient") == "learned"


def test_a_window_with_a_draw_is_skipped() -> None:
    """A draw splits 7 quiet hours into windows of 3 and 4 hours: neither counts."""
    rig = quiet_rig()
    for hour in range(1, 8):
        rig.call(T0 + hour * HOUR, "on_tank_sensor", 57.0 - 0.14 * hour)
        if hour == 3:
            rig.draw(T0 + hour * HOUR, 1.0)
    rig.call(T0 + 7 * HOUR, "on_heating", True)
    assert rig.cal.quiet_estimates == []
    assert rig.cal.values == {}


def test_a_window_ends_when_the_sensor_leaves_the_charged_temperature() -> None:
    """The estimate uses only the time while the sensor reads within the tolerance of T_ch."""
    rig = quiet_rig()
    for hour in range(1, 7):
        rig.call(T0 + hour * HOUR, "on_tank_sensor", 57.0 - 0.14 * hour)
    assert rig.cal.quiet_estimates == []
    rig.call(T0 + 7 * HOUR, "on_tank_sensor", 50.0)  # a draw nobody counted
    (estimate,) = rig.cal.quiet_estimates
    assert estimate == pytest.approx(0.0038, abs=0.0006)


def test_closures_take_precedence_over_fewer_than_three_quiet_windows() -> None:
    """With fewer than 3 quiet estimates, 5 intervals set the loss coefficient, not the window."""
    rig = quiet_rig()
    for closure in synthetic_closures(6, k=0.009, share=0.2, startup=1.8):
        rig.cal.add_closure(closure)
    after_fit = rig.cal.options.loss_coefficient
    for hour in range(1, 9):
        rig.call(T0 + hour * HOUR, "on_tank_sensor", 57.0 - 1.1 * hour / 8)
    rig.draw(T0 + 8 * HOUR, 5.0)
    assert rig.cal.quiet_estimates
    assert rig.cal.options.loss_coefficient == after_fit


# ----- thermocline width from the first sensor drop ----------------------------------------


def test_sensor_starts_to_fall() -> None:
    """H is 0.5 and the energy balance's cold fraction is 0.33 at the first drop: the width is 0.34."""
    rig = Rig(loss_coefficient=0.0, cold_mean=10.0)
    rig.call(T0, "on_tank_sensor", 57.0)
    end = rig.run(T0 + HOUR, 60, 3.0, 57.0)
    rig.call(end + MINUTE, "on_tank_sensor", 57.0)
    # Mixed draws until f = 0.33: 0.33 * 47 K * 281 L / (38 - 10) = 155.7 L.
    rig.call(end + 10 * MINUTE, "on_humidity", "bath", 50.0)
    rig.call(end + 20 * MINUTE, "on_humidity", "bath", 70.0)
    rig.draw(end + 20 * MINUTE, 77.85)
    rig.draw(end + 21 * MINUTE, 77.85)
    assert rig.model.balance_cold_fraction == pytest.approx(0.33, abs=0.001)
    assert rig.cal.width_estimates == []
    rig.call(end + 22 * MINUTE, "on_tank_sensor", 54.0)
    (estimate,) = rig.cal.width_estimates
    assert estimate == pytest.approx(0.34, abs=0.005)
    # Applied only after 3 estimates, as the mean of the last 10.
    assert rig.cal.options.thermocline_width == 0.35
    assert rig.cal.values == {}


def test_width_is_applied_after_three_estimates_within_bounds() -> None:
    """Three estimates give their mean, within the bounds and one step at most."""
    cal = Calibrator(make_options())
    cal.width_estimates = [0.5, 0.58]
    rig = Rig(loss_coefficient=0.0, cold_mean=10.0)
    rig.cal = cal
    rig.call(T0, "on_tank_sensor", 57.0)
    end = rig.run(T0 + HOUR, 60, 3.0, 57.0)
    rig.call(end + MINUTE, "on_tank_sensor", 57.0)
    rig.call(end + 10 * MINUTE, "on_humidity", "bath", 50.0)
    rig.call(end + 20 * MINUTE, "on_humidity", "bath", 70.0)
    rig.draw(end + 20 * MINUTE, 20.0)  # f is 0.04: the estimate 0.92 is limited to 0.6
    rig.call(end + 21 * MINUTE, "on_tank_sensor", 54.0)
    assert cal.width_estimates[-1] == pytest.approx(0.6)
    # The mean of 0.5, 0.58 and 0.6 is 0.56, 0.21 above 0.35: one step is (0.6 - 0.1) / 4.
    assert cal.options.thermocline_width == pytest.approx(0.35 + 0.125)


# ----- the button -------------------------------------------------------------------------


def test_k_is_held_at_the_quiet_window_mean() -> None:
    """From 3 quiet estimates the closure fit leaves k alone and fits the share and S."""
    closures = synthetic_closures(8, k=0.009, share=0.3, startup=1.8)
    held = Calibrator(make_options())
    held.quiet_estimates = [0.009, 0.009, 0.009]
    for closure in closures:
        held.add_closure(closure)
    # k is not fitted from the closures: it steps to the quiet-window mean.
    assert held.value_of("loss_coefficient") == pytest.approx(0.009)
    # With k held at the true value, the other two are found.
    held = Calibrator(make_options(loss_coefficient=0.009))
    held.quiet_estimates = [0.009, 0.009, 0.009]
    for closure in closures:
        held.add_closure(closure)
    assert held.value_of("other_hot_share") == pytest.approx(0.3, rel=0.02)
    assert held.value_of("startup_energy") == pytest.approx(1.8, rel=0.02)
    # With 2 estimates the closures fit k too.
    free = Calibrator(make_options())
    free.quiet_estimates = [0.009, 0.009]
    for closure in closures:
        free.add_closure(closure)
    assert free.source_of("loss_coefficient") == "learned"
    assert free.value_of("loss_coefficient") == pytest.approx(0.009, rel=0.02)


def test_the_hold_steps_k_towards_the_quiet_mean() -> None:
    """A closure fit moved k far away; with the third quiet estimate the next fit steps k back."""
    closures = synthetic_closures(8, k=0.012, share=0.3, startup=1.8)
    cal = Calibrator(make_options())
    for closure in closures[:5]:
        cal.add_closure(closure)
    far = cal.value_of("loss_coefficient")
    assert far > 0.0070  # the closures alone moved k one step up
    cal.quiet_estimates = [0.004, 0.004, 0.004]
    cal.add_closure(closures[5])
    stepped = cal.value_of("loss_coefficient")
    assert stepped == pytest.approx(far - 0.0035)
    cal.add_closure(closures[6])
    assert cal.value_of("loss_coefficient") == pytest.approx(0.004)


def test_three_quiet_windows_set_k_before_five_intervals() -> None:
    """The mean of 3 estimates is k in use, step-limited like every learned update."""
    rig = quiet_rig()
    rig.cal.base = replace(rig.cal.base, loss_coefficient=0.001)
    rig.model.set_options(rig.cal.options)
    rig.cal.quiet_estimates = [0.0048, 0.0048]
    # A fall of 1.4 K in 8 hours: the estimate 0.175 / 36.3 = 0.0048 is 0.0038 above k in use.
    for hour in range(1, 9):
        rig.call(T0 + hour * HOUR, "on_tank_sensor", 57.0 - 1.4 * hour / 8)
    rig.draw(T0 + 8 * HOUR, 5.0)
    assert len(rig.cal.quiet_estimates) == 3
    assert rig.cal.options.loss_coefficient == pytest.approx(0.001 + 0.0035)


def test_a_quiet_window_opens_an_hour_after_a_run_end() -> None:
    """The sensor still settles right after a run: a window of 5.5 h from the run end does not count."""

    def estimates(draw_after: timedelta) -> list[float]:
        rig = Rig(sensor_tolerance=1.5)
        rig.call(T0, "on_tank_sensor", 57.0)
        end = rig.run(T0 + HOUR, 60, 3.0, 57.0)
        hour = 0
        while timedelta(hours=hour) < draw_after:
            rig.call(end + timedelta(hours=hour), "on_tank_sensor", 57.0 - 0.14 * hour)
            hour += 1
        rig.draw(end + draw_after, 5.0)
        return rig.cal.quiet_estimates

    assert estimates(timedelta(hours=5.5)) == []
    (estimate,) = estimates(timedelta(hours=7))
    assert estimate == pytest.approx(0.0038, abs=0.0008)


def test_removing_a_lock_discards_the_value_learned_before_it() -> None:
    """After the lock goes, the option value applies until the next fit."""
    cal = Calibrator(make_options())
    closures = synthetic_closures(6, k=0.004, share=0.5, startup=1.8)
    for closure in closures[:5]:
        cal.add_closure(closure)
    assert cal.options.other_hot_share != 0.2
    cal.set_locks({"other_hot_share"})
    assert cal.options.other_hot_share == 0.2
    assert cal.source_of("other_hot_share") == "locked"
    cal.set_locks(set())
    assert "other_hot_share" not in cal.values
    assert cal.options.other_hot_share == 0.2
    assert cal.source_of("other_hot_share") == "option"
    # The other learned values stay.
    assert cal.source_of("startup_energy") == "learned"
    # The next fit learns it again.
    cal.add_closure(closures[5])
    assert cal.source_of("other_hot_share") == "learned"


def test_the_waiting_closure_survives_a_restart() -> None:
    """A run that ended a minute ago and may still get counter lag is part of the saved state."""
    rig = Rig()
    end = rig.run(T0 + HOUR, 60, 5.0, 55.0)
    saved = json.loads(json.dumps(rig.cal.to_dict()))
    assert saved["pending"] is not None
    restored = Calibrator(make_options())
    restored.restore(saved)
    rig.kwh += 0.5
    restored.observe(
        rig.model,
        rig.model.on_energy(end + 5 * MINUTE, rig.kwh),
        end + 5 * MINUTE,
    )
    restored.flush()
    (closure,) = restored.closures
    assert closure.energy_kwh == pytest.approx(5.5)
    assert restored.to_dict()["pending"] is None


def test_the_reset_marker_survives_a_restart() -> None:
    """After a button reset, the next interval is still excluded once the state is restored."""
    rig = Rig()
    rig.call(T0 + HOUR, "on_tank_sensor", 55.0)
    rig.cal.cold_shower(rig.model, T0 + 2 * HOUR)
    restored = Calibrator(make_options())
    restored.restore(json.loads(json.dumps(rig.cal.to_dict())))
    rig.cal = restored
    rig.run(T0 + 5 * HOUR, 60, 5.0, 55.0)
    restored.flush()
    assert restored.closures[-1].reason == "after_manual_reset"


def test_the_button_is_limited_to_the_bounds_of_the_usable_fraction() -> None:
    """A cold fraction under 0.5 gives 0.5, one over 0.98 gives 0.98."""
    low = Rig(t_avg=57.0, loss_coefficient=0.0, cold_mean=14.0)
    low.model.set_state(T0, t_avg=57.0 - 0.3 * 43)
    low.cal.cold_shower(low.model, T0 + MINUTE)
    assert low.model.options.usable_fraction == pytest.approx(0.5)
    assert low.model.tank_litres_exact == pytest.approx(0.0)
    high = Rig(t_avg=57.0, loss_coefficient=0.0, cold_mean=14.0)
    high.model.set_state(T0, t_avg=0.0)
    assert high.model.cold_fraction == pytest.approx(1.0)
    high.cal.cold_shower(high.model, T0 + MINUTE)
    assert high.model.options.usable_fraction == pytest.approx(0.98)


def test_a_locked_usable_fraction_is_not_learned_by_the_button() -> None:
    """The button still empties the model, but a locked fraction stays."""
    rig = Rig(t_avg=57.0, loss_coefficient=0.0, cold_mean=14.0)
    rig.cal.set_locks({"usable_fraction"})
    rig.model.set_state(T0, t_avg=57.0 - 0.72 * 43)
    rig.cal.cold_shower(rig.model, T0 + MINUTE)
    assert rig.model.options.usable_fraction == 0.85
    assert rig.model.tank_litres_exact == pytest.approx(0.0)


def test_shower_runs_cold_early() -> None:
    """At a cold fraction of 0.72 the usable fraction becomes 0.72 and the tank water is 0 L."""
    rig = Rig(t_avg=57.0, loss_coefficient=0.0, cold_mean=14.0)
    rig.model.set_state(T0, t_avg=57.0 - 0.72 * 43)
    assert rig.model.cold_fraction == pytest.approx(0.72)
    assert rig.model.options.usable_fraction == 0.85
    rig.cal.cold_shower(rig.model, T0 + MINUTE)
    assert rig.model.options.usable_fraction == pytest.approx(0.72)
    assert rig.cal.source_of("usable_fraction") == "learned"
    assert rig.model.outputs.tank_litres == 0
    assert rig.model.tank_litres_exact == pytest.approx(0.0)
