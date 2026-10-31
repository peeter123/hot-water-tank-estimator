"""Cut a time window out of a history export into an anonymised replay fixture.

Usage:
    python scripts/anonymise.py EXPORT_DIR OUT.json --start 2026-10-29T17:00:00+00:00 \
        --end 2026-10-30T01:00:00+00:00 --name long_shower --description "text" \
        --volume 281 --sensor-height 0.5 [--map-file MAPPING.json] [--map FILE_STEM=ROLE] \
        [--thin ROLE=SECONDS] [--unit ROLE=UNIT]

`EXPORT_DIR` holds one `<stem>.json` per source, as written by `scripts/history.py`: a list of
`[last_changed, state]` rows in UTC ISO format. `history.py` names the files by role, and a stem
that is a role name needs no mapping. Any other stem is mapped to a role by `--map STEM=ROLE`
(repeatable) or by a JSON mapping file `{"stem": "role", ...}`, which belongs in the git-ignored
`private/` folder. The real entity IDs never appear here: the stems are file names and the
fixture gets made-up entity IDs. Files whose stem has no role are left out, so only the roles
the model uses end up in a fixture. A missing role file is a warning; a missing folder is an
error.

The roles and their made-up entity IDs:

    tank_temperature    sensor.tank_temperature      C
    water_meter         sensor.water_meter           m3 (override with --unit water_meter=L)
    dhw_energy          sensor.dhw_energy            kWh
    dhw_heating         binary_sensor.dhw_heating
    flow_temperature    sensor.flow_temperature      C
    return_temperature  sensor.return_temperature    C
    bathroom_humidity   sensor.bathroom_humidity     %

Fixture format, one JSON file:

    {
      "name": "...", "description": "...",
      "tank": {"volume": 281.0, "sensor_height": 0.5},
      "window": {"start": "<UTC ISO>", "end": "<UTC ISO>"},
      "entities": {
        "sensor.tank_temperature": {
          "role": "tank_temperature",
          "unit_of_measurement": "°C",
          "states": [["<UTC ISO time>", "<state text>"], ...]
        },
        ...
      }
    }

The rows of an entity are in time order. The first row is stamped at the window start and holds
the state in effect then (the last row before the window), so a replay starts with every source
known. Times stay as recorded, in UTC, rounded to the millisecond and written with a `Z`.
Attributes other than the unit are dropped. Consecutive rows with
the same state are merged into the first, and a numeric state that was a 32-bit float on the
device is written with the shortest digits that give the same 32-bit float. Every change of
every role is kept, including `unavailable`. `--thin ROLE=SECONDS` thins a role that is too
big: it keeps the first and last row, every non-numeric row, every decrease (a counter reset),
the last row of each burst (the next row is at least SECONDS later), a row at least SECONDS after
the last kept one, and the last row at or before and the first row at or after every change of
the `dhw_heating` role. For a cumulative counter that leaves the total exact and every increase
inside the same heating run as in the raw export. Standard library only.
"""

import argparse
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime, timedelta
import json
import math
from pathlib import Path
import struct
import sys

# role -> (made-up entity ID, unit of measurement or None)
ROLES: dict[str, tuple[str, str | None]] = {
    "tank_temperature": ("sensor.tank_temperature", "°C"),
    "water_meter": ("sensor.water_meter", "m3"),
    "dhw_energy": ("sensor.dhw_energy", "kWh"),
    "dhw_heating": ("binary_sensor.dhw_heating", None),
    "flow_temperature": ("sensor.flow_temperature", "°C"),
    "return_temperature": ("sensor.return_temperature", "°C"),
    "bathroom_humidity": ("sensor.bathroom_humidity", "%"),
}


def parse_time(text: str) -> datetime:
    """Parse an ISO time; a time without offset is UTC."""
    value = datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def compact_time(text: str) -> str:
    """Return a UTC time rounded to the millisecond: 2026-10-03T07:16:50.873Z."""
    time = parse_time(text).astimezone(UTC)
    millis = round(time.microsecond / 1000)
    time = time.replace(microsecond=0) + timedelta(milliseconds=millis)
    fraction = f".{time.microsecond // 1000:03d}" if time.microsecond else ""
    return time.strftime("%Y-%m-%dT%H:%M:%S") + fraction + "Z"


