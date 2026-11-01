"""Shared fixtures for the Home Assistant tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest) -> None:
    """Let Home Assistant load the integration in this repository.

    A test with the recorder must set the recorder up before `hass`, and `enable_custom_integrations`
    needs `hass`. So such a test asks for `enable_custom_integrations` itself, after `recorder_mock`.
    """
    if "recorder_mock" not in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
