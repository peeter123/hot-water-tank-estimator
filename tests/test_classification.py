"""Tests for draw classification: one test per scenario of the draw-classification spec."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import logging

import pytest

from custom_components.hot_water_tank_estimator.classification import (
    ClassifierOptions,
    DrawClassifier,
    litres_from_meter,
)
from custom_components.hot_water_tank_estimator.model import (
    ModelOptions,
    Sources,
    TankModel,
)

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
SECOND = timedelta(seconds=1)
MINUTE = timedelta(minutes=1)


def test_meter_in_cubic_metres() -> None:
    """347.504 m3 to 347.505 m3 is 1 litre drawn."""
    classifier = DrawClassifier(ClassifierOptions())
    assert classifier.on_meter(T0, 347.504, "m3") is None
    result = classifier.on_meter(T0 + 5 * SECOND, 347.505, "m3")
    assert result is not None
    assert result.litres == pytest.approx(1.0)


def test_meter_units() -> None:
    """Litres, US gallons and cubic feet convert to litres."""
    assert litres_from_meter(2.0, "L") == 2.0
    assert litres_from_meter(1.0, "m³") == 1000.0
    assert litres_from_meter(1.0, "gal") == pytest.approx(3.785, abs=0.001)
    assert litres_from_meter(1.0, "ft3") == pytest.approx(28.317, abs=0.001)
    assert litres_from_meter(1.0, "furlong") is None


def test_meter_reset() -> None:
    """347.504 m3 to 0.002 m3 draws nothing, and 0.002 m3 is the new starting point."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 347.504, "m3")
    assert classifier.on_meter(T0 + 5 * SECOND, 0.002, "m3") is None
    result = classifier.on_meter(T0 + 10 * SECOND, 0.003, "m3")
    assert result is not None
    assert result.litres == pytest.approx(1.0)