def thin_rows(
    rows: list[list[str]], seconds: float, edges: list[datetime]
) -> list[list[str]]:
    """Thin numeric rows as described in the module docstring.

    Args:
        rows: The rows of one role, in time order.
        seconds: The thinning interval.
        edges: The times of the heating state changes, around which every row is kept.
    """
    times = [parse_time(row[0]) for row in rows]
    pinned: set[int] = set()
    for edge in edges:
        after = bisect_left(times, edge)  # first row at or after the edge
        before = bisect_right(times, edge) - 1  # last row at or before it
        if 0 <= before < len(rows):
            pinned.add(before)
        if after < len(rows):
            pinned.add(after)
    kept: list[list[str]] = []
    for index, row in enumerate(rows):
        try:
            value = float(row[1])
        except ValueError:
            kept.append(row)
            continue
        if not kept or index == len(rows) - 1 or index in pinned:
            kept.append(row)
            continue
        gap_after = (times[index + 1] - times[index]).total_seconds()
        try:
            decreased = value < float(kept[-1][1])
        except ValueError:
            decreased = True
        since_kept = (times[index] - parse_time(kept[-1][0])).total_seconds()
        if decreased or gap_after >= seconds or since_kept >= seconds:
            kept.append(row)
    return kept


def shorten(state: str) -> str:
    """Shorten a state that is a 32-bit float written out with float64 digits.

    21.7000007629395 becomes 21.7. Other states are returned unchanged.
    """
    try:
        value = float(state)
    except ValueError:
        return state
    if not math.isfinite(value) or abs(value) > 1e30:
        return state
    single = struct.unpack("f", struct.pack("f", value))[0]
    if abs(single - value) > 1e-12 * max(1.0, abs(value)):
        return state
    for digits in range(1, 10):
        text = f"{single:.{digits}g}"
        if struct.unpack("f", struct.pack("f", float(text)))[0] == single:
            return text
    return state


def cut_rows(
    rows: list[list[str]],
    start: datetime,
    end: datetime,
    thin: float | None = None,
    edges: list[datetime] | None = None,
    *,
    compact: bool = True,
) -> list[list[str]]:
    """Return the rows of the window, led by the state in effect at its start."""
    before: list[str] | None = None
    inside: list[list[str]] = []
    for time_text, state in rows:
        time = parse_time(time_text)
        if time < start:
            before = [time_text, state]
        elif time <= end:
            inside.append([time_text, state])
    result: list[list[str]] = []
    if before is not None and (not inside or parse_time(inside[0][0]) > start):
        result.append([start.isoformat(), before[1]])
    result.extend(inside)
    merged: list[list[str]] = []
    for time_text, state in result:
        short = shorten(state)
        if merged and merged[-1][1] == short:
            continue
        merged.append([time_text, short])
    if thin:
        merged = thin_rows(merged, thin, edges or [])
    if not compact:
        return merged
    return [[compact_time(time_text), state] for time_text, state in merged]


def build_fixture(
    export: Path,
    roles_by_stem: dict[str, str],
    units: dict[str, str],
    thin: dict[str, float],
    start: datetime,
    end: datetime,
    meta: dict[str, object],
) -> dict[str, object]:
    """Build the fixture dict from an export folder."""
    entities: dict[str, object] = {}
    edges: list[datetime] = []
    for stem, role in roles_by_stem.items():
        path = export / f"{stem}.json"
        if role == "dhw_heating" and path.exists():
            rows = json.loads(path.read_text(encoding="utf-8"))
            edges = [
                parse_time(t) for t, _ in cut_rows(rows, start, end, compact=False)
            ]
    for stem, role in sorted(roles_by_stem.items(), key=lambda item: item[1]):
        path = export / f"{stem}.json"
        if not path.exists():
            continue
        entity_id, default_unit = ROLES[role]
        entry: dict[str, object] = {"role": role}
        unit = units.get(role, default_unit)
        if unit is not None:
            entry["unit_of_measurement"] = unit
        rows = json.loads(path.read_text(encoding="utf-8"))
        entry["states"] = cut_rows(rows, start, end, thin.get(role), edges)
        entities[entity_id] = entry
    for role, (entity_id, _) in ROLES.items():
        if entity_id not in entities:
            print(f"warning: no file for role {role} in {export}", file=sys.stderr)
    return {
        **meta,
        "window": {
            "start": compact_time(start.isoformat()),
            "end": compact_time(end.isoformat()),
        },
        "entities": entities,
    }


