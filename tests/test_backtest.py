"""Tests for `scripts/backtest.py`: it fits the same parameters as the setup fit."""

from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from custom_components.hot_water_tank_estimator.model import ModelOptions
from custom_components.hot_water_tank_estimator.setup_fit import (
    history_from_fixture,
    setup_fit,
)

ROOT = Path(__file__).parent.parent
WEEK = ROOT / "tests" / "fixtures" / "week.json"
BACK_TO_BACK = ROOT / "tests" / "fixtures" / "back_to_back.json"


def load_script() -> ModuleType:
    """Import `scripts/backtest.py` by path (`scripts/` is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "hwte_backtest_script", ROOT / "scripts" / "backtest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_week_fits_the_same_parameters_as_the_setup_fit() -> None:
    """The backtest loads the pure modules on its own and fits the same values as the package."""
    script = load_script()
    pure = script.load_pure()
    history, tank = script.read_history(pure, WEEK)
    data = json.loads(WEEK.read_text(encoding="utf-8"))
    assert tank == data["tank"]
    options = pure.model.ModelOptions(
        volume=tank["volume"], sensor_height=tank["sensor_height"]
    )
    result = script.run_backtest(pure, history, options)
    expected = setup_fit(
        history_from_fixture(data),
        ModelOptions(volume=tank["volume"], sensor_height=tank["sensor_height"]),
    ).parameters
    assert {n: v for n, (v, _) in result.fit.parameters.items()} == pytest.approx(
        {n: v for n, (v, _) in expected.items()}
    )
    assert {n: s for n, (_, s) in result.fit.parameters.items()} == {
        n: s for n, (_, s) in expected.items()
    }
    assert len(result.fit.intervals) == 7
    assert result.fitted.mean_abs_error < result.given.mean_abs_error


def test_the_report_has_every_section(capsys: pytest.CaptureFixture[str]) -> None:
    """The documented command prints the charge errors, showers, parameters and the comparison."""
    script = load_script()
    assert script.main([str(WEEK)]) == 0
    out = capsys.readouterr().out
    assert "Charge errors in K" in out
    assert out.count("closure ") >= 7
    assert "sensor_start" in out
    assert "Showers" in out and "given" in out and "fitted" in out
    assert "other_hot_share" in out and "startup_energy" in out
    assert "Summary" in out and "mean absolute error" in out


def test_options_locks_and_days(capsys: pytest.CaptureFixture[str]) -> None:
    """Options come from JSON, a lock keeps a parameter, and --days cuts the history."""
    script = load_script()
    argv = [
        str(WEEK),
        "--options",
        json.dumps({"other_hot_share": 0.25, "sensor_tolerance": 2.0}),
        "--lock",
        "other_hot_share",
    ]
    assert script.main(argv) == 0
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if line.startswith("other_hot_share"))
    assert "0.2500" in line and "locked" in line
    assert script.main([str(WEEK), "--days", "2"]) == 0
    assert "History: 2026-10-28 12:30 to 2026-10-30 12:30" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        script.main([str(WEEK), "--lock", "nonsense"])


def test_an_export_folder_needs_a_mapping_and_a_volume(tmp_path: Path) -> None:
    """A folder of `[time, state]` files is read by role, with a stem mapping for other names."""
    script = load_script()
    pure = script.load_pure()
    rows = [
        ["2026-10-01T10:00:00+00:00", "50.0"],
        ["2026-10-01T11:00:00+00:00", "49.0"],
    ]
    (tmp_path / "tank_temperature.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "meter.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "ignored.json").write_text(json.dumps(rows), encoding="utf-8")
    history, tank = script.read_history(
        pure, tmp_path, stem_roles={"meter": "water_meter"}, water_unit="L"
    )
    assert tank == {}
    assert {s.role for s in history.series} == {"tank_temperature", "water_meter"}
    assert next(s for s in history.series if s.role == "water_meter").unit == "L"
    assert history.end.hour == 11
    with pytest.raises(SystemExit):
        script.main([str(tmp_path)])  # no volume
    with pytest.raises(SystemExit):
        script.read_history(pure, tmp_path / "missing")
    # The ambient sensor is a role of the map file.
    (tmp_path / "room.json").write_text(json.dumps(rows), encoding="utf-8")
    history, _ = script.read_history(
        pure, tmp_path, stem_roles={"room": "ambient_temperature"}
    )
    assert "ambient_temperature" in {s.role for s in history.series}
    assert pure.setup_fit.sources_for(history).ambient_sensor


def test_the_shower_list_has_times_litres_minutes_and_the_flow_sample(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each shower line gives its start and end, litres, minutes of flow and the flow sample.

    Expected values for the first shower of `back_to_back`, derived from the fixture's raw
    meter rows (not from the script): its session starts at the first increase at 16:36:15
    UTC, ends at the last at 16:48:45 (12.5 min, a gap above 60 s starts the next session) and
    the meter rose 88.0 L from the reading before the first increase to the last. The flow
    sample is the model's own report at the end of detection. The humidity flickers in the
    first shower: detection starts at 16:37:17, drops after 16:38:50 and returns at
    16:41:40. The first fragment (16:36:15-16:38:50, 21 L, about 2.6 min) is under
    3 minutes, so it gives no sample. The sample counts from 16:39:00:
    (67 - 1) + (4 - 1) + (200 - 1) = 268 L in 9.75 + 0.42 + 30.53 = 40.70 min (the first
    increase of each session is left out), and `flow` is their quotient.
    """
    script = load_script()
    pure = script.load_pure()
    history, tank = script.read_history(pure, BACK_TO_BACK)
    options = pure.model.ModelOptions(
        volume=tank["volume"], sensor_height=tank["sensor_height"]
    )
    result = script.run_backtest(pure, history, options)
    first, second = result.given.showers()
    assert first.start.isoformat() == "2026-10-22T16:36:15.359000+00:00"
    assert first.end.isoformat() == "2026-10-22T16:48:45.359000+00:00"
    assert first.litres == pytest.approx(88.0)
    # Detection came during the session and reclassified its earlier litres (the replay test
    # `back_to_back` checks that no litre of either shower stays an other draw).
    assert first.mixed_litres == pytest.approx(88.0)
    assert second.mixed_litres == pytest.approx(200.0)
    assert (first.end - first.start).total_seconds() / 60 == pytest.approx(12.5)
    sample = script.shower_sample(result.given, first, pure)
    assert sample is not None
    assert sample.time >= first.end
    assert sample.change["litres"] == pytest.approx(268, abs=0.5)
    assert sample.change["minutes"] == pytest.approx(40.7, abs=0.05)
    assert sample.change["flow"] == pytest.approx(
        sample.change["litres"] / sample.change["minutes"]
    )
    # Detection holds across both showers, so they share the one sample.
    assert script.shower_sample(result.given, second, pure) is sample

    assert script.main([str(BACK_TO_BACK)]) == 0
    line = next(
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("2026-10-22 16:36-16:48")
    )
    assert (
        "88 L ( 88 mixed)" in line
        and "12.5 min" in line
        and "sample 6.58 L/min" in line
    )
    assert "268 L in 40.7 min" in line


