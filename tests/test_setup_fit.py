"""Tests for the setup fit: the replay of recorded history with live learning."""

from datetime import UTC, datetime, timedelta
from functools import cache
import json
from pathlib import Path

import pytest

from custom_components.hot_water_tank_estimator.calibration import (
    CLOSURE,
    SENSOR_START,
    Calibrator,
    UndoRecord,
)
from custom_components.hot_water_tank_estimator.model import ModelOptions
from custom_components.hot_water_tank_estimator.setup_fit import (
    History,
    Series,
    SetupFit,
    evaluate,
    history_from_fixture,
    replay,
    setup_fit,
    sources_for,
)

FIXTURES = Path(__file__).parent / "fixtures"


@cache
def load(name: str) -> tuple[History, ModelOptions]:
    """Return a fixture's history and the default options for its tank."""
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    options = ModelOptions(
        volume=data["tank"]["volume"], sensor_height=data["tank"]["sensor_height"]
    )
    return history_from_fixture(data), options


@cache
def week_fit() -> SetupFit:
    """The setup fit of the week fixture with the default options."""
    history, options = load("week")
    return setup_fit(history, options)


def test_the_sources_follow_the_roles_of_the_history() -> None:
    """The fixture has a counter, a heating binary, flow and return, and one humidity sensor."""
    history, _ = load("week")
    sources = sources_for(history)
    assert sources.energy_counter
    assert sources.heating_binary
    assert sources.flow_return
    assert not sources.power
    assert sources.humidity_sensors == ("sensor.bathroom_humidity",)


def test_the_first_charge_is_a_sensor_start() -> None:
    """The first charge of a replay is a sensor start, never a closure."""
    closures = week_fit().closures
    assert closures[0].status == SENSOR_START
    assert closures[0].t_ch_prev is None
    assert all(c.status == CLOSURE for c in closures[1:])


def test_week_has_seven_closures() -> None:
    """The week holds 8 heating runs: a sensor start and 7 closures."""
    fit = week_fit()
    assert len(fit.closures) == 8
    assert len(fit.intervals) == 7


def test_week_start_up_energy() -> None:
    """The start-up energy fitted on the week is 1.0-2.6 kWh."""
    value, source = week_fit().parameters["startup_energy"]
    assert 1.0 <= value <= 2.6
    assert source == "setup_fit"


def test_week_charge_error_with_the_fitted_parameters() -> None:
    """Replayed with the fitted parameters, the mean absolute charge error is 2.5 K or less."""
    history, _ = load("week")
    result = evaluate(history, week_fit().options)
    assert len(result.intervals) == 7
    assert result.mean_abs_error is not None
    assert result.mean_abs_error <= 2.5


def test_the_fit_beats_the_given_options() -> None:
    """The fitted parameters have a smaller error than the options as given."""
    history, options = load("week")
    given = evaluate(history, options).mean_abs_error
    fitted = evaluate(history, week_fit().options).mean_abs_error
    assert given is not None and fitted is not None
    assert fitted < given


def test_week_share_and_loss_ranges() -> None:
    """The share fitted on the week is 0.1-0.3 and k 0.002-0.007 per hour, with k held at the quiet windows."""
    fit = week_fit()
    parameters = fit.parameters
    assert 0.1 <= parameters["other_hot_share"][0] <= 0.3
    assert 0.002 <= parameters["loss_coefficient"][0] <= 0.007
    # Six quiet windows are at hand, so the closures did not fit k: it is their mean.
    estimates = fit.calibrator.quiet_estimates
    assert len(estimates) >= 3
    assert parameters["loss_coefficient"][0] == pytest.approx(
        sum(estimates) / len(estimates), abs=0.0003
    )


def test_live_learning_after_the_fit_is_labelled_learned() -> None:
    """The fit labels its changes setup_fit; later changes by live learning are labelled learned."""
    fit = week_fit()
    assert fit.parameters["startup_energy"][1] == "setup_fit"
    assert fit.calibrator.label == "learned"


def test_recalibrate_keeps_the_usable_fraction_from_the_button() -> None:
    """A replay cannot learn the usable fraction, so a recalibrate keeps the one from the button."""
    history, options = load("week")
    before = setup_fit(history, options)
    before.calibrator.values["usable_fraction"] = 0.72
    before.calibrator.sources["usable_fraction"] = "learned"
    again = setup_fit(history, options, previous=before.calibrator)
    assert again.parameters["usable_fraction"] == (0.72, "learned")
    assert again.options.usable_fraction == 0.72
    # The other parameters are refitted from the same history.
    assert again.parameters["startup_energy"] == before.parameters["startup_energy"]


def test_recalibrate_keeps_the_undo_record() -> None:
    """The undo of the last press is in no history: a recalibrate keeps the record."""
    history, options = load("week")
    before = setup_fit(history, options)
    record = UndoRecord(
        time=history.end,
        usable_changed=True,
        usable=0.9,
        usable_source="learned",
        drop=4.3,
        last_reset=None,
    )
    before.calibrator.undo_record = record
    again = setup_fit(history, options, previous=before.calibrator)
    assert again.calibrator.undo_record == record


