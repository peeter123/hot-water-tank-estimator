"""Tests for draw classification: one test per scenario of the draw-classification spec."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json
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


def test_bathroom_dries() -> None:
    """Minimum 61 %, rise 6: humid at 64 %, dry at 63.9 %, and a new rise of 6 starts a shower."""
    classifier = DrawClassifier(ClassifierOptions(humidity_configured=True))
    classifier.on_humidity(T0, "bath", 61.0)
    classifier.on_humidity(T0 + 10 * MINUTE, "bath", 75.0)
    assert classifier.detected
    classifier.update(T0 + 15 * MINUTE)  # no water: the shower is over
    assert not classifier.detected
    classifier.on_humidity(T0 + 20 * MINUTE, "bath", 65.0)
    assert classifier.humid
    classifier.on_humidity(T0 + 21 * MINUTE, "bath", 64.0)
    assert classifier.humid
    classifier.on_humidity(T0 + 22 * MINUTE, "bath", 63.9)
    assert not classifier.humid
    assert not classifier.detected
    classifier.on_humidity(T0 + 23 * MINUTE, "bath", 67.0)
    assert classifier.detected


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
    assert not classifier.humid


def test_humidity_window_slides() -> None:
    """The window minimum is the lowest value in force during the last 60 minutes."""
    classifier = DrawClassifier(ClassifierOptions(humidity_window=60.0))
    classifier.on_humidity(T0, "bath", 50.0)
    classifier.on_humidity(T0 + 50 * MINUTE, "bath", 60.0)
    assert classifier.humid
    # The 50 % reading was in force until minute 50, so it still counts at minute 100...
    classifier.update(T0 + 100 * MINUTE)
    assert classifier.humid
    # ...and no longer at minute 111, when the window holds only 60 %.
    classifier.update(T0 + 111 * MINUTE)
    assert not classifier.humid


def test_long_draw_without_humidity_sensor() -> None:
    """No humidity sensor, 3 minutes: a session of 3 minutes is a shower, ending 5 minutes after the water."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    litres = 1000.0
    classifier.on_meter(T0, litres, "L")
    for i in range(1, 22):
        litres += 1.0
        result = classifier.on_meter(T0 + i * 10 * SECOND, litres, "L")
        assert result is not None
        assert result.mixed == ((i - 1) * 10 >= 180)
    assert classifier.detected
    last = T0 + 210 * SECOND
    classifier.update(last + 5 * MINUTE - SECOND)
    assert classifier.detected
    classifier.update(last + 5 * MINUTE)
    assert not classifier.detected


def test_pause_in_a_long_draw_shower() -> None:
    """A long-draw shower that pauses for 3 minutes and runs again stays one shower."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    classifier.on_meter(T0, 1000.0, "L")
    meter = 1000.0
    for step in range(1, 25):  # 4 minutes of water, 1 L every 10 s
        meter = _draw(classifier, meter, step * 10, 1.0)
    assert classifier.detected
    classifier.update(T0 + 240 * SECOND + 3 * MINUTE)
    assert classifier.detected
    for step in range(1, 7):  # and one more minute
        meter = _draw(classifier, meter, 240 + 180 + step * 10, 1.0)
    classifier.update(T0 + 480 * SECOND + 5 * MINUTE)
    report = classifier.take_shower_end()
    assert report is not None
    assert report.litres == pytest.approx(
        28.0
    )  # 23 + 5: the first of each session is left out
    assert classifier.take_shower_end() is None


def test_long_draw_with_a_humidity_sensor() -> None:
    """A humidity sensor, 10 minutes, a 14-minute draw and a flat humidity: all other draws."""
    classifier = DrawClassifier(
        ClassifierOptions(long_draw_minutes=10.0, humidity_configured=True)
    )
    classifier.on_humidity(T0, "bath", 55.0)
    classifier.on_meter(T0, 1000.0, "L")
    for step in range(1, 15 * 6):  # 14.8 minutes, 1 L every 10 s
        classifier.on_humidity(T0 + step * 10 * SECOND, "bath", 55.0 + step % 2)
        result = classifier.on_meter(T0 + step * 10 * SECOND, 1000.0 + step, "L")
        assert result is not None
        assert not result.mixed
    assert not classifier.detected
    assert classifier.take_shower_end() is None


def test_a_reading_after_the_deadline_is_handled_after_the_shower() -> None:
    """With no call between, a draw 7 minutes after the last is a new draw, and the shower is reported."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    classifier.on_meter(T0, 1000.0, "L")
    meter = 1000.0
    for step in range(1, 25):
        meter = _draw(classifier, meter, step * 10, 1.0)
    assert classifier.detected
    result = classifier.on_meter(T0 + 240 * SECOND + 7 * MINUTE, meter + 1.0, "L")
    assert result is not None
    assert not result.mixed
    assert not classifier.detected
    report = classifier.take_shower_end()
    assert report is not None


def test_the_next_shower_end_is_the_last_increase_plus_the_end_time() -> None:
    """The deadline of the shower in progress, none without one."""
    classifier = DrawClassifier(ClassifierOptions(shower_end_minutes=5.0))
    assert classifier.shower_end is None
    classifier.on_humidity(T0, "bath", 55.0)
    classifier.on_humidity(T0 + MINUTE, "bath", 70.0)
    assert classifier.shower_end == T0 + 6 * MINUTE  # no water yet: from the start
    classifier.on_meter(T0 + 2 * MINUTE, 1000.0, "L")
    classifier.on_meter(T0 + 3 * MINUTE, 1001.0, "L")
    assert classifier.shower_end == T0 + 8 * MINUTE
    classifier.update(T0 + 8 * MINUTE)
    assert classifier.shower_end is None


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
    assert classifier.humid
    classifier.on_humidity(T0 + 20 * MINUTE, "a", 51.0)
    assert not classifier.humid


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


