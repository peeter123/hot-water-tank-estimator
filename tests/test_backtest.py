"""Tests for `scripts/backtest.py`: it fits the same parameters as the setup fit."""

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from custom_components.hot_water_tank_estimator.model import ModelOptions
from custom_components.hot_water_tank_estimator.setup_fit import (
    history_from_fixture,
    setup_fit,
)

ROOT = Path(__file__).parent.parent
WEEK = ROOT / "tests" / "fixtures" / "week.json"


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
