"""Export recorder history of Home Assistant entities, one JSON file per role.

Usage:
    python scripts/history.py https://ha.example --out private/history/2026-10-01_2026-10-31 \
        --start 2026-10-01T00:00:00+00:00 --end 2026-10-31T00:00:00+00:00 \
        --role tank_temperature=sensor.x --role water_meter=sensor.y

Each `--role NAME=ENTITY_ID` writes `NAME.json` into the output folder: a list of
`[last_changed, state]` rows in UTC ISO format, all states including `unavailable`, oldest
first. The recorder starts the result of each request with the state in effect at the request's
start, stamped at that start, so the first row of a role is the state at `--start` and each
chunk boundary adds one row repeating the state in effect there. Rows with the same time and state
are written once. Errors (an unreadable token file, a rejected token, an HTTP or network error)
exit with status 1 and a message that never contains the token.
The long-lived access token is read from a file (default `%USERPROFILE%/.ha_token`) and is
never printed. Standard library only.
"""

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


def parse_time(text: str) -> datetime:
    """Parse an ISO time; a time without offset is UTC."""
    value = datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def fetch_rows(
    base_url: str, token: str, entity_id: str, start: datetime, end: datetime
) -> list[list[str]]:
    """Return the `[time, state]` rows of one entity between two times."""
    rows: list[list[str]] = []
    query = {
        "filter_entity_id": entity_id,
        "end_time": end.isoformat(),
        "minimal_response": "",
        "no_attributes": "",
        "significant_changes_only": "0",
    }
    url = (
        f"{base_url.rstrip('/')}/api/history/period/{urllib.parse.quote(start.isoformat())}"
        f"?{urllib.parse.urlencode(query)}"
    )
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.load(response)
    rows.extend(
        [state.get("last_changed") or state["last_updated"], state["state"]]
        for state in (data[0] if data else [])
    )
    return rows


def export(
    base_url: str,
    token: str,
    roles: dict[str, str],
    start: datetime,
    end: datetime,
    out: Path,
    chunk_days: int,
) -> None:
    """Write one JSON file per role into `out`, reading the range in chunks."""
    out.mkdir(parents=True, exist_ok=True)
    for role, entity_id in roles.items():
        rows: list[list[str]] = []
        seen: set[tuple[str, str]] = set()
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=chunk_days), end)
            for row in fetch_rows(base_url, token, entity_id, cursor, chunk_end):
                key = (row[0], row[1])
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
            cursor = chunk_end
        (out / f"{role}.json").write_text(json.dumps(rows), encoding="utf-8")
        print(f"{role}: {len(rows)} rows")


def main(argv: list[str] | None = None) -> int:
    """Run the export."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("base_url", help="Home Assistant base URL")
    parser.add_argument("--out", type=Path, required=True, help="output folder")
    parser.add_argument(
        "--start", required=True, help="start time, ISO (UTC if no offset)"
    )
    parser.add_argument("--end", help="end time, ISO; default now")
    parser.add_argument(
        "--role",
        action="append",
        required=True,
        metavar="NAME=ENTITY_ID",
        help="a role name and the entity to export for it; repeat for every role",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path.home() / ".ha_token",
        help="file with the long-lived access token (default ~/.ha_token)",
    )
    parser.add_argument("--chunk-days", type=int, default=2, help="days per request")
    args = parser.parse_args(argv)

    roles: dict[str, str] = {}
    for item in args.role:
        name, sep, entity_id = item.partition("=")
        if not sep or not name or not entity_id:
            parser.error(f"--role needs NAME=ENTITY_ID, got {item!r}")
        roles[name] = entity_id
    if args.chunk_days < 1:
        parser.error("--chunk-days must be at least 1")
    try:
        token = args.token_file.read_text(encoding="utf-8").strip()
    except OSError as err:
        print(
            f"error: cannot read the token file {args.token_file}: {err.strerror}",
            file=sys.stderr,
        )
        return 1
    start = parse_time(args.start)
    end = parse_time(args.end) if args.end else datetime.now(UTC)
    try:
        export(args.base_url, token, roles, start, end, args.out, args.chunk_days)
    except urllib.error.HTTPError as err:
        if err.code == 401:
            print("error: the token was rejected (HTTP 401)", file=sys.stderr)
        else:
            print(
                f"error: Home Assistant answered HTTP {err.code} {err.reason}",
                file=sys.stderr,
            )
        return 1
    except urllib.error.URLError as err:
        print(f"error: cannot reach {args.base_url}: {err.reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