def _detect_by_humidity(classifier: DrawClassifier) -> None:
    """Make the classifier detect a shower: 55 % and, a second later, 70 %."""
    classifier.on_humidity(T0, "bath", 55.0)
    classifier.on_humidity(T0 + SECOND, "bath", 70.0)
    assert classifier.detected


def _draw(
    classifier: DrawClassifier, meter: float, seconds: float, litres: float
) -> float:
    """Draw `litres` at `seconds` after T0 and return the new meter reading."""
    meter += litres
    classifier.on_meter(T0 + timedelta(seconds=seconds), meter, "L")
    return meter


def test_off_after_the_water_stops() -> None:
    """Scenario "Off after the water stops": 5 minutes after the last litre, still 80 % humid, not detected."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 1000.0, "L")
    _detect_by_humidity(classifier)
    classifier.on_humidity(T0 + 5 * SECOND, "bath", 80.0)
    meter = _draw(classifier, 1000.0, 10, 1.0)
    meter = _draw(classifier, meter, 70, 6.0)
    classifier.update(T0 + 70 * SECOND + 5 * MINUTE - SECOND)
    assert classifier.detected
    classifier.update(T0 + 70 * SECOND + 5 * MINUTE)
    assert not classifier.detected


def test_shower_with_a_pause() -> None:
    """Scenario "Pause in a shower": a 3-minute pause between two sessions stays one shower (60 L over 8 minutes)."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 1000.0, "L")
    _detect_by_humidity(classifier)
    meter = 1000.0
    meter = _draw(classifier, meter, 10, 1.0)  # first increase of a session
    for seconds in (70, 130, 190, 250, 310):  # 5 minutes, 30 L after the first
        meter = _draw(classifier, meter, seconds, 6.0)
    meter = _draw(classifier, meter, 490, 1.0)  # after a 3-minute pause: 3 minutes
    for seconds in (550, 610, 670):  # 30 L after the first increase
        meter = _draw(classifier, meter, seconds, 10.0)
    assert classifier.take_shower_end() is None
    classifier.on_humidity(
        T0 + 700 * SECOND, "bath", 55.0
    )  # the humidity does not end it
    assert classifier.take_shower_end() is None
    classifier.update(T0 + 670 * SECOND + 5 * MINUTE)
    report = classifier.take_shower_end()
    assert report is not None
    assert report.litres == pytest.approx(60.0)
    assert report.minutes == pytest.approx(8.0)
    assert classifier.take_shower_end() is None
    assert classifier.rolling_flow is None


def test_shower_detected_by_the_long_draw_rule() -> None:
    """A session of 9 minutes that draws 70 L, detected by the long-draw rule: 70 L over 9 minutes."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    classifier.on_meter(T0, 1000.0, "L")
    meter = 1000.0
    for step in range(16):  # every 36 s for 9 minutes: 70 L after the first increase
        meter = _draw(classifier, meter, 10 + 36 * step, 3.0 if step == 0 else 70 / 15)
    assert classifier.detected
    assert classifier.take_shower_end() is None
    classifier.update(T0 + 10 * SECOND + 15 * 36 * SECOND + 5 * MINUTE)
    report = classifier.take_shower_end()
    assert report is not None
    assert report.litres == pytest.approx(70.0)
    assert report.minutes == pytest.approx(9.0)


def test_polled_meter() -> None:
    """One 8-minute session read every 30 s at 3.75 L per reading: 60 L over 8 minutes, 7.5 L/min."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 1000.0, "L")
    _detect_by_humidity(classifier)
    meter = 1000.0
    for step in range(17):
        meter = _draw(classifier, meter, 10 + 30 * step, 3.75)
    classifier.on_humidity(
        T0 + 14 * MINUTE, "bath", 55.0
    )  # 5 min 50 s after the last increase (490 s), past its end at 13 min 10 s
    report = classifier.take_shower_end()
    assert report is not None
    assert report.litres == pytest.approx(60.0)
    assert report.minutes == pytest.approx(8.0)


def test_litres_reclassified_at_detection_belong_to_the_shower() -> None:
    """The litres of the reclassify window count in the shower, with their time of flow."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 1000.0, "L")
    meter = 1000.0
    for seconds in (10, 40, 70):  # 3 L before detection, 1 minute of flow
        meter = _draw(classifier, meter, seconds, 1.0)
    assert not classifier.detected
    classifier.on_humidity(T0 + 75 * SECOND, "bath", 55.0)
    classifier.on_humidity(T0 + 80 * SECOND, "bath", 70.0)
    meter = _draw(classifier, meter, 100, 1.0)
    classifier.update(T0 + 100 * SECOND + 5 * MINUTE)
    report = classifier.take_shower_end()
    assert report is not None
    assert report.litres == pytest.approx(3.0)
    assert report.minutes == pytest.approx(90 / 60)


def test_detection_without_a_draw_reports_no_shower() -> None:
    """A humidity rise with no water drawn ends without a report."""
    classifier = DrawClassifier(ClassifierOptions())
    _detect_by_humidity(classifier)
    classifier.on_humidity(T0 + 10 * MINUTE, "bath", 55.0)
    assert classifier.take_shower_end() is None


def test_steady_shower() -> None:
    """24 L in the last 2 minutes of flow is a rolling flow of 12.0 L/min."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 1000.0, "L")
    _detect_by_humidity(classifier)
    meter = 1000.0
    for step in range(37):  # 1 L every 5 s for 3 minutes
        meter = _draw(classifier, meter, 10 + 5 * step, 1.0)
    assert classifier.rolling_flow == pytest.approx(12.0)


