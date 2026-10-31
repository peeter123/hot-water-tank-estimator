# ruff: noqa: INP001
"""Print the requirements of the Home Assistant components that hassfest imports.

Usage: hassfest_requirements.py CORE_DIR. Run at image build time. The components are found by
parsing the `from homeassistant.components.X` imports in CORE_DIR/script/hassfest/*.py, so a
new core version is picked up without a change here.
"""

import json
from pathlib import Path
import re
import sys

IMPORT = re.compile(r"^\s*from homeassistant\.components\.(\w+)", re.MULTILINE)


def main(core: Path) -> None:
    """Print one requirement per line, sorted and without duplicates."""
    components = set()
    for source in (core / "script" / "hassfest").glob("*.py"):
        components.update(IMPORT.findall(source.read_text(encoding="utf-8")))
    requirements = set()
    for name in sorted(components):
        manifest = core / "homeassistant" / "components" / name / "manifest.json"
        requirements.update(
            json.loads(manifest.read_text(encoding="utf-8")).get("requirements", [])
        )
    sys.stdout.write("".join(f"{line}\n" for line in sorted(requirements)))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
