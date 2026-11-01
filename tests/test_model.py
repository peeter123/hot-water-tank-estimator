"""Tests for the tank model: one test per scenario of the tank-model spec."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise
import json

import pytest

from custom_components.hot_water_tank_estimator.model import (
    EventKind,
    ModelOptions,
    Sources,
    TankModel,
)

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
SECOND = timedelta(seconds=1)


def make_options(**overrides: float) -> ModelOptions:
    """Options for a 281 L tank, cold water at 14 C all year and no standing loss."""
    values: dict[str, float] = {
        "volume": 281.0,
        "cold_mean": 14.0,
        "cold_amplitude": 0.0,
        "loss_coefficient": 0.0,
    }
    values.update(overrides)
    return ModelOptions(**values)


def make_model(
    sources: Sources | None = None,
    t_avg: float = 50.0,
    t_ch: float | None = 57.0,
    **overrides: float,
) -> TankModel:
    """A model at T0 with an energy counter as heat input unless other sources are given."""
    return TankModel(
        make_options(**overrides),
        sources if sources is not None else Sources(energy_counter=True),
        T0,
        t_avg,
        t_ch,
    )


def start_shower(model: TankModel, at: datetime) -> None:
    """Make the model detect a shower by humidity, with the water meter at 1000 L."""
    model.on_humidity(at - 10 * MINUTE, "bath", 50.0)
    model.on_humidity(at, "bath", 70.0)
    model.on_water_meter(at, 1000.0, "L")
    assert model.shower_detected


def test_cold_fraction() -> None:
    """Cold fraction with T_ch 57 C, T_avg 50 C and T_cold 14 C is 7 / 43."""
    model = make_model()
    assert model.t_cold == pytest.approx(14.0)
    assert model.cold_fraction == pytest.approx(7 / 43)
    assert model.cold_fraction == pytest.approx(0.163, abs=0.0005)


def test_shower_from_a_charged_tank() -> None:
    """10 L of mixed draw lower T_avg by 10 * 24 / 281 = 0.854 K and leave T_ch alone."""
    model = make_model(t_avg=57.0)
    start_shower(model, T0)
    model.on_water_meter(T0 + MINUTE, 1010.0, "L")
    assert model.t_avg == pytest.approx(57 - 10 * 24 / 281)
    assert 57 - model.t_avg == pytest.approx(0.854, abs=0.0005)
    assert model.t_ch == 57.0


def test_shower_from_a_tank_charged_below_the_mix_temperature() -> None:
    """With T_ch 35 C below T_mix, 10 L of mixed draw drop T_avg by 10 * 21 / 281."""
    model = make_model(t_avg=35.0, t_ch=35.0)
    start_shower(model, T0)
    model.on_water_meter(T0 + MINUTE, 1010.0, "L")
    assert 35 - model.t_avg == pytest.approx(10 * 21 / 281)
    assert 35 - model.t_avg == pytest.approx(0.747, abs=0.0005)


def test_taps_and_toilet() -> None:
    """6 L of other draws at share 0.2 lower T_avg by 6 * 0.2 * 43 / 281 = 0.184 K."""
    model = make_model(t_avg=57.0)
    model.on_water_meter(T0, 1000.0, "L")
    model.on_water_meter(T0 + MINUTE, 1006.0, "L")
    assert 57 - model.t_avg == pytest.approx(6 * 0.2 * 43 / 281)
    assert 57 - model.t_avg == pytest.approx(0.184, abs=0.0005)


def test_energy_counter_step() -> None:
    """A counter rise of 3.27 kWh on a 281 L tank at 40 C gives 50.0 C, with T_ch at least that."""
    model = make_model(t_avg=40.0, t_ch=40.0)
    model.on_energy(T0, 151.0)
    model.on_energy(T0 + MINUTE, 151.0 + 3.27)
    assert model.heating
    assert model.t_avg == pytest.approx(40 + 3270 / (1.163 * 281))
    assert model.t_avg == pytest.approx(50.0, abs=0.01)
    assert model.t_ch >= model.t_avg


def test_start_up_energy() -> None:
    """With 1.8 kWh start-up energy, a run of 5.0 kWh raises T_avg by 3200 / (1.163 * 281)."""
    model = make_model(t_avg=40.0, t_ch=40.0, startup_energy=1.8)
    model.on_energy(T0, 151.0)
    model.on_energy(T0 + MINUTE, 153.0)
    model.on_energy(T0 + 2 * MINUTE, 156.0)
    assert model.t_avg - 40 == pytest.approx(3200 / (1.163 * 281))
    assert model.t_avg - 40 == pytest.approx(9.79, abs=0.005)


def test_constant_power_for_ten_minutes() -> None:
    """6 kW for 10 minutes on a 281 L tank raises T_avg by 1000 Wh / (1.163 * 281) = 3.06 K."""
    model = make_model(Sources(power=True), t_avg=40.0, t_ch=40.0)
    model.on_power(T0, 6000.0)
    model.on_power(T0 + 10 * MINUTE, 6000.0)
    assert model.t_avg - 40 == pytest.approx(1000 / (1.163 * 281))
    assert model.t_avg - 40 == pytest.approx(3.06, abs=0.005)


def test_power_gap_counts_as_no_energy() -> None:
    """Power that was unavailable between two readings adds no energy."""
    model = make_model(Sources(power=True), t_avg=40.0, t_ch=40.0)
    model.on_power(T0, 6000.0)
    model.on_power(T0 + MINUTE, None)
    model.on_power(T0 + 11 * MINUTE, 6000.0)
    assert model.t_avg - 40 == pytest.approx(100 / (1.163 * 281))


def test_binary_sensor_drives_the_run() -> None:
    """A heating-active binary sensor turning off ends the run at that moment."""
    model = make_model(
        Sources(heating_binary=True, energy_counter=True), t_avg=40.0, t_ch=40.0
    )
    model.on_tank_sensor(T0, 50.0)
    model.on_heating(T0 + MINUTE, True)
    assert model.heating
    end = T0 + 30 * MINUTE
    events = model.on_heating(end, False)
    assert not model.heating
    assert [(e.kind, e.time) for e in events] == [(EventKind.CHARGE, end)]


def test_run_ends_below_the_setpoint() -> None:
    """The highest mean of flow and return over the last 2 minutes charges the tank: 50.3 C."""
    model = make_model(
        Sources(heating_binary=True, flow_return=True), t_avg=41.0, t_ch=41.0
    )
    end = T0 + 30 * MINUTE
    model.on_heating(T0, True)
    model.on_flow_return(end - 130 * timedelta(seconds=1), 52.0, 48.0)
    model.on_flow_return(end - 60 * timedelta(seconds=1), 52.2, 48.4)
    model.on_flow_return(end - 10 * timedelta(seconds=1), 50.0, 46.0)
    model.on_heating(end, False)
    assert model.t_avg == pytest.approx((52.2 + 48.4) / 2)
    assert model.t_avg == pytest.approx(50.3)
    assert model.t_ch == model.t_avg
    assert model.cold_fraction == 0.0


def test_no_flow_and_return_sensors() -> None:
    """Without flow and return, the tank sensor's 58.0 C is the charged temperature."""
    model = make_model(Sources(heating_binary=True), t_avg=41.0, t_ch=41.0)
    model.on_heating(T0, True)
    model.on_tank_sensor(T0 + MINUTE, 58.0)
    model.on_heating(T0 + 20 * MINUTE, False)
    assert (model.t_avg, model.t_ch) == (58.0, 58.0)