def test_pause_in_the_shower() -> None:
    """15 L in 2 minutes of flow, then 3 minutes with the water off: still 7.5 L/min."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 1000.0, "L")
    _detect_by_humidity(classifier)
    meter = 1000.0
    for step in range(16):  # 1 L every 8 s for 2 minutes
        meter = _draw(classifier, meter, 10 + 8 * step, 1.0)
    assert classifier.rolling_flow == pytest.approx(7.5)
    classifier.update(T0 + 130 * SECOND + 3 * MINUTE)
    assert classifier.detected
    assert classifier.rolling_flow == pytest.approx(7.5)
    # The next session starts after the pause: the pause is no flow, so the flow is not diluted.
    meter = _draw(classifier, meter, 130 + 180 + 5, 1.0)
    meter = _draw(classifier, meter, 130 + 180 + 15, 2.0)
    assert classifier.rolling_flow == pytest.approx((2.0 + 13.0) / 114 * 60)


def test_too_little_flow_yet() -> None:
    """A detected shower with 40 seconds of flow has no rolling flow."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 1000.0, "L")
    _detect_by_humidity(classifier)
    meter = 1000.0
    for step in range(6):  # 40 s of flow
        meter = _draw(classifier, meter, 10 + 8 * step, 1.0)
    assert classifier.rolling_flow is None
    meter = _draw(classifier, meter, 10 + 8 * 6 + 20, 3.0)  # 60 s of flow now
    assert classifier.rolling_flow is not None


def test_no_rolling_flow_without_a_detected_shower() -> None:
    """Draws that are no shower have no rolling flow."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 1000.0, "L")
    meter = 1000.0
    for step in range(16):
        meter = _draw(classifier, meter, 10 + 8 * step, 1.0)
    assert classifier.rolling_flow is None


def test_the_shower_in_progress_is_saved() -> None:
    """A restart during a shower keeps its litres and flow, and a state without it loads."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_meter(T0, 1000.0, "L")
    _detect_by_humidity(classifier)
    meter = 1000.0
    for step in range(16):
        meter = _draw(classifier, meter, 10 + 8 * step, 1.0)
    state = classifier.to_dict()
    restored = DrawClassifier(ClassifierOptions())
    restored.restore(json.loads(json.dumps(state)))
    assert restored.rolling_flow == pytest.approx(7.5)
    restored.update(T0 + 130 * SECOND + 5 * MINUTE)
    report = restored.take_shower_end()
    assert report is not None
    assert report.litres == pytest.approx(15.0)

    del state["shower"]
    old = DrawClassifier(ClassifierOptions())
    old.restore(state)
    assert old.rolling_flow is None


HOUR_ = 60 * MINUTE


def _humid_classifier(**overrides: float) -> DrawClassifier:
    """A classifier with a bathroom sensor, a 4-hour humidity window and a reading before T0."""
    options = ClassifierOptions(
        humidity_configured=True, humidity_window=240.0, **overrides
    )
    classifier = DrawClassifier(options)
    classifier.on_humidity(T0 - 30 * MINUTE, "bath", 60.0)
    return classifier


def test_the_water_stops() -> None:
    """Last increase at 20:45:08, humidity 83 %: the shower ends at 20:50:08, the bathroom stays humid."""
    start = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)
    classifier = DrawClassifier(
        ClassifierOptions(humidity_configured=True, humidity_window=240.0)
    )
    classifier.on_humidity(start - 30 * MINUTE, "bath", 60.0)
    classifier.on_meter(start, 1000.0, "L")
    classifier.on_humidity(start + 10 * MINUTE, "bath", 83.0)
    assert classifier.detected
    meter = 1000.0
    last = start + 45 * MINUTE + 8 * SECOND
    now = start + 10 * MINUTE
    while now < last:
        meter += 5.0
        classifier.on_meter(now, meter, "L")
        now += 30 * SECOND
    meter += 5.0
    classifier.on_meter(last, meter, "L")
    classifier.on_humidity(last + 2 * MINUTE, "bath", 83.0)
    assert classifier.detected
    classifier.update(last + 5 * MINUTE - SECOND)
    assert classifier.detected
    classifier.update(last + 5 * MINUTE)  # 20:50:08
    assert not classifier.detected
    assert classifier.humid
    assert classifier.take_shower_end() is not None
    # The humidity reading that follows starts nothing.
    classifier.on_humidity(last + 6 * MINUTE, "bath", 83.0)
    assert not classifier.detected


def test_humidity_dips_while_the_water_runs() -> None:
    """Detected at 60.6 % with a minimum of 50.7 %, then 53.4 % while the water runs: the shower continues."""
    classifier = DrawClassifier(ClassifierOptions(humidity_configured=True))
    classifier.on_meter(T0, 1000.0, "L")
    classifier.on_humidity(T0, "bath", 50.7)
    classifier.on_humidity(T0 + 10 * MINUTE, "bath", 60.6)
    assert classifier.detected
    meter = 1000.0
    for step in range(61):  # water from minute 10 to minute 20, every 10 s
        meter = _draw(classifier, meter, 600 + step * 10, 1.0)
    classifier.on_humidity(T0 + 20 * MINUTE, "bath", 53.4)
    assert not classifier.humid
    assert classifier.detected
    result = classifier.on_meter(T0 + 20 * MINUTE + 10 * SECOND, meter + 1.0, "L")
    assert result is not None
    assert result.mixed


def test_humidity_rise_without_water() -> None:
    """A rise of 8 points with no water: detected, ended 5 minutes later, no shower reported."""
    classifier = DrawClassifier(ClassifierOptions())
    classifier.on_humidity(T0, "bath", 55.0)
    classifier.on_humidity(T0 + MINUTE, "bath", 63.0)
    assert classifier.detected
    classifier.update(T0 + 6 * MINUTE)
    assert not classifier.detected
    assert classifier.take_shower_end() is None


def _first_shower(classifier: DrawClassifier, start: datetime, end: datetime) -> float:
    """Run a shower by humidity from `start` to a last increase at `end`, 5 L every 30 s.

    Returns:
        The meter reading after the last increase.
    """
    classifier.on_meter(start, 1000.0, "L")
    classifier.on_humidity(start + SECOND, "bath", 85.0)
    meter = 1000.0
    now = start + 30 * SECOND
    while now <= end:
        meter += 5.0
        classifier.on_meter(now, meter, "L")
        now += 30 * SECOND
    classifier.update(end + 5 * MINUTE)
    assert not classifier.detected
    assert classifier.humid
    assert classifier.take_shower_end() is not None
    return meter