def test_the_replay_starts_at_the_first_numeric_tank_reading() -> None:
    """A tank sensor that is unavailable in its first row does not make the model start at 50 C."""
    history, options = load("week")
    start = history.start
    tank = Series(
        "tank_temperature",
        "sensor.tank_temperature",
        "C",
        [(start, "unavailable"), (start + timedelta(minutes=1), "42.0")],
    )
    short = History(start, start + timedelta(minutes=30), [tank])
    result = replay(short, options)
    assert result.model.t_avg == pytest.approx(42.0, abs=0.5)


def quiet_night(ambient: list[tuple[datetime, str]] | None) -> History:
    """A tank sensor that falls from 57.0 to 55.9 C in 8 hours, then drops to 50 C.

    With `ambient`, the history has an ambient sensor with those rows.
    """
    start = datetime(2026, 10, 1, 22, 0, tzinfo=UTC)
    hour = timedelta(hours=1)
    rows = [(start + n * hour, str(57.0 - 1.1 * n / 8)) for n in range(9)]
    rows.append((start + 8 * hour + timedelta(minutes=1), "50.0"))
    series = [Series("tank_temperature", "sensor.tank", "C", rows)]
    if ambient is not None:
        series.append(Series("ambient_temperature", "sensor.ambient", "C", ambient))
    return History(start, start + 10 * hour, series)


def test_the_replay_uses_the_ambient_series_in_the_loss() -> None:
    """An ambient sensor at 10 C cools the replayed tank more than the 20 C of the options."""
    start = datetime(2026, 10, 1, 22, 0, tzinfo=UTC)
    options = ModelOptions(volume=281.0, loss_coefficient=0.004)
    plain = replay(quiet_night(None), options)
    cold = replay(quiet_night([(start, "10.0")]), options)
    assert sources_for(quiet_night([(start, "10.0")])).ambient_sensor
    assert not sources_for(quiet_night(None)).ambient_sensor
    assert 57.0 - plain.model.t_ch > 0
    # (57 - 10) / (57 - 20) times the fall: both fall by the same fraction of the excess.
    assert (57.0 - cold.model.t_ch) / (57.0 - plain.model.t_ch) == pytest.approx(
        (57 - 10) / (57 - 20), rel=0.02
    )


def test_the_replay_uses_the_ambient_series_in_the_quiet_windows() -> None:
    """Ambient readings that average 16 C give 0.1375 / 40.45 = 0.0034, not 0.1375 / 36.45."""
    start = datetime(2026, 10, 1, 22, 0, tzinfo=UTC)
    options = ModelOptions(volume=281.0)
    estimates = {}
    for name, ambient in (
        ("option", None),
        ("sensor", [(start, "16.0")]),
    ):
        cal = Calibrator(options, measures_heat=False)
        replay(quiet_night(ambient), options, calibrator=cal)
        (estimates[name],) = cal.quiet_estimates
    assert estimates["option"] == pytest.approx(0.1375 / 36.45, abs=0.0001)
    assert estimates["sensor"] == pytest.approx(0.1375 / 40.45, abs=0.0001)


def test_the_option_is_used_before_the_first_ambient_reading() -> None:
    """An ambient series that starts late leaves the earlier hours on the option."""
    start = datetime(2026, 10, 1, 22, 0, tzinfo=UTC)
    options = ModelOptions(volume=281.0)
    late = [(start + timedelta(hours=6), "16.0")]
    cal = Calibrator(options, measures_heat=False)
    replay(quiet_night(late), options, calibrator=cal)
    (estimate,) = cal.quiet_estimates
    # 6 hours at the option (20 C) and 2 hours at 16 C average 19.0 C.
    assert estimate == pytest.approx(0.1375 / (56.45 - 19.0), abs=0.0002)


def test_a_locked_parameter_is_not_fitted() -> None:
    """A locked share keeps its option value and is reported as locked."""
    history, options = load("week")
    fit = setup_fit(history, options, locks=["other_hot_share"])
    value, source = fit.parameters["other_hot_share"]
    assert value == options.other_hot_share
    assert source == "locked"
    assert "other_hot_share" not in fit.calibrator.values
    assert fit.parameters["startup_energy"][1] == "setup_fit"


def test_not_enough_history() -> None:
    """With fewer than 5 closures the parameters fitted from closures stay at their option values."""
    history, options = load("long_shower")
    fit = setup_fit(history, options)
    assert len(fit.intervals) < 5
    assert fit.parameters["other_hot_share"] == (options.other_hot_share, "option")
    assert fit.parameters["startup_energy"] == (options.startup_energy, "option")


def test_the_history_can_be_cut_to_its_last_days() -> None:
    """Fewer days of history replay the same way from the state in force at the start."""
    history, options = load("week")
    short = history.last_days(3)
    assert short.start == history.end - timedelta(days=3)
    assert all(s.states[0][0] == short.start for s in short.series)
    fit = setup_fit(short, options)
    assert len(fit.intervals) < 5
    assert fit.closures[0].status == SENSOR_START
    assert history.since(history.start - timedelta(days=1)) is history


def test_the_fit_is_repeatable() -> None:
    """The same history and options give the same parameters."""
    history, options = load("week")
    again = setup_fit(history, options)
    assert again.parameters == week_fit().parameters