def test_charged_temperature_unavailable() -> None:
    """With flow, return and the tank sensor unavailable, the modelled values stay."""
    model = make_model(
        Sources(heating_binary=True, flow_return=True), t_avg=45.0, t_ch=50.0
    )
    model.on_heating(T0, True)
    model.on_flow_return(T0 + MINUTE, None, None)
    model.on_tank_sensor(T0 + MINUTE, None)
    model.on_heating(T0 + 20 * MINUTE, False)
    assert not model.heating
    assert (model.t_avg, model.t_ch) == (45.0, 50.0)


def test_binary_only_heating_source() -> None:
    """With only a binary sensor, heating on and the tank sensor at 45 C lift T_avg 41 C to 45 C."""
    model = make_model(Sources(heating_binary=True), t_avg=41.0, t_ch=41.0)
    model.on_heating(T0, True)
    model.on_tank_sensor(T0 + MINUTE, 45.0)
    assert model.t_avg == 45.0
    assert model.t_ch == 45.0


def test_one_hour_of_standing_loss() -> None:
    """One hour at k 0.004 per hour and T_ambient 20 C drops both temperatures by 0.148 K."""
    model = make_model(t_avg=57.0, t_ch=57.0, loss_coefficient=0.004)
    model.tick(T0 + HOUR)
    assert 57 - model.t_avg == pytest.approx(0.004 * 37)
    assert 57 - model.t_ch == pytest.approx(0.148)


def test_no_standing_loss_below_ambient() -> None:
    """A tank at or below T_ambient does not cool further."""
    model = make_model(t_avg=18.0, t_ch=18.0, loss_coefficient=0.004)
    model.tick(T0 + 10 * HOUR)
    assert (model.t_avg, model.t_ch) == (18.0, 18.0)


def test_model_drew_too_much() -> None:
    """The sensor at the charged temperature raises T_avg 40 C to 57 - 0.325 * 43 = 43.0 C."""
    model = make_model(t_avg=40.0, t_ch=57.0)
    model.on_tank_sensor(T0, 57.0)
    assert model.t_avg == pytest.approx(57 - 0.325 * 43)
    assert model.t_avg == pytest.approx(43.0, abs=0.03)


def test_tank_emptied_past_the_sensor() -> None:
    """The sensor at 15 C lowers T_avg 33 C to 57 - 0.675 * 43 = 28.0 C."""
    model = make_model(t_avg=33.0, t_ch=57.0)
    model.on_tank_sensor(T0, 15.0)
    assert model.t_avg == pytest.approx(57 - 0.675 * 43)
    assert model.t_avg == pytest.approx(28.0, abs=0.03)


def test_sensor_falling_during_a_long_shower() -> None:
    """The sensor at 40 C gives T_s_avg 37.1 C, so T_avg 41 C becomes 39.1 C."""
    model = make_model(t_avg=41.0, t_ch=57.0)
    model.on_tank_sensor(T0, 40.0)
    t_s_avg = 57 - (0.675 - (40 - 14) / 43 * 0.35) * 43
    assert t_s_avg == pytest.approx(37.1, abs=0.05)
    assert model.t_avg == pytest.approx(t_s_avg + 2)
    assert model.t_avg == pytest.approx(39.1, abs=0.05)


def test_model_below_the_sensor_reading() -> None:
    """The sensor in the thermocline never raises the model: T_avg 33 C stays."""
    model = make_model(t_avg=33.0, t_ch=57.0)
    model.on_tank_sensor(T0, 40.0)
    assert model.t_avg == 33.0


def test_unmetered_heat() -> None:
    """A sensor 55 C over T_ch 50 C (tolerance 1.5 K) raises T_ch to 55 C and T_avg 45 C to 50 C."""
    model = make_model(t_avg=45.0, t_ch=50.0)
    model.on_tank_sensor(T0, 55.0)
    assert model.t_ch == 55.0
    assert model.t_avg == 50.0


def test_sensor_bounds_do_not_apply_while_heating() -> None:
    """No sensor rule acts during a heating run."""
    model = make_model(
        Sources(heating_binary=True, energy_counter=True), t_avg=40.0, t_ch=57.0
    )
    model.on_heating(T0, True)
    model.on_tank_sensor(T0 + MINUTE, 57.0)
    assert model.t_avg == 40.0