def write_fixture(fixture: dict[str, object], out: Path) -> None:
    """Write the fixture as JSON with one state row per line."""
    entities = fixture["entities"]
    assert isinstance(entities, dict)
    lines = ["{"]
    for key, value in fixture.items():
        if key != "entities":
            lines.append(f"{json.dumps(key)}: {json.dumps(value)},")
    lines.append('"entities": {')
    texts = []
    for entity_id, entry in entities.items():
        info = json.dumps({k: v for k, v in entry.items() if k != "states"})
        rows = ",\n".join(
            json.dumps(row, separators=(",", ":")) for row in entry["states"]
        )
        texts.append(f'{json.dumps(entity_id)}: {info[:-1]}, "states": [\n{rows}\n]}}')
    lines.append(",\n".join(texts))
    lines.append("}\n}\n")
    out.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the anonymiser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path, help="folder with the exported JSON files")
    parser.add_argument("out", type=Path, help="fixture file to write")
    parser.add_argument(
        "--start", required=True, help="window start, ISO (UTC if no offset)"
    )
    parser.add_argument(
        "--end", required=True, help="window end, ISO (UTC if no offset)"
    )
    parser.add_argument("--name", default="fixture")
    parser.add_argument("--description", default="")
    parser.add_argument(
        "--volume", type=float, required=True, help="tank volume in litres"
    )
    parser.add_argument(
        "--sensor-height", type=float, required=True, help="tank sensor height, 0-1"
    )
    parser.add_argument("--map", action="append", default=[], metavar="STEM=ROLE")
    parser.add_argument("--map-file", type=Path, help='JSON {"stem": "role"}')
    parser.add_argument("--thin", action="append", default=[], metavar="ROLE=SECONDS")
    parser.add_argument("--unit", action="append", default=[], metavar="ROLE=UNIT")
    args = parser.parse_args(argv)

    mapping: dict[str, str] = {role: role for role in ROLES}
    if args.map_file:
        mapping.update(json.loads(args.map_file.read_text(encoding="utf-8")))
    for item in args.map:
        stem, sep, role = item.partition("=")
        if not sep:
            parser.error(f"--map needs STEM=ROLE, got {item!r}")
        mapping[stem] = role
    unknown = sorted(set(mapping.values()) - set(ROLES))
    if unknown:
        parser.error(f"unknown roles: {', '.join(unknown)}")
    units: dict[str, str] = {}
    for item in args.unit:
        role, sep, unit = item.partition("=")
        if not sep or role not in ROLES:
            parser.error(f"--unit needs ROLE=UNIT with a known role, got {item!r}")
        units[role] = unit

    thin: dict[str, float] = {}
    for item in args.thin:
        role, sep, seconds = item.partition("=")
        if not sep or role not in ROLES:
            parser.error(f"--thin needs ROLE=SECONDS with a known role, got {item!r}")
        thin[role] = float(seconds)

    if not args.export.is_dir():
        print(f"error: export folder {args.export} not found", file=sys.stderr)
        return 1
    start, end = parse_time(args.start), parse_time(args.end)
    meta = {
        "name": args.name,
        "description": args.description,
        "tank": {"volume": args.volume, "sensor_height": args.sensor_height},
    }
    fixture = build_fixture(args.export, mapping, units, thin, start, end, meta)
    write_fixture(fixture, args.out)
    print(f"{args.out}: {args.out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
