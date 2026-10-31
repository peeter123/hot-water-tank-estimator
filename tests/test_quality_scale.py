"""Tests for the quality scale file."""

from pathlib import Path

import yaml

QUALITY_SCALE = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "hot_water_tank_estimator"
    / "quality_scale.yaml"
)

# Copy of the rule names in ALL_RULES of Home Assistant core's script/hassfest/quality_scale.py
# (dev branch, copied 2026-10-31). hassfest does not validate this file for custom integrations.
HASSFEST_RULES = {
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow",
    "config-flow-test-coverage",
    "dependency-transparency",
    "docs-actions",
    "docs-conditions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "docs-triggers",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
    "devices",
    "diagnostics",
    "discovery",
    "discovery-update-info",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
    "async-dependency",
    "inject-websession",
    "strict-typing",
}
STATUSES = {"done", "todo", "exempt"}


def load_rules() -> dict:
    """Load the rules mapping from the quality scale file."""
    return yaml.safe_load(QUALITY_SCALE.read_text("utf-8"))["rules"]


def test_rules_match_hassfest() -> None:
    """The file has exactly the rules of hassfest's list."""
    assert set(load_rules()) == HASSFEST_RULES


def test_rule_statuses() -> None:
    """Each rule is done or todo, or has a status and, when exempt, a comment."""
    for name, rule in load_rules().items():
        if isinstance(rule, str):
            assert rule in {"done", "todo"}, name
            continue
        assert rule["status"] in STATUSES, name
        if rule["status"] == "exempt":
            assert str(rule.get("comment", "")).strip(), name