def test_draws_on_an_empty_tank() -> None:
    """A draw that would lower T_avg 14.2 C by 1 K stops at T_cold, 14 C."""
    model = make_model(t_avg=14.2, t_ch=57.0)
    start_shower(model, T0)
    model.on_water_meter(T0 + MINUTE, 1012.0, "L")
    assert model.t_avg == 14.0


def test_physical_bounds_hold_t_max() -> None:
    """Heat cannot take T_ch above T_max, and T_avg stays below T_ch."""
    model = make_model(t_avg=90.0, t_ch=90.0, max_temperature=95.0)
    model.on_energy(T0, 0.0)
    model.on_energy(T0 + MINUTE, 20.0)
    assert model.t_ch == 95.0
    assert model.t_cold <= model.t_avg <= model.t_ch <= 95.0


def test_seasonal_curve_in_late_october() -> None:
    """Mean 12.5 C, amplitude 5 K and coldest day 46 give 13.8 C on 31 October (day 304)."""
    model = TankModel(
        ModelOptions(volume=281.0), Sources(energy_counter=True), T0, 50.0
    )
    assert model.cold_water_temperature(T0) == pytest.approx(13.8, abs=0.05)
    assert model.t_cold == pytest.approx(13.8, abs=0.05)


def test_cold_sensor_unavailable() -> None:
    """A configured but unavailable cold water sensor falls back to the seasonal curve."""
    model = TankModel(
        ModelOptions(volume=281.0),
        Sources(energy_counter=True, cold_sensor=True),
        T0,
        50.0,
    )
    curve = model.t_cold
    model.on_cold_water_sensor(T0 + MINUTE, 10.0)
    assert model.t_cold == 10.0
    model.on_cold_water_sensor(T0 + 2 * MINUTE, None)
    assert model.t_cold == curve


def test_partly_drawn_tank() -> None:
    """With u 0.85 and f 0.163, tank water remaining is 281 * 0.687 = 193 L."""
    model = make_model(t_avg=50.0, t_ch=57.0)
    assert model.tank_litres_exact == pytest.approx(281 * (0.85 - 7 / 43))
    assert model.outputs.tank_litres == 193


def test_empty() -> None:
    """With f 0.9 and u 0.85, tank water remaining is 0 L."""
    model = make_model(t_avg=57 - 0.9 * 43, t_ch=57.0)
    assert model.cold_fraction == pytest.approx(0.9)
    assert model.outputs.tank_litres == 0


def test_mixing_multiplies_the_tank_water() -> None:
    """193.1 L of tank water at 57 C make 193.1 * 43 / 24 = 346 L of mixed water at 38 C."""
    model = make_model(t_avg=50.0, t_ch=57.0)
    assert model.tank_litres_exact == pytest.approx(193.1, abs=0.05)
    assert model.shower_litres_exact == pytest.approx(model.tank_litres_exact * 43 / 24)
    assert model.outputs.shower_litres == 346


def test_shower_water_equals_tank_water_below_the_mix_temperature() -> None:
    """With T_ch at or below T_mix, shower water equals tank water."""
    model = make_model(t_avg=30.0, t_ch=35.0)
    assert model.shower_litres_exact == model.tank_litres_exact


def test_percent_charged() -> None:
    """With u 0.85 and f 0.163, percent charged is 81 %, and 100 % right after a charge."""
    model = make_model(t_avg=50.0, t_ch=57.0)
    assert model.outputs.percent_charged == 81
    model.set_state(T0, 57.0, 57.0)
    assert model.outputs.percent_charged == 100


def test_minutes_from_litres() -> None:
    """346 L of shower water at 7.5 L/min is 46 minutes."""
    model = make_model(t_avg=50.0, t_ch=57.0)
    assert model.outputs.shower_litres == 346
    assert model.outputs.shower_minutes == 46


def test_set_state() -> None:
    """The set_tank_state rules: neither given charges to the sensor, bounds apply."""
    model = make_model(t_avg=50.0, t_ch=55.0)
    with pytest.raises(ValueError, match="unavailable"):
        model.set_state(T0)
    model.set_state(T0, t_avg=30.0)
    assert (model.t_avg, model.t_ch) == (30.0, 55.0)
    model.on_tank_sensor(T0 + MINUTE, 52.0)
    model.set_state(T0 + MINUTE)
    assert (model.t_avg, model.t_ch) == (52.0, 52.0)
    model.set_state(T0 + MINUTE, t_avg=5.0)
    assert model.t_avg == model.t_cold


def test_event_log_is_bounded() -> None:
    """The log keeps only the newest events, each with the input change and both temperatures."""
    model = TankModel(
        make_options(), Sources(energy_counter=True), T0, 57.0, 57.0, max_events=5
    )
    model.on_water_meter(T0, 1000.0, "L")
    for i in range(1, 11):
        model.on_water_meter(T0 + i * MINUTE, 1000.0 + i, "L")
    assert len(model.events) == 5
    last = model.events[-1]
    assert last.kind == EventKind.DRAW
    assert last.change == {"litres": 1.0, "mixed": False}
    assert last.t_avg_after < last.t_avg_before
    assert last.t_ch_after == last.t_ch_before == 57.0
    assert json.dumps(last.as_dict())


