"""Tests for the integration manifest and HACS metadata."""

import json
from pathlib import Path

from custom_components.hot_water_tank_estimator.const import DOMAIN

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "hot_water_tank_estimator"
REPOSITORY_URL = "https://github.com/peeter123/hot-water-tank-estimator"


def test_manifest_fields() -> None:
    """The manifest has the fields the packaging spec requires."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text("utf-8"))
    assert manifest["domain"] == DOMAIN == "hot_water_tank_estimator"
    assert manifest["name"] == "Hot Water Tank Estimator"
    assert manifest["version"] == "0.0.1"
    assert manifest["documentation"] == REPOSITORY_URL
    assert manifest["issue_tracker"] == f"{REPOSITORY_URL}/issues"
    assert manifest["codeowners"]
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "device"
    assert manifest["iot_class"] == "calculated"
    assert manifest["requirements"] == []


def test_hacs_json() -> None:
    """The HACS metadata has the display name."""
    hacs = json.loads((ROOT / "hacs.json").read_text("utf-8"))
    assert hacs["name"] == "Hot Water Tank Estimator"


def test_manifest_key_order() -> None:
    """The keys are in hassfest's order: domain, name, then alphabetical."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text("utf-8"))
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])