def test_non_numeric_reading_is_no_draw() -> None:
    """A non-numeric reading draws nothing, and the change since the last valid one applies later."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 100.0, "L")
    assert classifier.on_meter(T0 + MINUTE, None, "L") is None
    assert classifier.on_meter(T0 + 2 * MINUTE, float("nan"), "L") is None
    result = classifier.on_meter(T0 + 3 * MINUTE, 103.0, "L")
    assert result is not None
    assert result.litres == 3.0


def test_meter_catches_up_after_an_outage(caplog: pytest.LogCaptureFixture) -> None:
    """A rise of 450 L with the maximum at 100 L draws nothing and logs a warning."""
    classifier = DrawClassifier(ClassifierOptions(max_draw=100.0))
    classifier.on_meter(T0, 1000.0, "L")
    with caplog.at_level(logging.WARNING):
        assert classifier.on_meter(T0 + 5 * SECOND, 1450.0, "L") is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    result = classifier.on_meter(T0 + 10 * SECOND, 1451.0, "L")
    assert result is not None
    assert result.litres == 1.0


def test_continuous_shower() -> None:
    """1 L every 8 seconds for 30 minutes is one session: the long-draw rule never restarts."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    litres = 1000.0
    classifier.on_meter(T0, litres, "L")
    mixed_after_three_minutes = []
    for i in range(1, 30 * 60 // 8 + 1):
        litres += 1.0
        result = classifier.on_meter(T0 + i * 8 * SECOND, litres, "L")
        assert result is not None
        if (i - 1) * 8 >= 180:
            mixed_after_three_minutes.append(result.mixed)
    assert all(mixed_after_three_minutes)
    assert classifier.session_active


def test_separate_draws() -> None:
    """Two increases 5 minutes apart are different sessions."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    litres = 1000.0
    classifier.on_meter(T0, litres, "L")
    results = []
    # Two draws of 2.5 minutes each, 5 minutes apart: together they would pass 3 minutes.
    for start in (0, 450):
        for i in range(1, 19):
            litres += 1.0
            results.append(
                classifier.on_meter(T0 + (start + i * 8) * SECOND, litres, "L")
            )
    assert all(r is not None and not r.mixed for r in results)


def test_shower_starts() -> None:
    """With a 60-minute minimum of 61 % and a reading of 72 %, a shower is detected."""
    classifier = DrawClassifier(ClassifierOptions())
    for i, value in enumerate((64.0, 61.0, 62.0)):
        classifier.on_humidity(T0 + i * 10 * MINUTE, "bath", value)
    assert not classifier.detected
    classifier.on_humidity(T0 + 30 * MINUTE, "bath", 72.0)
    assert classifier.detected


def test_shower_ends_with_hysteresis() -> None:
    """Detected with minimum 61 % and rise 6: still detected at 65 %, ended below 64 %."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_humidity(T0, "bath", 61.0)
    classifier.on_humidity(T0 + 10 * MINUTE, "bath", 75.0)
    assert classifier.detected
    classifier.on_humidity(T0 + 20 * MINUTE, "bath", 65.0)
    assert classifier.detected
    classifier.on_humidity(T0 + 21 * MINUTE, "bath", 64.0)
    assert classifier.detected
    classifier.on_humidity(T0 + 22 * MINUTE, "bath", 63.9)
    assert not classifier.detected


def test_humidity_sensors_have_their_own_window_minimum() -> None:
    """A sensor high all day does not detect a shower, and one rising from its own minimum does."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_humidity(T0, "bath", 50.0)
    classifier.on_humidity(T0, "hall", 70.0)
    classifier.on_humidity(T0 + 5 * MINUTE, "hall", 71.0)
    assert not classifier.detected
    classifier.on_humidity(T0 + 6 * MINUTE, "bath", 57.0)
    assert classifier.detected
    classifier.on_humidity(T0 + 20 * MINUTE, "bath", 51.0)
    assert not classifier.detected


def test_humidity_window_slides() -> None:
    """The window minimum is the lowest value in force during the last 60 minutes."""
    classifier = DrawClassifier(ClassifierOptions(humidity_window=60.0))
    classifier.on_humidity(T0, "bath", 50.0)
    classifier.on_humidity(T0 + 50 * MINUTE, "bath", 60.0)
    assert classifier.detected
    # The 50 % reading was in force until minute 50, so it still counts at minute 100...
    classifier.update(T0 + 100 * MINUTE)
    assert classifier.detected
    # ...and no longer at minute 111, when the window holds only 60 %.
    classifier.update(T0 + 111 * MINUTE)
    assert not classifier.detected


def test_long_draw_without_humidity_sensor() -> None:
    """A session of 3 minutes counts as a shower until the session ends."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    litres = 1000.0
    classifier.on_meter(T0, litres, "L")
    for i in range(1, 22):
        litres += 1.0
        result = classifier.on_meter(T0 + i * 10 * SECOND, litres, "L")
        assert result is not None
        assert result.mixed == ((i - 1) * 10 >= 180)
    assert classifier.detected
    classifier.update(T0 + 210 * SECOND + 61 * SECOND)
    assert not classifier.detected


def test_long_draw_is_off_by_default() -> None:
    """With the duration at 0 a long session stays other draws."""
    classifier = DrawClassifier(ClassifierOptions())
    litres = 1000.0
    classifier.on_meter(T0, litres, "L")
    for i in range(1, 60):
        litres += 1.0
        result = classifier.on_meter(T0 + i * 10 * SECOND, litres, "L")
        assert result is not None
        assert not result.mixed


def make_model(**overrides: float) -> TankModel:
    """A 281 L tank at 57 C, cold water at 14 C, no standing loss, with a bathroom sensor."""
    options = ModelOptions(
        volume=281.0,
        cold_mean=14.0,
        cold_amplitude=0.0,
        loss_coefficient=0.0,
        **overrides,
    )
    return TankModel(
        options, Sources(energy_counter=True, humidity_sensors=("bath",)), T0, 57.0
    )


def test_binary_sensor_follows_detection() -> None:
    """The model exposes detection by humidity, and whether a detection method exists."""
    model = make_model()
    assert model.detection_available
    model.on_humidity(T0, "bath", 55.0)
    assert not model.shower_detected
    model.on_humidity(T0 + MINUTE, "bath", 70.0)
    assert model.shower_detected
    without = TankModel(
        ModelOptions(volume=281.0), Sources(energy_counter=True), T0, 57.0
    )
    assert not without.detection_available
    with_long_draw = TankModel(
        ModelOptions(volume=281.0, long_draw_minutes=3.0),
        Sources(energy_counter=True),
        T0,
        57.0,
    )
    assert with_long_draw.detection_available


def test_shower_litre() -> None:
    """1 litre drawn while a shower is detected goes to the tank model as 1 litre of mixed draw."""
    model = make_model()
    model.on_water_meter(T0, 1000.0, "L")
    model.on_humidity(T0, "bath", 55.0)
    model.on_humidity(T0 + MINUTE, "bath", 70.0)
    events = model.on_water_meter(T0 + MINUTE + 5 * SECOND, 1001.0, "L")
    assert events[0].change == {"litres": 1.0, "mixed": True}
    assert 57 - model.t_avg == pytest.approx(24 / 281)


def _slow_trickle_then_shower(feed: Callable[[int, int], object]) -> None:
    """Feed 40 L of slow trickle, then 45 L in the 10 minutes before detection, one session.

    The trickle is 20 draws of 2 L, 50 s apart, ending 620 s before the detection at 1620 s. The
    shower litres are 45 draws of 1 L, 12 s apart, from 1050 s, the last 42 s before detection.
    """
    litres = 1000.0
    feed(0, int(litres))
    for i in range(20):
        litres += 2.0
        feed(50 * i + 50, int(litres))
    for i in range(45):
        litres += 1.0
        feed(1050 + 12 * i, int(litres))


def test_reclassify_at_detection() -> None:
    """45 L in the 10 minutes before detection become mixed draws, 40 L of slow trickle stay."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_humidity(T0 - 10 * MINUTE, "bath", 50.0)
    _slow_trickle_then_shower(
        lambda seconds, litres: classifier.on_meter(
            T0 + seconds * SECOND, float(litres), "L"
        )
    )
    reclassified = classifier.on_humidity(T0 + 1620 * SECOND, "bath", 60.0)
    assert classifier.detected
    assert reclassified == pytest.approx(45.0)


def test_reclassify_corrects_the_model_by_the_energy_difference() -> None:
    """The model ends where it would be had the 45 L been mixed draws from the start."""
    model = make_model()
    model.on_humidity(T0 - 10 * MINUTE, "bath", 50.0)
    _slow_trickle_then_shower(
        lambda seconds, litres: model.on_water_meter(
            T0 + seconds * SECOND, float(litres), "L"
        )
    )
    events = model.on_humidity(T0 + 1620 * SECOND, "bath", 60.0)
    assert events[0].change == {"reclassified_litres": pytest.approx(45.0)}
    assert 57 - model.t_avg == pytest.approx((40 * 0.2 * 43 + 45 * 24) / 281)
    sums = model.interval_sums
    assert sums.mixed == pytest.approx(45 * 24 / 281)
    assert sums.other == pytest.approx(40 * 43 / 281)


def test_toilet_flush_or_tap() -> None:
    """6 L drawn with no shower detected go to the tank model as 6 L of other draws."""
    model = make_model()
    model.on_water_meter(T0, 1000.0, "L")
    events = model.on_water_meter(T0 + 5 * SECOND, 1006.0, "L")
    assert events[0].change == {"litres": 6.0, "mixed": False}
    assert 57 - model.t_avg == pytest.approx(6 * 0.2 * 43 / 281)


def test_litres_reclassified_when_the_long_draw_rule_fires() -> None:
    """At the long-draw start, the 9 session litres within the reclassify window become mixed draws."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    litres = 1000.0
    classifier.on_meter(T0, litres, "L")
    results = []
    for i in range(1, 11):
        litres += 1.0
        results.append(classifier.on_meter(T0 + i * 20 * SECOND, litres, "L"))
    assert all(r is not None for r in results)
    assert [r.reclassified for r in results if r is not None] == [0.0] * 9 + [9.0]
    assert results[-1] is not None
    assert results[-1].mixed


def test_sensor_that_never_reached_the_rise_does_not_hold_detection() -> None:
    """Sensor B at its minimum plus 4 points never detected, so A dropping ends detection."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_humidity(T0, "a", 50.0)
    classifier.on_humidity(T0, "b", 50.0)
    classifier.on_humidity(T0 + 5 * MINUTE, "b", 54.0)
    classifier.on_humidity(T0 + 6 * MINUTE, "a", 62.0)
    assert classifier.detected
    classifier.on_humidity(T0 + 20 * MINUTE, "a", 51.0)
    assert not classifier.detected


def test_unknown_unit_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    """An unknown or missing unit is ignored, with one warning per unit."""
    classifier = DrawClassifier(ClassifierOptions())
    with caplog.at_level(logging.WARNING):
        for i in range(3):
            assert classifier.on_meter(T0 + i * SECOND, 1.0 + i, "furlong") is None
        assert classifier.on_meter(T0 + 5 * SECOND, 5.0, None) is None
        assert classifier.on_meter(T0 + 6 * SECOND, 6.0, None) is None
    assert len(caplog.records) == 2
    assert litres_from_meter(1.0, None) is None


def test_a_session_end_is_reported_once() -> None:
    """A session that ends reports the time of its last increase, once, after the session gap."""
    classifier = DrawClassifier(ClassifierOptions(session_gap=60.0))
    classifier.on_meter(T0, 1000.0, "L")
    classifier.on_meter(T0 + 10 * SECOND, 1001.0, "L")
    classifier.on_meter(T0 + 30 * SECOND, 1002.0, "L")
    classifier.update(T0 + 60 * SECOND)
    assert classifier.take_session_end() is None
    assert classifier.session_active
    classifier.update(T0 + 100 * SECOND)
    assert not classifier.session_active
    assert classifier.take_session_end() == T0 + 30 * SECOND
    assert classifier.take_session_end() is None


def test_a_new_draw_after_the_gap_reports_the_old_session_end() -> None:
    """The reading that opens the next session also reports the end of the one before."""
    classifier = DrawClassifier(ClassifierOptions(session_gap=60.0))
    classifier.on_meter(T0, 1000.0, "L")
    classifier.on_meter(T0 + 10 * SECOND, 1001.0, "L")
    classifier.on_meter(T0 + 5 * MINUTE, 1002.0, "L")
    assert classifier.take_session_end() == T0 + 10 * SECOND
    assert classifier.session_active
