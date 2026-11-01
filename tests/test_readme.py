"""The README documents every config and options field, every entity and every action."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text("utf-8")
STRINGS = json.loads(
    (
        ROOT / "custom_components" / "hot_water_tank_estimator" / "strings.json"
    ).read_text("utf-8")
)
TRANSLATION = json.loads(
    (
        ROOT
        / "custom_components"
        / "hot_water_tank_estimator"
        / "translations"
        / "en.json"
    ).read_text("utf-8")
)


def labels(flow: str) -> set[str]:
    """Return the field labels of a flow's steps."""
    return {
        label
        for step in STRINGS[flow]["step"].values()
        for label in step["data"].values()
    }


@pytest.mark.parametrize("flow", ["config", "options"])
def test_every_field_is_in_the_readme(flow: str) -> None:
    """Each field label of the config flow and the options flow is in the README."""
    missing = sorted(label for label in labels(flow) if label not in README)
    assert not missing


def test_every_entity_is_in_the_readme() -> None:
    """Each entity name is in the README."""
    names = {
        entity["name"]
        for domain in STRINGS["entity"].values()
        for entity in domain.values()
    }
    assert len(names) == 7 + 8 + 1 + 1
    missing = sorted(name for name in names if name not in README)
    assert not missing


def test_every_action_and_field_is_in_the_readme() -> None:
    """Each action and each of its fields is in the README."""
    for action, service in STRINGS["services"].items():
        assert f"hot_water_tank_estimator.{action}" in README
        for field in service["fields"].values():
            assert field["name"] in README


def test_the_translation_file_matches_the_strings() -> None:
    """translations/en.json is a copy of strings.json."""
    assert TRANSLATION == STRINGS


def test_no_emoji_in_the_strings() -> None:
    """The user-facing text is plain."""
    text = json.dumps(STRINGS, ensure_ascii=False)
    assert all(ord(char) < 0x2000 for char in text)