def test_second_shower() -> None:
    """Ended at 18:23, still humid: a session from 18:25 starts a shower at 18:30 and is its own shower."""
    day = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
    classifier = _humid_classifier()
    meter = _first_shower(
        classifier, day - 20 * MINUTE, day + 18 * MINUTE
    )  # ends 18:23
    results = []
    for step in range(21):  # 2 L every 20 s from 18:25:00 to 18:31:40: 42 L
        meter += 2.0
        results.append(
            classifier.on_meter(day + 25 * MINUTE + step * 20 * SECOND, meter, "L")
        )
    assert all(r is not None for r in results)
    mixed = [r.mixed for r in results if r is not None]
    assert mixed == [False] * 15 + [True] * 6  # the shower starts at 18:30:00
    assert results[15] is not None
    assert results[15].reclassified == pytest.approx(30.0)  # the litres since 18:25
    classifier.update(day + 25 * MINUTE + 400 * SECOND + 5 * MINUTE)
    report = classifier.take_shower_end()
    assert report is not None
    assert report.litres == pytest.approx(
        40.0
    )  # 42 L less the first increase of the session
    assert report.minutes == pytest.approx(400 / 60)


def test_washbasin_after_a_shower() -> None:
    """Humid after a shower, a washbasin draw of 12 L in 2.3 minutes: other draws."""
    day = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
    classifier = _humid_classifier()
    meter = _first_shower(classifier, day - 20 * MINUTE, day + 18 * MINUTE)
    results = []
    for step in range(1, 7):  # 2 L every 23 s: 12 L over 138 s
        meter += 2.0
        results.append(
            classifier.on_meter(day + 25 * MINUTE + step * 23 * SECOND, meter, "L")
        )
    assert all(r is not None and not r.mixed for r in results)
    assert not classifier.detected
    assert classifier.take_shower_end() is None


def test_the_humid_edge_is_saved_so_a_restart_starts_no_shower() -> None:
    """Restarted 10 minutes after a shower ended, still humid: the humidity starts nothing, a draw needs 5 minutes."""
    day = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
    classifier = _humid_classifier()
    meter = _first_shower(classifier, day - 20 * MINUTE, day + 18 * MINUTE)
    state = json.loads(json.dumps(classifier.to_dict()))
    restored = DrawClassifier(classifier.options)
    restored.restore(state)
    restored.on_humidity(day + 33 * MINUTE, "bath", 85.0)
    assert not restored.detected
    results = []
    for step in range(17):  # 1 L every 20 s from 18:35 for 5.3 minutes
        meter += 1.0
        results.append(
            restored.on_meter(day + 35 * MINUTE + step * 20 * SECOND, meter, "L")
        )
    mixed = [r.mixed for r in results if r is not None]
    assert mixed[:15] == [False] * 15
    assert mixed[15]


def test_a_shower_in_progress_ends_at_its_deadline_after_a_restart() -> None:
    """Back 2 minutes after the water stopped: still detected, ended 5 minutes after the last increase."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    classifier.on_meter(T0, 1000.0, "L")
    meter = 1000.0
    for step in range(1, 25):
        meter = _draw(classifier, meter, step * 10, 1.0)
    assert classifier.detected
    restored = DrawClassifier(classifier.options)
    restored.restore(json.loads(json.dumps(classifier.to_dict())))
    restored.update(T0 + 240 * SECOND + 2 * MINUTE)
    assert restored.detected
    restored.update(T0 + 240 * SECOND + 5 * MINUTE)
    assert not restored.detected
    assert restored.take_shower_end() is not None


def test_a_store_without_the_new_keys_loads() -> None:
    """A state of the previous release has no shower start: the shower takes its last increase."""
    classifier = DrawClassifier(ClassifierOptions(long_draw_minutes=3.0))
    classifier.on_meter(T0, 1000.0, "L")
    meter = 1000.0
    for step in range(1, 25):
        meter = _draw(classifier, meter, step * 10, 1.0)
    state = json.loads(json.dumps(classifier.to_dict()))
    del state["shower"]["start"]
    restored = DrawClassifier(classifier.options)
    restored.restore(state)
    assert restored.detected
    assert restored.shower_end == T0 + 240 * SECOND + 5 * MINUTE
    # A shower with no increase and no start time:
    state["shower"]["last"] = None
    # With neither, it starts at the next call.
    unknown = DrawClassifier(classifier.options)
    unknown.restore(state)
    assert unknown.shower_end is None
    unknown.update(T0 + 2 * HOUR_)
    assert unknown.shower_end == T0 + 2 * HOUR_ + 5 * MINUTE


def _previous_release_restore(data: dict) -> dict:
    """Read the keys the previous release's `DrawClassifier.restore` reads (commit 228b3d9)."""
    shower = data.get("shower")
    return {
        "last_litres": data["last_litres"],
        "session_start": data["session_start"],
        "last_increase": data["last_increase"],
        "others": [(datetime.fromisoformat(t), a) for t, a in data["others"]],
        "long_active": bool(data["long_active"]),
        "was_detected": bool(data["was_detected"]),
        "shower": None
        if shower is None
        else (
            float(shower["litres"]),
            float(shower["seconds"]),
            shower["last"],
            [(float(a), float(b)) for a, b in shower["recent"]],
        ),
        "humidity": {
            sensor_id: (
                [(datetime.fromisoformat(t), v) for t, v in item["readings"]],
                bool(item["active"]),
            )
            for sensor_id, item in data["humidity"].items()
        },
    }