def test_charge_event_carries_calibration_figures() -> None:
    """The charge event holds the run energy and the interval sums of the plain balance."""
    model = make_model(
        Sources(heating_binary=True, energy_counter=True),
        t_avg=57.0,
        t_ch=57.0,
        startup_energy=1.8,
        loss_coefficient=0.004,
    )
    model.on_tank_sensor(T0, 40.0)
    model.on_heating(T0 + MINUTE, True)
    model.on_energy(T0 + MINUTE, 100.0)
    model.on_energy(T0 + 11 * MINUTE, 105.0)
    events = model.on_heating(T0 + 12 * MINUTE, False)
    charge = events[-1]
    assert charge.kind == EventKind.CHARGE
    assert charge.change["run_energy_kwh"] == pytest.approx(5.0)
    assert charge.change["startup_used_kwh"] == pytest.approx(1.8)
    assert charge.change["run_start_t_avg"] < 57.0
    assert charge.change["charge_temperature"] == 40.0
    assert charge.change["interval"]["hours"] == pytest.approx(1 / 60)
    assert model.interval_sums.hours == 0.0


def test_sums_ignore_sensor_bounds() -> None:
    """A sensor bound changes T_avg but not the balance sums of the interval."""
    model = make_model(t_avg=40.0, t_ch=57.0, loss_coefficient=0.004)
    model.on_water_meter(T0, 1000.0, "L")
    model.on_water_meter(T0 + MINUTE, 1010.0, "L")
    sums = model.interval_sums
    model.on_tank_sensor(T0 + MINUTE, 57.0)
    assert model.t_avg > 40.0
    assert model.interval_sums == sums
    assert sums.other == pytest.approx(10 * (57 - 14) / 281, rel=1e-3)


def test_counter_only_run_ends_after_ten_minutes() -> None:
    """With only an energy counter, 10 minutes without an increase find that the run ended."""
    model = make_model(t_avg=40.0, t_ch=40.0)
    model.on_tank_sensor(T0, 55.0)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + MINUTE, 101.0)
    assert model.heating
    model.tick(T0 + 10 * MINUTE)
    assert model.heating
    events = model.tick(T0 + 11 * MINUTE + timedelta(seconds=1))
    assert not model.heating
    assert any(e.kind == EventKind.CHARGE for e in events)
    assert (model.t_avg, model.t_ch) == (55.0, 55.0)


def test_energy_counter_reset_applies_no_heat() -> None:
    """A counter that drops adds no heat and its new reading is the starting point."""
    model = make_model(t_avg=40.0, t_ch=40.0)
    model.on_energy(T0, 151.5)
    model.on_energy(T0 + MINUTE, 0.2)
    assert model.t_avg == 40.0
    assert not model.heating
    model.on_energy(T0 + 2 * MINUTE, 1.2)
    assert model.t_avg - 40 == pytest.approx(1000 / (1.163 * 281))


def test_round_trip_mid_shower_mid_run() -> None:
    """A model restored mid-shower and mid-run gives the same results as the original."""
    sources = Sources(
        energy_counter=True,
        heating_binary=True,
        flow_return=True,
        humidity_sensors=("bath",),
    )
    options = make_options(startup_energy=1.0, loss_coefficient=0.004)
    model = TankModel(options, sources, T0, 45.0, 55.0)
    model.on_tank_sensor(T0, 48.0)
    model.on_flow_return(T0, 52.0, 48.0)
    model.on_energy(T0, 100.0)
    model.on_heating(T0 + MINUTE, True)
    model.on_energy(T0 + 2 * MINUTE, 101.5)
    model.on_humidity(T0 + 2 * MINUTE, "bath", 50.0)
    model.on_water_meter(T0 + 2 * MINUTE, 1000.0, "L")
    model.on_humidity(T0 + 3 * MINUTE, "bath", 70.0)
    for i in range(1, 6):
        model.on_water_meter(
            T0 + 3 * MINUTE + i * 8 * timedelta(seconds=1), 1000.0 + i, "L"
        )
    assert model.heating
    assert model.shower_detected

    restored = TankModel.from_dict(
        options, sources, json.loads(json.dumps(model.to_dict()))
    )
    assert restored.to_dict() == model.to_dict()
    assert restored.shower_detected

    def drive(m: TankModel) -> list[dict]:
        """Feed the same readings and return all resulting events."""
        out = []
        t = T0 + 4 * MINUTE
        for i in range(6, 12):
            out += m.on_water_meter(
                t + (i - 6) * 8 * timedelta(seconds=1), 1000.0 + i, "L"
            )
        out += m.on_energy(t + MINUTE, 103.0)
        out += m.on_flow_return(t + 2 * MINUTE, 53.0, 49.0)
        out += m.on_humidity(t + 3 * MINUTE, "bath", 62.0)
        out += m.on_tank_sensor(t + 4 * MINUTE, 47.0)
        out += m.tick(t + 5 * MINUTE)
        out += m.on_heating(t + 6 * MINUTE, False)
        out += m.tick(t + 20 * MINUTE)
        return [e.as_dict() for e in out]

    assert drive(restored) == drive(model)
    assert restored.to_dict() == model.to_dict()
    assert restored.outputs == model.outputs


def test_from_dict_rejects_bad_data() -> None:
    """Malformed or foreign state raises ValueError."""
    options = make_options()
    sources = Sources(energy_counter=True)
    with pytest.raises(ValueError, match="Invalid"):
        TankModel.from_dict(options, sources, {"version": 1})
    with pytest.raises(ValueError, match="version"):
        TankModel.from_dict(options, sources, {"version": 99})


def test_binary_sensor_flickers_during_a_run() -> None:
    """A binary sensor unavailable for 2 seconds keeps the run: no charge, no second start-up."""
    model = make_model(
        Sources(heating_binary=True, energy_counter=True),
        t_avg=40.0,
        t_ch=40.0,
        startup_energy=1.8,
    )
    model.on_energy(T0, 100.0)
    model.on_heating(T0 + MINUTE, True)
    model.on_energy(T0 + 2 * MINUTE, 102.0)
    model.on_heating(T0 + 3 * MINUTE, None)
    assert model.heating
    model.on_heating(T0 + 3 * MINUTE + 2 * SECOND, True)
    model.on_energy(T0 + 4 * MINUTE, 103.0)
    assert model.heating
    assert not any(e.kind == EventKind.CHARGE for e in model.events)
    assert model.t_avg - 40 == pytest.approx(1200 / (1.163 * 281))


