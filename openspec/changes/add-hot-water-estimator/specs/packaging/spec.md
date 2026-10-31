# Spec Delta

## Purpose

Describes how the integration is distributed, documented and checked so that other Home Assistant users can
install it through HACS and understand how to tune it.

## ADDED Requirements

### Requirement: Installable through HACS
The repository SHALL be installable as a HACS custom repository of type integration. It needs:
- a `hacs.json` with the display name;
- the integration in `custom_components/hot_water_tank_estimator/`;
- a manifest with domain, name, version, documentation and issue tracker URLs, codeowners, `config_flow` true,
  `integration_type` helper, `iot_class` calculated, and no runtime requirements.

#### Scenario: Add as custom repository
- **WHEN** a user adds the repository URL in HACS as an integration and downloads it
- **THEN** after a restart, "Hot Water Tank Estimator" can be added from Settings, Devices and services

### Requirement: README explains install, setup, model and tuning
The README SHALL cover:
- what the integration estimates and what it needs;
- installation through HACS and by hand;
- each config and options field;
- each entity;
- a short explanation of the model, linking to `docs/model.md`;
- how to tune the floor temperature and the other-draws share;
- example dashboard YAML using stock cards;
- its known limitations.

#### Scenario: New user
- **WHEN** a user with a tank sensor, a water meter and a heat pump energy counter reads the README
- **THEN** they can install it, set it up and tell which option to change when the shower runs cold earlier than
  predicted

### Requirement: Model documentation
`docs/model.md` SHALL give:
- every formula with its units;
- the reason for each anchor, cap and default value;
- how draws are classified;
- the backtest script's usage.

It SHALL contain no installation-specific entity IDs.

#### Scenario: Formula lookup
- **WHEN** a reader wants to know how the remaining litres are computed
- **THEN** `docs/model.md` gives the formula, the meaning of each symbol and its unit

### Requirement: Automated checks
GitHub Actions SHALL run hassfest, HACS validation, `ruff check`, `ruff format --check` and the pytest suite on
every push and pull request.

#### Scenario: Pull request with a lint error
- **WHEN** a pull request introduces a ruff error
- **THEN** the checks fail

### Requirement: No installation-specific data in tracked files
Tracked code, tests, fixtures, examples and docs SHALL NOT contain entity IDs, device serials, hostnames or
dashboard IDs of a real installation. Fixtures SHALL use made-up entity IDs.

#### Scenario: Fixture from real history
- **WHEN** a replay fixture is built from a real shower
- **THEN** its entity IDs are replaced with made-up ones such as `sensor.tank_temperature` before it is committed