def test_the_saved_state_keeps_the_keys_the_previous_release_reads() -> None:
    """A rollback restores the model: every key the previous release reads is written."""
    classifier = DrawClassifier(ClassifierOptions(humidity_configured=True))
    classifier.on_humidity(T0, "bath", 55.0)
    classifier.on_humidity(T0 + MINUTE, "bath", 70.0)
    meter = 1000.0
    classifier.on_meter(T0, meter, "L")
    for step in range(1, 5):
        meter = _draw(classifier, meter, 60 + step * 10, 1.0)
    state = json.loads(json.dumps(classifier.to_dict()))
    old = _previous_release_restore(state)
    assert old["long_active"] is False
    assert old["was_detected"] is True  # the humid edge state
    assert old["shower"] is not None
    assert old["humidity"]["bath"][1] is True
    # A shower with no water: `last` is still a key.
    empty = DrawClassifier(ClassifierOptions())
    empty.on_humidity(T0, "bath", 55.0)
    empty.on_humidity(T0 + MINUTE, "bath", 70.0)
    old = _previous_release_restore(json.loads(json.dumps(empty.to_dict())))
    assert old["shower"] == (0.0, 0.0, None, [])


def test_the_model_exposes_the_next_shower_end() -> None:
    """With a shower in progress the model gives its deadline, without one none."""
    model = make_model()
    assert model.next_shower_end is None
    model.on_water_meter(T0, 1000.0, "L")
    model.on_humidity(T0, "bath", 55.0)
    model.on_humidity(T0 + MINUTE, "bath", 70.0)
    assert model.next_shower_end == T0 + 6 * MINUTE
    model.on_water_meter(T0 + 2 * MINUTE, 1010.0, "L")
    assert model.next_shower_end == T0 + 7 * MINUTE
    model.tick(T0 + 7 * MINUTE)
    assert model.next_shower_end is None
    assert not model.shower_detected


def test_the_model_tells_the_classifier_a_humidity_sensor_is_configured() -> None:
    """The long-draw rule starts a shower only when the sources have no humidity sensor."""
    for sources, expected in (
        (Sources(energy_counter=True, humidity_sensors=("bath",)), False),
        (Sources(energy_counter=True), True),
    ):
        model = TankModel(
            ModelOptions(volume=281.0, long_draw_minutes=3.0), sources, T0, 57.0
        )
        meter = 1000.0
        model.on_water_meter(T0, meter, "L")
        for step in range(1, 25):  # 4 minutes of water, 1 L every 10 s
            meter += 1.0
            model.on_water_meter(T0 + step * 10 * SECOND, meter, "L")
        assert model.shower_detected is expected
        model.set_options(ModelOptions(volume=281.0, long_draw_minutes=3.0))
        assert model.shower_detected is expected


def test_the_model_restores_the_humid_bathroom_after_a_shower() -> None:
    """Restarted 10 minutes after a shower ended: no shower from the humidity, a draw needs 5 minutes."""
    model = make_model(humidity_window=240.0)
    model.on_humidity(T0 - 30 * MINUTE, "bath", 60.0)
    model.on_water_meter(T0, 1000.0, "L")
    model.on_humidity(T0 + SECOND, "bath", 85.0)
    meter = 1000.0
    for step in range(1, 21):  # 10 minutes of shower
        meter += 5.0
        model.on_water_meter(T0 + step * 30 * SECOND, meter, "L")
    model.tick(T0 + 15 * MINUTE)  # ended at 10:00 + 5 minutes
    assert not model.shower_detected
    saved = json.loads(json.dumps(model.to_dict()))
    restored = TankModel.from_dict(model.options, model.sources, saved)
    restored.on_humidity(T0 + 25 * MINUTE, "bath", 85.0)
    assert not restored.shower_detected
    meter += 1.0
    restored.on_water_meter(T0 + 26 * MINUTE, meter, "L")
    for step in range(1, 15):  # 1 L every 20 s: the session runs until 4 min 40 s
        meter += 1.0
        restored.on_water_meter(T0 + 26 * MINUTE + step * 20 * SECOND, meter, "L")
    assert not restored.shower_detected
    meter += 1.0
    restored.on_water_meter(T0 + 31 * MINUTE, meter, "L")  # 5 minutes of session
    assert restored.shower_detected


def test_the_model_restores_a_shower_in_progress() -> None:
    """Restarted during a shower, back 2 minutes after the water stopped: detected, ended 5 minutes after the last increase."""
    model = make_model()
    model.on_water_meter(T0, 1000.0, "L")
    model.on_humidity(T0, "bath", 55.0)
    model.on_humidity(T0 + SECOND, "bath", 70.0)
    meter = 1000.0
    for step in range(1, 11):
        meter += 5.0
        model.on_water_meter(T0 + step * 30 * SECOND, meter, "L")
    last = T0 + 5 * MINUTE
    saved = json.loads(json.dumps(model.to_dict()))
    restored = TankModel.from_dict(model.options, model.sources, saved)
    restored.tick(last + 2 * MINUTE)
    assert restored.shower_detected
    assert restored.next_shower_end == last + 5 * MINUTE
    restored.tick(last + 5 * MINUTE)
    assert not restored.shower_detected
    assert restored.next_shower_end is None


def test_the_session_shower_time_in_the_humid_bathroom() -> None:
    """Humid with no shower and a session open: the session start plus the next shower time."""
    classifier = DrawClassifier(
        ClassifierOptions(humidity_configured=True, next_shower_minutes=5.0)
    )
    assert classifier.session_shower_time is None
    classifier.on_humidity(T0, "bath", 61.0)
    classifier.on_humidity(T0 + 10 * MINUTE, "bath", 75.0)
    assert classifier.detected
    classifier.on_meter(T0 + 10 * MINUTE, 1000.0, "L")
    classifier.on_meter(T0 + 10 * MINUTE + 8 * SECOND, 1001.0, "L")
    assert classifier.session_shower_time is None  # a shower is in progress
    classifier.update(T0 + 16 * MINUTE)
    assert not classifier.detected
    assert classifier.humid
    assert classifier.session_shower_time is None  # no session is open
    start = T0 + 20 * MINUTE
    classifier.on_meter(start, 1002.0, "L")
    assert classifier.session_shower_time == start + 5 * MINUTE
    classifier.update(start + 2 * MINUTE)  # the session ended
    assert classifier.session_shower_time is None