def test_a_shower_under_three_minutes_of_flow_has_no_sample() -> None:
    """Below `SHOWER_MIN_MINUTES` of flow the list says `no sample`."""
    script = load_script()
    pure = script.load_pure()
    start = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    shower = pure.setup_fit.Shower(start, start + timedelta(minutes=2), 20.0, 20.0)
    evaluation = SimpleNamespace(replay=SimpleNamespace(events=[]))
    assert script.shower_sample(evaluation, shower, pure) is None
    assert script.shower_summary(evaluation, shower, pure).endswith(
        "2.0 min, no sample"
    )


def test_the_sample_match_stops_at_the_next_other_draw() -> None:
    """A sample reported after a draw counted as other does not belong to the shower."""
    script = load_script()
    pure = script.load_pure()
    kind = pure.model.EventKind
    start = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    shower = pure.setup_fit.Shower(start, start + timedelta(minutes=10), 80.0, 80.0)

    def event(minutes: int, event_kind: object, change: dict) -> SimpleNamespace:
        return SimpleNamespace(
            time=start + timedelta(minutes=minutes), kind=event_kind, change=change
        )

    sample = event(40, kind.SHOWER_FLOW, {"litres": 70, "minutes": 10, "flow": 7.0})
    other = event(20, kind.DRAW, {"litres": 1.0, "mixed": False})
    mixed = event(15, kind.DRAW, {"litres": 1.0, "mixed": True})
    run = SimpleNamespace(replay=SimpleNamespace(events=[mixed, sample]))
    assert script.shower_sample(run, shower, pure) is sample
    run = SimpleNamespace(replay=SimpleNamespace(events=[mixed, other, sample]))
    assert script.shower_sample(run, shower, pure) is None


def test_the_report_lists_every_sample_and_the_litre_totals(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The report has the list of all shower flow samples and the litres per options set.

    Expected values derived from the `back_to_back` fixture: the meter rose 373 L over the
    window (345.979 less 345.606 m3 in its raw rows), and the replay test of that fixture
    reclassifies 8 + 19 L in the first session and 9 L at 17:49:54 UTC, 36 L in all.
    """
    script = load_script()
    pure = script.load_pure()
    history, tank = script.read_history(pure, BACK_TO_BACK)
    options = pure.model.ModelOptions(
        volume=tank["volume"], sensor_height=tank["sensor_height"]
    )
    result = script.run_backtest(pure, history, options)
    drawn, mixed, reclassified = script.litre_totals(result.given, pure)
    assert drawn == pytest.approx(373.0)
    assert reclassified == pytest.approx(36.0)
    assert 288.0 <= mixed <= drawn  # both showers are fully mixed

    assert script.main([str(BACK_TO_BACK)]) == 0
    out = capsys.readouterr().out
    assert "Shower flow samples the model reported" in out
    assert "2026-10-22 17:44 given   268 L  40.7 min  6.58 L/min" in out
    assert "given  options: 373 L drawn" in out
    assert "36 L of them reclassified" in out