def test_power_detector_unavailable_holds_then_hands_over() -> None:
    """Power as top detector holds the run 15 minutes while unavailable, then the counter decides."""
    model = make_model(Sources(power=True, energy_counter=True), t_avg=40.0, t_ch=40.0)
    model.on_tank_sensor(T0, 55.0)
    model.on_power(T0, 6000.0)
    assert model.heating
    model.on_power(T0 + MINUTE, None)
    model.tick(T0 + 15 * MINUTE)
    assert model.heating
    events = model.tick(T0 + 16 * MINUTE + SECOND)
    assert not model.heating
    assert any(e.kind == EventKind.CHARGE for e in events)


def test_cold_sensor_state_survives_a_round_trip() -> None:
    """A tank at 11 C with the cold sensor at 10 C keeps 11 C through a restore."""
    sources = Sources(energy_counter=True, cold_sensor=True)
    options = ModelOptions(volume=281.0)
    model = TankModel(options, sources, T0, 11.0, 50.0, cold_sensor=10.0)
    assert (model.t_cold, model.t_avg) == (10.0, 11.0)
    restored = TankModel.from_dict(
        options, sources, json.loads(json.dumps(model.to_dict()))
    )
    assert restored.t_cold == 10.0
    assert restored.t_avg == 11.0
    assert restored.to_dict() == model.to_dict()


def test_counter_timeout() -> None:
    """Last increase 12:30: found ended at 12:40, run_end 12:30, charge window 12:28-12:30."""
    model = make_model(
        Sources(energy_counter=True, flow_return=True), t_avg=40.0, t_ch=40.0
    )
    model.on_tank_sensor(T0, 50.0)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + 10 * MINUTE, 101.0)
    model.on_energy(T0 + 30 * MINUTE, 103.0)
    model.on_flow_return(T0 + 25 * MINUTE, 52.0, 48.0)
    model.on_flow_return(T0 + 29 * MINUTE, 53.0, 49.0)
    # Space heating after the run: these must not be used.
    model.on_flow_return(T0 + 31 * MINUTE, 35.0, 30.0)
    model.tick(T0 + 39 * MINUTE)
    assert model.heating
    events = model.tick(T0 + 40 * MINUTE)
    assert not model.heating
    charge = next(e for e in events if e.kind == EventKind.CHARGE)
    assert charge.change["source"] == "flow_return"
    assert charge.change["run_end"] == (T0 + 30 * MINUTE).isoformat()
    assert charge.change["charge_temperature"] == 51.0
    assert (model.t_avg, model.t_ch) == (51.0, 51.0)


def test_power_restore_adds_no_downtime_energy() -> None:
    """After a restore with a 5 kW last value, the first reading 8 h later adds no energy."""
    sources = Sources(power=True)
    options = make_options()
    model = TankModel(options, sources, T0, 40.0, 40.0)
    model.on_power(T0, 5000.0)
    assert model.heating
    restored = TankModel.from_dict(options, sources, model.to_dict())
    restored.on_power(T0 + 8 * HOUR, 5000.0)
    assert restored.heating
    assert restored.t_avg == 40.0
    restored.on_power(T0 + 8 * HOUR + 6 * MINUTE, 5000.0)
    assert restored.t_avg - 40 == pytest.approx(500 / (1.163 * 281))


def test_power_before_a_binary_run_start_is_not_counted() -> None:
    """With a binary detector, the run's energy is the power from its start to its end."""
    model = make_model(Sources(heating_binary=True, power=True), t_avg=40.0, t_ch=40.0)
    model.on_tank_sensor(T0, 50.0)
    model.on_power(T0, 6000.0)
    model.on_heating(T0 + 10 * MINUTE, True)
    events = model.on_heating(T0 + 20 * MINUTE, False)
    charge = events[-1]
    assert charge.kind == EventKind.CHARGE
    assert charge.change["run_energy_kwh"] == pytest.approx(1.0)


def test_negative_energy_steps_count_as_zero() -> None:
    """A negative power reading cannot make the run energy or the start-up bookkeeping negative."""
    model = make_model(
        Sources(heating_binary=True, power=True),
        t_avg=40.0,
        t_ch=40.0,
        startup_energy=1.8,
    )
    model.on_heating(T0, True)
    model.on_tank_sensor(T0, 50.0)
    model.on_power(T0, -500.0)
    model.on_power(T0 + HOUR, 0.0)
    assert model.t_avg == 40.0
    charge = model.on_heating(T0 + HOUR, False)[-1]
    assert charge.change["run_energy_kwh"] == 0.0
    assert charge.change["startup_used_kwh"] == 0.0


def test_litres_before_a_charge_are_not_reclassified() -> None:
    """6 L of other draws, a charge to 55.0 C, then detection: T_avg stays and no negative sum."""
    model = make_model(
        Sources(heating_binary=True, energy_counter=True, humidity_sensors=("bath",)),
        t_avg=57.0,
        t_ch=57.0,
    )
    model.on_humidity(T0 - 10 * MINUTE, "bath", 50.0)
    model.on_water_meter(T0, 1000.0, "L")
    model.on_heating(T0 + 30 * SECOND, True)
    model.on_water_meter(T0 + MINUTE, 1006.0, "L")
    model.on_tank_sensor(T0 + MINUTE, 55.0)
    model.on_heating(T0 + 2 * MINUTE, False)
    assert model.t_avg == 55.0
    events = model.on_humidity(T0 + 150 * SECOND, "bath", 70.0)
    assert model.shower_detected
    assert not any(e.change.get("reclassified_litres") for e in events)
    assert model.t_avg == 55.0
    assert model.interval_sums.other >= 0.0
    assert model.interval_sums.mixed == 0.0