def _humid_after_a_shower() -> tuple[DrawClassifier, datetime]:
    """Return a classifier in the humid tail of a shower, and a time with no session open."""
    classifier = DrawClassifier(
        ClassifierOptions(humidity_configured=True, next_shower_minutes=5.0)
    )
    classifier.on_humidity(T0, "bath", 61.0)
    classifier.on_humidity(T0 + 10 * MINUTE, "bath", 75.0)
    classifier.on_meter(T0 + 10 * MINUTE, 1000.0, "L")
    classifier.on_meter(T0 + 10 * MINUTE + 8 * SECOND, 1001.0, "L")
    classifier.update(T0 + 16 * MINUTE)
    assert not classifier.detected
    assert classifier.humid
    return classifier, T0 + 20 * MINUTE


def test_a_draw_one_second_before_the_session_shower_time_stays_an_other_draw() -> None:
    """The shower starts at the first meter increase at or after the session shower time."""
    early, start = _humid_after_a_shower()
    early.on_meter(start, 1002.0, "L")
    time = early.session_shower_time
    assert time == start + 5 * MINUTE
    for second in range(1, 301, 30):  # keep the session open with a draw every 30 s
        early.on_meter(start + second * SECOND, 1002.0 + second, "L")
    before = early.on_meter(time - SECOND, 1274.0, "L")
    assert before is not None
    assert not before.mixed
    assert not early.detected
    at = early.on_meter(time, 1275.0, "L")
    assert at is not None
    assert at.mixed
    assert early.detected


def test_the_session_expiry_is_a_moment_past_the_session_gap() -> None:
    """A draw at the gap continues the session; one at the expiry time opens a new one."""
    classifier, start = _humid_after_a_shower()
    assert classifier.session_expiry is None
    classifier.on_meter(start, 1002.0, "L")
    assert classifier.session_expiry == start + 61 * SECOND
    classifier.on_meter(start + 60 * SECOND, 1003.0, "L")  # exactly the session gap
    assert classifier.session_shower_time == start + 5 * MINUTE
    expiry = classifier.session_expiry
    assert expiry == start + 121 * SECOND
    classifier.update(expiry - SECOND)
    assert classifier.session_expiry == expiry  # the session is still open
    classifier.update(expiry)
    assert classifier.session_expiry is None
    assert classifier.session_shower_time is None


def test_the_model_exposes_the_next_shower_start() -> None:
    """In the humid tail the model gives the session start plus the next shower time."""
    model = make_model(next_shower_minutes=5.0)
    assert model.next_shower_start is None
    model.on_humidity(T0, "bath", 55.0)
    model.on_humidity(T0 + MINUTE, "bath", 70.0)
    model.on_water_meter(T0 + MINUTE, 1000.0, "L")
    model.on_water_meter(T0 + MINUTE + 8 * SECOND, 1001.0, "L")
    assert model.next_shower_start is None  # a shower is in progress
    model.tick(T0 + 7 * MINUTE)
    assert not model.shower_detected
    start = T0 + 10 * MINUTE
    model.on_water_meter(start, 1002.0, "L")
    assert model.next_shower_start == start + 5 * MINUTE
    model.tick(start + 2 * MINUTE)
    assert model.next_shower_start is None


def test_the_next_wake_up_is_the_earlier_of_the_shower_end_and_the_session_expiry() -> (
    None
):
    """The runtime wakes at the shower end, or just past a session expiry while a draw can become a shower."""
    model = make_model(next_shower_minutes=5.0)
    assert model.next_wake_up is None
    # A shower end alone: no session can become a shower while one is in progress.
    model.on_humidity(T0, "bath", 55.0)
    model.on_humidity(T0 + MINUTE, "bath", 70.0)
    model.on_water_meter(T0 + MINUTE, 1000.0, "L")
    model.on_water_meter(T0 + MINUTE + 8 * SECOND, 1001.0, "L")
    assert model.next_shower_end == T0 + MINUTE + 8 * SECOND + 5 * MINUTE
    assert model.next_wake_up == model.next_shower_end
    model.tick(T0 + 7 * MINUTE)
    assert not model.shower_detected
    assert model.next_wake_up is None
    # A session expiry alone: the bathroom is humid, no shower is in progress.
    start = T0 + 10 * MINUTE
    model.on_water_meter(start, 1002.0, "L")
    assert model.next_shower_end is None
    assert model.next_wake_up == start + 61 * SECOND
    # The humidity falling away leaves nothing to count down, so no wake-up.
    model.on_humidity(start + 10 * SECOND, "bath", 50.0)
    assert model.next_shower_start is None
    assert model.next_wake_up is None


