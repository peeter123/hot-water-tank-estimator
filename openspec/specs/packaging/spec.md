# packaging Specification

## Purpose

Describes how the integration is distributed, documented and checked so that other Home Assistant users can
install it through HACS and understand how to tune it.

## Requirements

### Requirement: Installable through HACS
The repository SHALL be installable as a HACS custom repository of type integration. It needs:
- a `hacs.json` with the display name;
- the integration in `custom_components/hot_water_tank_estimator/`;
- a manifest with domain, name, version, documentation and issue tracker URLs, codeowners, `config_flow` true,
  `integration_type` device (one tank device per entry), `iot_class` calculated, and no runtime requirements.

#### Scenario: Add as custom repository
- **WHEN** a user adds the repository URL in HACS as an integration and downloads it
- **THEN** after a restart, "Hot Water Tank Estimator" can be added from Settings, Devices and services, and each
  entry is listed on the Integrations page with its tank device

### Requirement: Own brand images
The integration SHALL ship its icon and logo in `custom_components/hot_water_tank_estimator/brand/` (`icon.png`,
`icon@2x.png`, `logo.png`, `logo@2x.png`, with dark variants where the plain image does not work on a dark
background), which Home Assistant 2026.3 and later serves instead of the brands repository. `hacs.json` SHALL name a
minimum Home Assistant version of at least 2026.3.

#### Scenario: Integration list
- **WHEN** a user opens Settings, Devices and services
- **THEN** the Hot Water Tank Estimator entry shows its own icon, not the placeholder

### Requirement: README explains install, setup, model and tuning
The README SHALL cover:
- what the integration estimates and what it needs;
- how to find the tank sensor's height from the tank's data sheet;
- installation through HACS and by hand;
- each config and options field;
- each entity;
- a short explanation of the model, linking to `docs/model.md`;
- how to tune the usable fraction, thermocline width and other-draws share, with the backtest;
- example dashboard YAML using stock cards;
- its known limitations.

#### Scenario: New user
- **WHEN** a user with a tank sensor, a water meter and a heat pump energy counter reads the README
- **THEN** they can install it, set it up and tell which option to change when the shower runs cold earlier than
  predicted

### Requirement: Model documentation
`docs/README.md` SHALL be the entry point to the docs. `docs/model.md` SHALL give:
- every formula with its units;
- the reason for each charge rule, sensor bound and default value;
- how draws are classified;
- the backtest script's usage.

It SHALL contain no installation-specific entity IDs.

#### Scenario: Formula lookup
- **WHEN** a reader wants to know how the remaining litres are computed
- **THEN** `docs/model.md` gives the formula, the meaning of each symbol and its unit

### Requirement: One lint and test entry point
`scripts/lint.py` SHALL be the single local check. It uses only the Python standard library and runs pinned tools:
- ruff check and format with Home Assistant core's rule set;
- a Markdown check (line length 120, LF endings, final newline);
- codespell and yamllint;
- the pytest suite.

It SHALL exit 0 when clean, 1 on findings and 2 when a tool cannot run, and `--fix` SHALL apply the ruff and
Markdown fixes first.

#### Scenario: Markdown with CRLF
- **WHEN** a Markdown file has CRLF line endings
- **THEN** `python scripts/lint.py` exits 1 naming the file, and `python scripts/lint.py --fix` repairs it

### Requirement: Quality scale
The integration SHALL keep a `quality_scale.yaml` that records each Home Assistant Integration Quality Scale rule as
done, todo or exempt (with a reason). The first release SHALL meet every Silver rule that applies, plus the Gold
rules for diagnostics, entity and icon translations, entity categories, device classes and reconfiguration (a
reconfigure step in the config flow).

#### Scenario: Release check
- **WHEN** version 0.1.0 is tagged
- **THEN** `quality_scale.yaml` has no applicable Bronze or Silver rule marked todo, the quality scale test finds
  every rule of hassfest's rule list with a valid status, and hassfest passes

### Requirement: Automated checks
GitHub Actions SHALL run hassfest, HACS validation and `python scripts/lint.py` on every push and pull request.

#### Scenario: Pull request with a lint error
- **WHEN** a pull request introduces a ruff error
- **THEN** the checks fail

### Requirement: No installation-specific data in tracked files
Tracked code, tests, fixtures, examples and docs SHALL NOT contain entity IDs, device serials, hostnames or
dashboard IDs of a real installation. Fixtures SHALL use made-up entity IDs.

#### Scenario: Fixture from real history
- **WHEN** a replay fixture is built from a real shower
- **THEN** its entity IDs are replaced with made-up ones such as `sensor.tank_temperature` before it is committed