def test_event_log_chains() -> None:
    """Each event starts where the one before ended, including every loss step."""
    model = make_model(t_avg=57.0, t_ch=57.0, loss_coefficient=0.004)
    model.on_water_meter(T0, 1000.0, "L")
    model.on_water_meter(T0 + 10 * SECOND, 1006.0, "L")
    model.on_water_meter(T0 + 2 * HOUR, 1010.0, "L")
    model.tick(T0 + 3 * HOUR)
    model.tick(T0 + 4 * HOUR)
    model.on_water_meter(T0 + 4 * HOUR + MINUTE, 1015.0, "L")
    events = model.events
    assert [e.kind for e in events].count(EventKind.LOSS) >= 2
    for before, after in pairwise(events):
        assert after.t_avg_before == pytest.approx(before.t_avg_after)
        assert after.t_ch_before == pytest.approx(before.t_ch_after)
    # Consecutive loss steps merge into one event.
    assert all(not (a.kind == b.kind == EventKind.LOSS) for a, b in pairwise(events))


def test_t_cold_clamp_is_a_sensor_bound_not_a_loss() -> None:
    """A rising cold water temperature that lifts T_avg is logged as a sensor bound."""
    model = TankModel(
        ModelOptions(volume=281.0, loss_coefficient=0.0),
        Sources(energy_counter=True, cold_sensor=True),
        T0,
        11.0,
        50.0,
        cold_sensor=10.0,
    )
    events = model.on_cold_water_sensor(T0 + MINUTE, 15.0)
    assert model.t_avg == 15.0
    assert [e.kind for e in events] == [EventKind.SENSOR_BOUND]
    assert events[0].change["rules"] == ["t_cold_clamp"]
    assert events[0].t_avg_before == 11.0


def test_tank_sensor_flicker_applies_no_bound() -> None:
    """While the tank sensor is unavailable no bound acts and the outputs follow the model."""
    model = make_model(t_avg=57.0, t_ch=57.0)
    model.on_water_meter(T0, 1000.0, "L")
    model.on_tank_sensor(T0, 57.0)
    floor = 57 - 0.325 * 43
    model.on_tank_sensor(T0 + MINUTE, None)
    litres_before = model.outputs.tank_litres
    for i in range(1, 7):
        model.on_water_meter(T0 + MINUTE + i * 10 * SECOND, 1000.0 + 90 * i, "L")
    assert model.t_avg < floor
    assert model.outputs.tank_litres < litres_before
    model.on_tank_sensor(T0 + 3 * MINUTE, 57.0)
    assert model.t_avg == pytest.approx(floor)


def timeout_shower_model(**overrides: float) -> TankModel:
    """Counter-only run, last increase 12:30 at a 54.0 C charge, 60 L of shower until 12:34."""
    model = make_model(
        Sources(energy_counter=True, humidity_sensors=("bath",)),
        t_avg=40.0,
        t_ch=40.0,
        **overrides,
    )
    model.on_tank_sensor(T0, 54.0)
    model.on_humidity(T0 - 10 * MINUTE, "bath", 50.0)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + 10 * MINUTE, 101.0)
    model.on_energy(T0 + 30 * MINUTE, 103.0)
    model.on_humidity(T0 + 31 * MINUTE, "bath", 70.0)
    model.on_water_meter(T0 + 31 * MINUTE, 1000.0, "L")
    for i in range(1, 4):
        model.on_water_meter(T0 + (31 + i) * MINUTE, 1000.0 + 20 * i, "L")
    assert model.heating
    return model


def test_shower_before_the_counter_timeout_finds_the_end() -> None:
    """60 L of mixed draw between the last increase and the timeout land on the charged tank.

    Loss coefficient 0 here, so the expected T_avg is exactly 54.0 - 60 * 24 / 281 = 48.9 C.
    """
    model = timeout_shower_model()
    model.tick(T0 + 40 * MINUTE)
    assert not model.heating
    assert model.t_avg == pytest.approx(54.0 - 60 * 24 / 281)
    assert model.t_avg == pytest.approx(48.9, abs=0.05)
    assert model.t_ch == 54.0
    sums = model.interval_sums
    assert sums.mixed == pytest.approx(60 * 24 / 281)
    assert sums.hours == pytest.approx(10 / 60)
    # The log chains through the replayed draws, which are marked.
    events = model.events
    for before, after in pairwise(events):
        assert after.t_avg_before == pytest.approx(before.t_avg_after)
    replayed = [e for e in events if e.change.get("replayed")]
    assert [e.kind for e in replayed].count(EventKind.DRAW) == 3
    assert all(e.time > T0 + 30 * MINUTE for e in replayed)


def test_shower_before_the_counter_timeout_with_standing_loss() -> None:
    """With k 0.004 per hour both temperatures end slightly below 48.9 C and 54.0 C."""
    k = 0.004
    model = timeout_shower_model(loss_coefficient=k)
    model.tick(T0 + 40 * MINUTE)
    t_avg = t_ch = 54.0
    now_min = 0.0
    for draw_min in (2.0, 3.0, 4.0, 10.0):
        hours = (draw_min - now_min) / 60
        t_avg -= k * hours * (t_avg - 20.0)
        t_ch -= k * hours * (t_ch - 20.0)
        now_min = draw_min
        if draw_min < 10.0:
            t_avg -= 20 * 24 / 281
    assert model.t_avg == pytest.approx(t_avg)
    assert model.t_ch == pytest.approx(t_ch)
    assert 48.8 < model.t_avg < 48.9
    assert 53.9 < model.t_ch < 54.0