def test_the_next_wake_up_picks_the_earlier_of_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The classifier never has both at once, so give the model each in turn to check the minimum."""
    model = make_model(next_shower_minutes=5.0)
    start = T0 + 10 * MINUTE
    model.on_humidity(T0, "bath", 55.0)
    model.on_humidity(T0 + MINUTE, "bath", 70.0)
    model.on_water_meter(T0 + 5 * MINUTE, 1000.0, "L")  # the meter baseline
    model.tick(T0 + 7 * MINUTE)
    model.on_water_meter(start, 1002.0, "L")
    expiry = start + 61 * SECOND
    assert model.next_wake_up == expiry
    for end, earlier in ((expiry - SECOND, expiry - SECOND), (expiry + SECOND, expiry)):
        monkeypatch.setattr(TankModel, "next_shower_end", property(lambda _, e=end: e))
        assert model.next_wake_up == earlier


def test_the_session_shower_time_without_a_humid_bathroom() -> None:
    """A dry bathroom with a humidity sensor gives none; the long draw rule needs no sensor."""
    configured = DrawClassifier(
        ClassifierOptions(humidity_configured=True, long_draw_minutes=8.0)
    )
    configured.on_meter(T0, 1000.0, "L")
    configured.on_meter(T0 + 8 * SECOND, 1001.0, "L")
    assert configured.session_shower_time is None
    plain = DrawClassifier(ClassifierOptions(long_draw_minutes=8.0))
    plain.on_meter(T0, 1000.0, "L")
    plain.on_meter(T0 + 8 * SECOND, 1001.0, "L")
    assert plain.session_shower_time == T0 + 8 * SECOND + 8 * MINUTE
    off = DrawClassifier(ClassifierOptions())
    off.on_meter(T0, 1000.0, "L")
    off.on_meter(T0 + 8 * SECOND, 1001.0, "L")
    assert off.session_shower_time is None


# ----- humidity silence and the detection backup -------------------------------------------

SILENCE_START = datetime(2026, 10, 10, 15, 44, 24, tzinfo=UTC)


def _silence_model(
    sensors: tuple[str, ...] = ("bath",), **overrides: float
) -> TankModel:
    """A 285 L tank started at 15:44:24 whose humidity sensors all reported 58 % just then."""
    model = TankModel(
        ModelOptions(volume=285.0, **overrides),
        Sources(energy_counter=True, humidity_sensors=sensors),
        SILENCE_START,
        57.0,
    )
    for sensor in sensors:
        model.on_humidity(SILENCE_START, sensor, 58.0)
    return model


def _session(
    model: TankModel, start: datetime, step: timedelta, count: int, litres: float
) -> datetime | None:
    """Draw `litres` in `count` equal increases from `start`, `step` apart.

    Returns:
        The time of the increase at which a shower was first detected, None if it never was.
    """
    meter = 1000.0
    model.on_water_meter(start - 10 * SECOND, meter, "L")
    started = None
    for index in range(count):
        meter += litres / count
        now = start + index * step
        model.on_water_meter(now, meter, "L")
        if started is None and model.shower_detected:
            started = now
    return started


def test_sensor_goes_quiet() -> None:
    """Silence time 2 h, last report 15:44:24: silent from 17:44:24, not at its next report."""
    model = _silence_model()
    assert not model.humidity_silent("bath", SILENCE_START + 2 * HOUR_ - SECOND)
    assert model.humidity_silent("bath", SILENCE_START + 2 * HOUR_)
    assert model.humidity_degraded(SILENCE_START + 2 * HOUR_)
    model.on_humidity(SILENCE_START + 2 * HOUR_ + 10 * MINUTE, "bath", 58.0)
    assert not model.humidity_silent("bath", SILENCE_START + 2 * HOUR_ + 10 * MINUTE)
    assert not model.humidity_degraded(SILENCE_START + 2 * HOUR_ + 10 * MINUTE)


def test_unchanged_reports() -> None:
    """A sensor that reports 58.5 % every 10 minutes for 3 hours without a change is never silent."""
    model = _silence_model()
    model.on_humidity(SILENCE_START, "bath", 58.5)
    for step in range(1, 19):
        now = SILENCE_START + step * 10 * MINUTE
        # No state change: only the state's last_reported moves, which the tick passes on.
        model.tick(now, {"bath": now})
        assert not model.humidity_silent("bath", now)
        assert not model.humidity_degraded(now)
    # The same sensor without those reports is silent from 2 hours after its last one.
    quiet = _silence_model()
    quiet.tick(SILENCE_START + 3 * HOUR_)
    assert quiet.humidity_silent("bath", SILENCE_START + 3 * HOUR_)


def test_silence_check_off() -> None:
    """Silence time 0 and 5 hours without a report: not silent, not degraded."""
    model = _silence_model(humidity_silence=0.0)
    now = SILENCE_START + 5 * HOUR_
    model.tick(now)
    assert not model.humidity_silent("bath", now)
    assert not model.humidity_degraded(now)


def test_a_sensor_without_a_report_counts_from_the_start() -> None:
    """A sensor that never reported is silent 2 hours after the start of the model."""
    model = TankModel(
        ModelOptions(volume=285.0),
        Sources(energy_counter=True, humidity_sensors=("bath",)),
        SILENCE_START,
        57.0,
    )
    assert not model.humidity_silent("bath", SILENCE_START + 2 * HOUR_ - SECOND)
    assert model.humidity_silent("bath", SILENCE_START + 2 * HOUR_)
    status = model.humidity_status(SILENCE_START + 3 * HOUR_)
    assert status == {
        "bath": {"last_report": None, "unavailable": False, "silent": True}
    }


def test_a_state_read_at_a_restart_counts_from_its_last_report() -> None:
    """A reading reported 90 minutes before it is silent 30 minutes later, not 2 hours."""
    model = _silence_model()
    restart = SILENCE_START + 4 * HOUR_
    model.on_humidity(restart, "bath", 58.0, restart - 90 * MINUTE)
    assert not model.humidity_silent("bath", restart + 29 * MINUTE)
    assert model.humidity_silent("bath", restart + 30 * MINUTE)
    # An older report never moves the last one back.
    model.on_humidity(restart + 31 * MINUTE, "bath", 58.0, restart - 100 * MINUTE)
    assert model.humidity_silent("bath", restart + 31 * MINUTE)


def test_a_sensor_that_is_not_configured_is_ignored() -> None:
    """A reading of an unknown sensor adds no report and does not change the degraded state."""
    model = _silence_model()
    model.on_humidity(SILENCE_START + MINUTE, "other", 58.0)
    model.on_humidity(SILENCE_START + 2 * MINUTE, "other", None)
    assert set(model.humidity_status(SILENCE_START)) == {"bath"}
    assert set(model.to_dict()["humidity_reports"]) == {"bath"}
    assert not model.humidity_degraded(SILENCE_START + 2 * MINUTE)


def test_an_unavailable_sensor_is_not_silent_but_counts_as_out() -> None:
    """Unavailable is its own state: not silent, but the fallback holds while it is the only sensor."""
    model = _silence_model()
    now = SILENCE_START + 10 * MINUTE
    model.on_humidity(now, "bath", None)
    assert not model.humidity_silent("bath", now + 5 * HOUR_)
    assert model.humidity_degraded(now)
    model.on_humidity(now + MINUTE, "bath", 58.0)
    assert not model.humidity_degraded(now + MINUTE)


def test_shower_during_a_silence() -> None:
    """Silent since 17:44:24, a session 17:54:32-18:04:42 with 71 L: a shower from 17:59:32, 71 L mixed."""
    model = _silence_model()
    start = datetime(2026, 10, 10, 17, 54, 32, tzinfo=UTC)
    started = _session(model, start, 10 * SECOND, 62, 71.0)
    assert started == datetime(2026, 10, 10, 17, 59, 32, tzinfo=UTC)
    sums = model.interval_sums
    assert sums.mixed == pytest.approx(71 * (38 - model.t_cold) / 285)
    # The other-draw energy is subtracted at the current balance T_ch, which standing loss lowered
    # during the session, so a remainder of about 0.0008 K is left.
    assert sums.other == pytest.approx(0, abs=1e-3)
    end = datetime(2026, 10, 10, 18, 4, 42, tzinfo=UTC)
    model.tick(end + 5 * MINUTE)
    assert not model.shower_detected


def test_short_draw_during_a_silence() -> None:
    """A session of 4.4 minutes and 22 L while silent stays other draws."""
    model = _silence_model()
    start = datetime(2026, 10, 10, 17, 54, 32, tzinfo=UTC)
    assert _session(model, start, 12 * SECOND, 23, 22.0) is None
    assert model.humidity_degraded(start)
    assert model.interval_sums.mixed == 0.0
    assert model.interval_sums.other > 0.0


def test_sensor_unavailable() -> None:
    """The only humidity sensor is unavailable and a session runs for 5 minutes: a shower starts."""
    model = _silence_model()
    start = SILENCE_START + MINUTE
    model.on_humidity(start - 30 * SECOND, "bath", None)
    started = _session(model, start, 10 * SECOND, 40, 20.0)
    assert started == start + 5 * MINUTE


def test_one_of_two_sensors_still_reports() -> None:
    """One sensor unavailable, the other reports without a rise: an 8-minute session starts nothing."""
    model = _silence_model(("bath", "hall"))
    start = SILENCE_START + 3 * HOUR_
    model.on_humidity(start - 5 * MINUTE, "hall", None)
    model.on_humidity(start - 4 * MINUTE, "bath", 58.0)
    assert not model.humidity_degraded(start)
    assert _session(model, start, 10 * SECOND, 49, 30.0) is None
    assert model.interval_sums.mixed == 0.0
    assert model.interval_sums.other > 0.0


def test_sensor_reports_again() -> None:
    """A shower the fallback started continues when the sensor reports, to the shower end time."""
    model = _silence_model()
    start = datetime(2026, 10, 10, 17, 54, 32, tzinfo=UTC)
    meter = 1000.0
    model.on_water_meter(start - 10 * SECOND, meter, "L")
    for index in range(40):  # 6 minutes and 30 seconds of water
        meter += 1.0
        model.on_water_meter(start + index * 10 * SECOND, meter, "L")
    last = start + 390 * SECOND
    assert model.shower_detected
    model.on_humidity(last, "bath", 58.0)
    assert not model.humidity_degraded(last)
    assert model.shower_detected
    meter += 1.0
    model.on_water_meter(last + 10 * SECOND, meter, "L")
    assert model.shower_detected
    assert model.next_shower_end == last + 10 * SECOND + 5 * MINUTE
    model.tick(last + 10 * SECOND + 5 * MINUTE)
    assert not model.shower_detected


def test_the_countdown_follows_the_degraded_state() -> None:
    """While silent the countdown is the session start plus the next shower time; a report clears it."""
    model = _silence_model()
    start = datetime(2026, 10, 10, 17, 54, 32, tzinfo=UTC)
    model.on_water_meter(start - 10 * SECOND, 1000.0, "L")
    model.on_water_meter(start, 1001.0, "L")
    assert model.next_shower_start == start + 5 * MINUTE
    # A sensor that reports before the session starts is not silent.
    live = _silence_model()
    live.on_humidity(start - MINUTE, "bath", 58.0)
    live.on_water_meter(start - 10 * SECOND, 1000.0, "L")
    live.on_water_meter(start, 1001.0, "L")
    assert live.next_shower_start is None
    # A silence time of 0 turns the backup off with it.
    off = _silence_model(humidity_silence=0.0)
    off.on_water_meter(start - 10 * SECOND, 1000.0, "L")
    off.on_water_meter(start, 1001.0, "L")
    assert off.next_shower_start is None


def test_the_classifier_follows_the_flag_it_is_given() -> None:
    """`degraded` is not saved: a restored classifier has it off until the next call passes it."""
    classifier = DrawClassifier(ClassifierOptions(humidity_configured=True))
    classifier.on_meter(T0, 1000.0, "L", degraded=True)
    classifier.on_meter(T0 + 10 * SECOND, 1001.0, "L", degraded=True)
    assert classifier.session_shower_time == T0 + 10 * SECOND + 5 * MINUTE
    restored = DrawClassifier(classifier.options)
    restored.restore(json.loads(json.dumps(classifier.to_dict())))
    assert restored.session_shower_time is None
    restored.update(T0 + 20 * SECOND, degraded=True)
    assert restored.session_shower_time == T0 + 10 * SECOND + 5 * MINUTE
