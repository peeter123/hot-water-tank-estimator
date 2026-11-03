"""Backtest the tank model and the setup fit on recorded history.

Usage:
    uv run --no-project scripts/backtest.py INPUT [--volume LITRES] [--sensor-height FRACTION]
        [--options JSON | --options-file FILE] [--lock PARAMETER ...] [--days N]
        [--map-file FILE.json] [--map STEM=ROLE ...] [--water-unit UNIT]

`INPUT` is a replay fixture (one JSON file, the format of `scripts/anonymise.py`) or a history
export folder as written by `scripts/history.py` (one `<stem>.json` per source with
`[time, state]` rows). The tank volume and sensor height come from a fixture; an export needs
`--volume` and takes `--sensor-height` (default 0.5). A stem that is a role name needs no
mapping, any other stem is mapped to a role by `--map STEM=ROLE` or a JSON file
`{"stem": "role"}` (such a file holds installation names and stays in `private/`). Files whose
stem has no role are left out. Meters have no unit in an export, so `--water-unit` (default
m3) names it.

`--options` takes the tuning values as JSON (the field names of `ModelOptions`, for example
`{"sensor_tolerance": 2.0}`), `--lock` keeps a learned parameter at its option value, and
`--days` fits the last N days only.

It replays the history twice through the same code as the setup fit of a config entry
(`setup_fit.py`) and prints:
  - the charge error at every closure, with the options as given and with the fitted ones;
  - the outputs through every shower;
  - the fitted parameters;
  - the mean absolute charge error with the fitted parameters against the options as given.

The pure modules import only the standard library, but the package `__init__` imports Home
Assistant. So this script loads `model.py`, `classification.py`, `calibration.py` and
`setup_fit.py` as a package of its own, without that `__init__`. They need Python 3.14, the
version of the repository (`.python-version`), which `uv run` selects; no packages are needed.
Standard library only.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime
import importlib
import json
from pathlib import Path
import sys
import types
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = ROOT / "custom_components" / "hot_water_tank_estimator"
PURE_PACKAGE = "hwte_pure"
MIN_PYTHON = (3, 14)
DEFAULT_SENSOR_HEIGHT = 0.5


def load_pure() -> types.SimpleNamespace:
    """Load the pure modules without the package `__init__` (which imports Home Assistant).

    Returns:
        A namespace with the modules `model`, `calibration` and `setup_fit`.
    """
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(
            "The model needs Python 3.14 or later: run `uv run --no-project scripts/backtest.py`"
        )
    if PURE_PACKAGE not in sys.modules:
        package = types.ModuleType(PURE_PACKAGE)
        package.__path__ = [str(PACKAGE_DIR)]
        sys.modules[PURE_PACKAGE] = package
    return types.SimpleNamespace(
        **{
            name: importlib.import_module(f"{PURE_PACKAGE}.{name}")
            for name in ("model", "calibration", "setup_fit")
        }
    )


def read_history(
    pure: types.SimpleNamespace,
    path: Path,
    *,
    stem_roles: dict[str, str] | None = None,
    water_unit: str = "m3",
) -> tuple[Any, dict[str, float]]:
    """Read a fixture or an export folder.

    Args:
        pure: The loaded pure modules.
        path: A fixture file or an export folder.
        stem_roles: The role of each file stem of an export (stems named like a role need none).
        water_unit: The water meter unit of an export.

    Returns:
        The history and the tank figures a fixture holds (`volume`, `sensor_height`).

    Raises:
        SystemExit: The path is neither, or an export has no readable source.
    """
    setup_fit = pure.setup_fit
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return setup_fit.history_from_fixture(data), dict(data.get("tank", {}))
    if not path.is_dir():
        raise SystemExit(f"{path} is neither a fixture file nor an export folder")
    stem_roles = stem_roles or {}
    roles = {
        setup_fit.TANK_TEMPERATURE,
        setup_fit.WATER_METER,
        setup_fit.DHW_ENERGY,
        setup_fit.DHW_POWER,
        setup_fit.DHW_HEATING,
        setup_fit.FLOW_TEMPERATURE,
        setup_fit.RETURN_TEMPERATURE,
        setup_fit.BATHROOM_HUMIDITY,
        setup_fit.COLD_WATER_TEMPERATURE,
        setup_fit.AMBIENT_TEMPERATURE,
    }
    series = []
    for file in sorted(path.glob("*.json")):
        role = stem_roles.get(file.stem, file.stem if file.stem in roles else None)
        if role is None:
            continue
        rows = json.loads(file.read_text(encoding="utf-8"))
        states = [(datetime.fromisoformat(time), str(state)) for time, state in rows]
        unit = water_unit if role == setup_fit.WATER_METER else None
        series.append(setup_fit.Series(role, f"{role}.{file.stem}", unit, states))
    if not series:
        raise SystemExit(f"No source file with a known role in {path}")
    start = min(s.states[0][0] for s in series if s.states)
    end = max(s.states[-1][0] for s in series if s.states)
    return setup_fit.History(start, end, series), {}


@dataclass
class BacktestResult:
    """What the backtest computed.

    Attributes:
        history: The replayed history.
        options: The options as given.
        fit: The setup fit.
        given: The replay with the options as given.
        fitted: The replay with the fitted options.
    """

    history: Any
    options: Any
    fit: Any
    given: Any
    fitted: Any


def run_backtest(
    pure: types.SimpleNamespace,
    history: Any,
    options: Any,
    *,
    locks: frozenset[str] = frozenset(),
    days: float | None = None,
) -> BacktestResult:
    """Fit the parameters to a history and compare the fitted options with the given ones."""
    if days is not None:
        history = history.last_days(days)
    fit = pure.setup_fit.setup_fit(history, options, locks=locks)
    return BacktestResult(
        history,
        options,
        fit,
        pure.setup_fit.evaluate(history, options),
        pure.setup_fit.evaluate(history, fit.options),
    )


def _fmt(value: float | None, digits: int = 2) -> str:
    """Return a number with fixed digits, or `-` for None."""
    return "-" if value is None else f"{value:.{digits}f}"


def report(result: BacktestResult, pure: types.SimpleNamespace) -> str:
    """Return the backtest as text."""
    lines: list[str] = []
    history, fit = result.history, result.fit
    sources = pure.setup_fit.sources_for(history)
    lines.append(
        f"History: {history.start:%Y-%m-%d %H:%M} to {history.end:%Y-%m-%d %H:%M} UTC"
    )
    lines.append(
        f"Volume {result.options.volume:g} L, sensor height {result.options.sensor_height:g}; "
        f"sources: {', '.join(k for k, v in vars(sources).items() if v) or 'none'}"
    )

    lines += [
        "",
        "Charge errors in K (model T_avg at the run start minus the true one)",
    ]
    lines.append(
        f"{'run end (UTC)':<17} {'status':<13} {'hours':>6} {'E kWh':>6} "
        f"{'given':>7} {'fitted':>7}  note"
    )
    fitted_by_end = {c.run_end: c for c in result.fitted.closures}
    for closure in result.given.closures:
        other = fitted_by_end.get(closure.run_end)
        note = closure.reason or ""
        lines.append(
            f"{closure.run_end:%Y-%m-%d %H:%M}   {closure.status:<13} "
            f"{_fmt(closure.hours, 1):>6} {_fmt(closure.energy_kwh):>6} "
            f"{_fmt(closure.error):>7} {_fmt(other.error if other else None):>7}  {note}"
        )

    lines += [
        "",
        "Showers (tank litres / shower litres at the start, each quarter and the end)",
    ]
    for label, evaluation in (("given", result.given), ("fitted", result.fitted)):
        for shower in evaluation.showers():
            points = "  ".join(
                f"{litres:3.0f} L: {snap.tank_litres:3.0f}/{snap.shower_litres:3.0f}"
                for litres, snap in shower.points
            )
            lines.append(
                f"{shower.start:%Y-%m-%d %H:%M} {shower.litres:4.0f} L "
                f"({shower.mixed_litres:3.0f} mixed) {label:<6} {points}"
            )

    lines += ["", f"{'parameter':<20} {'given':>9} {'fitted':>9}  source"]
    for name, (value, source) in fit.parameters.items():
        given = getattr(result.options, name)
        lines.append(f"{name:<20} {given:>9.4f} {value:>9.4f}  {source}")
    lines.append(
        f"quiet-window loss estimates: {[round(v, 4) for v in fit.calibrator.quiet_estimates]}"
    )
    lines.append(
        f"first-drop width estimates: {[round(v, 3) for v in fit.calibrator.width_estimates]}"
    )

    lines += ["", "Summary"]
    for label, evaluation in (("given", result.given), ("fitted", result.fitted)):
        errors = [abs(c.error) for c in evaluation.intervals if c.error is not None]
        worst = max(errors, default=None)
        lines.append(
            f"{label:<6} options: {len(errors)} closures, mean absolute error "
            f"{_fmt(evaluation.mean_abs_error)} K, worst {_fmt(worst)} K"
        )
    excluded = [
        c for c in result.given.closures if c.status == pure.calibration.EXCLUDED
    ]
    for closure in excluded:
        lines.append(f"excluded: {closure.run_end:%Y-%m-%d %H:%M} {closure.reason}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("input", type=Path, help="a fixture file or an export folder")
    parser.add_argument("--volume", type=float, help="tank volume in litres")
    parser.add_argument("--sensor-height", type=float, help="tank sensor height, 0-1")
    parser.add_argument("--options", help="tuning values as JSON")
    parser.add_argument(
        "--options-file", type=Path, help="tuning values as a JSON file"
    )
    parser.add_argument("--lock", action="append", default=[], metavar="PARAMETER")
    parser.add_argument("--days", type=float, help="fit the last N days only")
    parser.add_argument("--map-file", type=Path, help="JSON {stem: role} for an export")
    parser.add_argument("--map", action="append", default=[], metavar="STEM=ROLE")
    parser.add_argument("--water-unit", default="m3", help="meter unit of an export")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the backtest from the command line."""
    args = build_parser().parse_args(argv)
    pure = load_pure()
    stem_roles: dict[str, str] = {}
    if args.map_file:
        stem_roles.update(json.loads(args.map_file.read_text(encoding="utf-8")))
    for item in args.map:
        stem, _, role = item.partition("=")
        stem_roles[stem] = role
    history, tank = read_history(
        pure, args.input, stem_roles=stem_roles, water_unit=args.water_unit
    )

    values: dict[str, Any] = {}
    if args.options_file:
        values.update(json.loads(args.options_file.read_text(encoding="utf-8")))
    if args.options:
        values.update(json.loads(args.options))
    volume = args.volume if args.volume is not None else tank.get("volume")
    if volume is None:
        raise SystemExit("The tank volume is needed: pass --volume")
    height = args.sensor_height
    if height is None:
        height = tank.get("sensor_height", DEFAULT_SENSOR_HEIGHT)
    values.setdefault("volume", volume)
    values.setdefault("sensor_height", height)
    options = pure.model.ModelOptions(**values)

    unknown = set(args.lock) - set(pure.calibration.PARAMETER_BOUNDS)
    if unknown:
        raise SystemExit(f"Unknown parameter to lock: {', '.join(sorted(unknown))}")
    result = run_backtest(
        pure, history, options, locks=frozenset(args.lock), days=args.days
    )
    print(report(result, pure))
    return 0


if __name__ == "__main__":
    sys.exit(main())