def test_detection_after_the_end_is_found_reclassifies_late_litres() -> None:
    """A shower from 12:38 as other draws, end found at 12:40, detection at 12:40:30."""
    model = make_model(
        Sources(energy_counter=True, humidity_sensors=("bath",)), t_avg=40.0, t_ch=40.0
    )
    model.on_tank_sensor(T0, 54.0)
    model.on_humidity(T0 - 10 * MINUTE, "bath", 50.0)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + 10 * MINUTE, 101.0)
    model.on_energy(T0 + 30 * MINUTE, 103.0)
    model.on_water_meter(T0 + 35 * MINUTE, 1000.0, "L")
    for i, seconds in enumerate((0, 50, 100), start=1):
        model.on_water_meter(T0 + 38 * MINUTE + seconds * SECOND, 1000.0 + 10 * i, "L")
    model.tick(T0 + 40 * MINUTE)
    assert not model.heating
    assert model.t_avg == pytest.approx(54.0 - 30 * 0.2 * 40 / 281)
    events = model.on_humidity(T0 + 40 * MINUTE + 30 * SECOND, "bath", 70.0)
    assert model.shower_detected
    assert events[0].change["reclassified_litres"] == pytest.approx(30.0)
    assert model.t_avg == pytest.approx(54.0 - 30 * 24 / 281)


def test_detection_before_the_end_is_found_does_not_correct_the_charge() -> None:
    """A reclassify between the run end and its discovery cannot touch litres before the end."""
    model = make_model(
        Sources(energy_counter=True, humidity_sensors=("bath",)), t_avg=40.0, t_ch=40.0
    )
    model.on_tank_sensor(T0, 54.0)
    model.on_humidity(T0 - 10 * MINUTE, "bath", 50.0)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + 10 * MINUTE, 101.0)
    model.on_water_meter(T0 + 20 * MINUTE, 1000.0, "L")
    model.on_water_meter(T0 + 29 * MINUTE + 30 * SECOND, 1010.0, "L")
    model.on_energy(T0 + 30 * MINUTE, 103.0)
    model.on_humidity(T0 + 30 * MINUTE + 30 * SECOND, "bath", 70.0)
    model.tick(T0 + 40 * MINUTE)
    assert not model.heating
    assert model.t_avg == pytest.approx(54.0)
    assert model.interval_sums.mixed == 0.0
    assert model.interval_sums.other == 0.0


def test_counter_takes_over_after_the_hold_without_ending_before_the_run_start() -> (
    None
):
    """After the 15-minute hold the counter ends the run no earlier than the run start."""
    model = make_model(Sources(power=True, energy_counter=True), t_avg=40.0, t_ch=40.0)
    model.on_tank_sensor(T0, 55.0)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + MINUTE, 101.0)
    model.on_power(T0 + 10 * MINUTE, 6000.0)
    assert model.heating
    model.on_power(T0 + 11 * MINUTE, None)
    events = model.tick(T0 + 27 * MINUTE)
    assert not model.heating
    charge = next(e for e in events if e.kind == EventKind.CHARGE)
    assert charge.change["run_end"] == charge.change["run_start"]
    assert charge.change["run_end"] == (T0 + 10 * MINUTE).isoformat()


def test_draws_before_the_counter_timeout_survive_a_restart() -> None:
    """A restart inside the window keeps the draws that the late charge has to replay."""
    sources = Sources(energy_counter=True)
    options = make_options()
    model = TankModel(options, sources, T0, 40.0, 40.0)
    model.on_tank_sensor(T0, 54.0)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + MINUTE, 101.0)
    model.on_water_meter(T0 + 2 * MINUTE, 1000.0, "L")
    model.on_water_meter(T0 + 3 * MINUTE, 1050.0, "L")
    restored = TankModel.from_dict(
        options, sources, json.loads(json.dumps(model.to_dict()))
    )
    model.tick(T0 + 12 * MINUTE)
    restored.tick(T0 + 12 * MINUTE)
    assert restored.t_avg == pytest.approx(54.0 - 50 * 0.2 * 40 / 281)
    assert restored.to_dict() == model.to_dict()


def test_charge_event_holds_the_in_run_sums() -> None:
    """Draws and loss during a run are in the charge event's run sums, apart from the interval sums."""
    model = make_model(
        Sources(heating_binary=True, energy_counter=True),
        t_avg=57.0,
        t_ch=57.0,
        loss_coefficient=0.004,
    )
    model.on_heating(T0, False)
    model.on_water_meter(T0, 1000.0, "L")
    model.on_water_meter(T0 + HOUR, 1010.0, "L")  # 10 L before the run
    model.on_heating(T0 + 2 * HOUR, True)
    model.on_energy(T0 + 2 * HOUR, 100.0)
    model.on_water_meter(T0 + 2 * HOUR + 10 * MINUTE, 1030.0, "L")  # 20 L in the run
    model.on_energy(T0 + 3 * HOUR, 104.0)
    events = model.on_heating(T0 + 3 * HOUR, False)
    change = events[-1].change
    assert change["interval"]["other"] == pytest.approx(10 * 43 / 281, rel=1e-2)
    assert change["interval"]["hours"] == pytest.approx(2.0)
    assert change["run"]["other"] == pytest.approx(20 * 43 / 281, rel=2e-2)
    assert change["run"]["hours"] == pytest.approx(1.0)
    assert change["run"]["loss"] > 0.0
    assert change["interval"]["loss"] + change["run"]["loss"] > change["run"]["loss"]


def test_counter_timeout_run_sums_end_at_the_last_increase() -> None:
    """A counter-timeout end is found 10 minutes late; the in-run sums stop at the last increase."""
    model = make_model(t_avg=57.0, t_ch=57.0, loss_coefficient=0.004)
    model.on_tank_sensor(T0, 40.0)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + MINUTE, 101.0)
    model.on_energy(T0 + 9 * MINUTE, 102.0)
    events = model.tick(T0 + 40 * MINUTE)
    (charge,) = [e for e in events if e.kind == EventKind.CHARGE]
    change = charge.change
    assert change["run_end"] == (T0 + 9 * MINUTE).isoformat()
    assert change["run"]["hours"] == pytest.approx(8 / 60)
    assert model.interval_sums.hours == pytest.approx(31 / 60)


