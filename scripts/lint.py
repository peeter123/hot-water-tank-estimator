#!/usr/bin/env python3
"""Lint and test the repository with pinned tools.

Usage (from anywhere, no venv, Python standard library only):

    python scripts/lint.py          check: ruff, Markdown format, codespell, yamllint, pytest
    python scripts/lint.py --fix    apply the ruff and Markdown fixes first, then check

Every tool runs through `uvx` or `uv run` at an exact version, never from PATH (Docker, where used, comes from PATH and runs a pinned image). The ruff
rules are Home Assistant core's (pyproject.toml). Exit status: 0 clean, 1 findings, 2 a
tool could not be run. See docs/development.md.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

import md_format  # scripts/md_format.py (scripts/ is sys.path[0] for this script)

# Home Assistant core pins (requirements_test_pre_commit.txt, dev branch, 2026-10-31).
RUFF_VERSION = "0.17.3"
CODESPELL_VERSION = "2.4.3"
YAMLLINT_VERSION = "1.38.0"

ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_EXCLUDE = (".claude/", "openspec/changes/archive/")
TEST_REQUIREMENTS = ROOT / "requirements_test.txt"
# Linux image with uv and Python 3.14, used to run the tests on Windows through Docker.
DOCKER_IMAGE = "ghcr.io/astral-sh/uv:0.13.1-python3.14-trixie-slim"
DOCKER_CACHE_VOLUME = "hwte-uv-cache"
# docker run exit codes meaning docker itself failed, not the tests.
DOCKER_FAILURE_CODES = (125, 126, 127)
# pytest11 entry point of pytest-homeassistant-custom-component; it imports homeassistant.
HA_PLUGIN = "homeassistant"


class ToolError(Exception):
    """A tool could not be fetched or run."""


def run(args: list[str]) -> int:
    """Run a command in the repository root and return its exit code."""
    print(f"$ {' '.join(args)}", flush=True)
    try:
        return subprocess.run(args, cwd=ROOT, check=False).returncode
    except OSError as error:
        raise ToolError(f"{args[0]}: {error}") from error


def docker_available() -> bool:
    """Whether a Docker engine answers, checked quickly."""
    try:
        return (
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=15,
                check=False,
            ).returncode
            == 0
        )
    except OSError:
        return False
    except subprocess.TimeoutExpired:
        return False


def pytest_command(*pytest_args: str) -> list[str]:
    """The command that runs pytest with the given arguments, chosen by platform.

    Home Assistant does not run on native Windows. There the tests run in a Linux
    container when a Docker engine is reachable. Without one, they run natively with the
    Home Assistant plugin disabled, so pure-Python tests pass and tests that need Home
    Assistant fail (a loud warning says so).
    """
    uv_run = [
        "uv",
        "run",
        "--no-project",
        "--with-requirements",
        "requirements_test.txt",
        "pytest",
    ]
    if os.name != "nt":
        return [*uv_run, *pytest_args]
    if docker_available():
        return [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ROOT}:/src",
            "-v",
            f"{DOCKER_CACHE_VOLUME}:/root/.cache/uv",
            "-e",
            "UV_LINK_MODE=copy",
            "-w",
            "/src",
            DOCKER_IMAGE,
            *uv_run,
            "-p",
            "no:cacheprovider",
            *pytest_args,
        ]
    print(
        "WARNING: no Docker engine and native Windows: running pytest with the Home "
        "Assistant plugin disabled. Tests that need Home Assistant cannot run here and "
        "will fail. Start Docker Desktop (it needs WSL) to run the full suite in a Linux container.",
        file=sys.stderr,
        flush=True,
    )
    return [*uv_run, "-p", f"no:{HA_PLUGIN}", *pytest_args]


def run_pytest() -> int:
    """Run the test suite and return pytest's exit code; a failing docker is a ToolError."""
    cmd = pytest_command("-q")
    code = run(cmd)
    if cmd[0] == "docker" and code in DOCKER_FAILURE_CODES:
        raise ToolError(f"docker run failed with exit code {code}")
    return code


def tracked(*patterns: str) -> list[str]:
    """Tracked and untracked-but-not-ignored files matching the patterns."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", *patterns],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ToolError(f"git ls-files: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if (ROOT / line).is_file()]


def markdown_files() -> list[str]:
    """The Markdown files the format check covers."""
    return [name for name in tracked("*.md") if not name.startswith(MARKDOWN_EXCLUDE)]


def check_markdown(fix: bool) -> int:
    """Check (and with fix, repair line endings and final newline of) the Markdown files."""
    print("$ markdown format check", flush=True)
    failed = 0
    for name in markdown_files():
        path = ROOT / name
        data = path.read_bytes()
        if fix:
            fixed = md_format.fix_bytes(data)
            if fixed != data:
                path.write_bytes(fixed)
                data = fixed
        for line, message in md_format.check_bytes(data):
            print(f"{name}:{line}: {message}")
            failed = 1
    return failed


def main() -> int:
    """Run every check and return the combined exit status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fix", action="store_true", help="apply ruff and Markdown fixes first"
    )
    args = parser.parse_args()

    if shutil.which("uv") is None or shutil.which("uvx") is None:
        print("uv is not installed: https://docs.astral.sh/uv/", file=sys.stderr)
        return 2

    ruff = ["uvx", f"ruff@{RUFF_VERSION}"]
    status = 0
    try:
        if args.fix:
            run([*ruff, "check", "--fix", "."])
            run([*ruff, "format", "."])
        status |= run([*ruff, "check", "."]) != 0
        status |= run([*ruff, "format", "--check", "."]) != 0
        status |= check_markdown(args.fix)
        status |= run(["uvx", f"codespell@{CODESPELL_VERSION}"]) != 0
        yaml_files = tracked("*.yaml", "*.yml", ".yamllint")
        if yaml_files:
            status |= (
                run(["uvx", f"yamllint@{YAMLLINT_VERSION}", "--strict", *yaml_files])
                != 0
            )
        if TEST_REQUIREMENTS.is_file() and (ROOT / "tests").is_dir():
            code = run_pytest()
            status |= code not in (0, 5)  # 5: no tests collected yet
    except ToolError as error:
        print(error, file=sys.stderr)
        return 2
    print("lint: clean" if status == 0 else "lint: findings", flush=True)
    return 1 if status else 0


if __name__ == "__main__":
    sys.exit(main())