def test_counter_increase_soon_after_a_run_end_is_reported() -> None:
    """With a binary sensor deciding, a counter step within 10 minutes after the end is a lag event."""
    model = make_model(
        Sources(heating_binary=True, energy_counter=True), t_avg=40.0, t_ch=40.0
    )
    model.on_heating(T0, True)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + 30 * MINUTE, 103.0)
    end = T0 + 31 * MINUTE
    model.on_heating(end, False)
    t_avg = model.t_avg
    (late,) = model.on_energy(end + 5 * MINUTE, 103.5)
    assert late.kind == EventKind.HEAT
    assert late.change == {"counter_lag_kwh": 0.5, "run_end": end.isoformat()}
    assert model.t_avg == t_avg
    assert model.on_energy(end + 11 * MINUTE, 104.0) == []


def test_unavailable_time_per_source() -> None:
    """The seconds a source was unavailable in the interval, also while it still is."""
    model = make_model(
        Sources(heating_binary=True, energy_counter=True, humidity_sensors=("bath",)),
        t_avg=50.0,
        t_ch=50.0,
    )
    model.on_water_meter(T0, 1000.0, "L")
    model.on_water_meter(T0 + 10 * MINUTE, None, "L")
    model.on_humidity(T0 + 20 * MINUTE, "bath", None)
    model.on_water_meter(T0 + 30 * MINUTE, 1000.0, "L")
    seconds = model.unavailable_seconds(T0 + 60 * MINUTE)
    assert seconds["water_meter"] == pytest.approx(20 * 60)
    assert seconds["humidity:bath"] == pytest.approx(40 * 60)
    assert "tank_sensor" not in seconds
    model.on_heating(T0 + 61 * MINUTE, True)
    model.on_energy(T0 + 61 * MINUTE, 100.0)
    model.on_energy(T0 + 62 * MINUTE, 101.0)
    model.on_tank_sensor(T0 + 62 * MINUTE, 45.0)
    events = model.on_heating(T0 + 63 * MINUTE, False)
    charge = events[-1].change
    assert charge["unavailable_seconds"]["humidity:bath"] == pytest.approx(43 * 60)
    # The next interval starts with the sources that are still unavailable.
    later = model.unavailable_seconds(T0 + 73 * MINUTE)
    assert later == {"humidity:bath": pytest.approx(10 * 60)}


def test_balance_cold_fraction_ignores_the_sensor() -> None:
    """The balance's cold fraction stays on the draws while a sensor bound lifts T_avg."""
    model = make_model(t_avg=57.0, t_ch=57.0)
    start_shower(model, T0)
    for minute in range(1, 4):
        model.on_water_meter(T0 + minute * MINUTE, 1000.0 + 95 * minute, "L")
    model.on_tank_sensor(T0 + 4 * MINUTE, 57.0)
    assert model.balance_cold_fraction == pytest.approx(3 * 95 * 24 / 281 / 43)
    assert model.cold_fraction < model.balance_cold_fraction
    assert model.tank_sensor == 57.0


def test_calibration_bookkeeping_survives_a_restore() -> None:
    """The counter-lag, unavailable time and increase sums are part of the saved state."""
    model = make_model(Sources(heating_binary=True, energy_counter=True))
    model.on_heating(T0, True)
    model.on_energy(T0, 100.0)
    model.on_energy(T0 + 10 * MINUTE, 102.0)
    model.on_water_meter(T0 + 11 * MINUTE, None, "L")
    model.on_heating(T0 + 12 * MINUTE, False)
    model.on_water_meter(T0 + 20 * MINUTE, None, "L")
    saved = json.loads(json.dumps(model.to_dict()))
    restored = TankModel.from_dict(make_options(), model.sources, saved)
    assert restored.to_dict() == model.to_dict()
    assert restored.unavailable_seconds(T0 + HOUR) == model.unavailable_seconds(
        T0 + HOUR
    )
    # A state saved before the bookkeeping existed still restores.
    for key in ("increase_sums", "last_run_end", "unavailable", "down_since"):
        saved.pop(key)
    TankModel.from_dict(make_options(), model.sources, saved)


def test_log_event_records_a_calibration_event() -> None:
    """A calibration event is logged with the temperatures now."""
    model = make_model()
    event = model.log_event(
        T0 + MINUTE, EventKind.CALIBRATION, {"parameters": {"other_hot_share": 0.3}}
    )
    assert model.events[-1] == event
    assert event.kind == EventKind.CALIBRATION
    assert event.change == {"parameters": {"other_hot_share": 0.3}}
    assert event.t_avg_before == event.t_avg_after == model.t_avg
    assert event.t_ch_before == event.t_ch_after == model.t_ch


def test_forget_reading_makes_the_next_reading_a_new_start() -> None:
    """After a source is replaced, a higher counter and a higher meter reading apply nothing."""
    model = make_model(Sources(energy_counter=True, heating_binary=True))
    model.on_heating(T0, True)
    model.on_energy(T0, 10.0)
    model.on_water_meter(T0, 100.0, "m3")
    model.forget_reading("energy_counter")
    model.forget_reading("water_meter")
    before = model.t_avg
    events = model.on_energy(T0 + MINUTE, 500.0)
    events += model.on_water_meter(T0 + MINUTE, 105.0, "m3")
    assert all(e.kind not in (EventKind.HEAT, EventKind.DRAW) for e in events)
    assert model.t_avg == before
    assert [e.kind for e in model.on_energy(T0 + 2 * MINUTE, 500.5)] == [EventKind.HEAT]
    with pytest.raises(ValueError, match="baseline"):
        model.forget_reading("tank_sensor")
