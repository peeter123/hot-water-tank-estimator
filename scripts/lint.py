#!/usr/bin/env python3
"""Lint and test the repository with pinned tools.

Usage (from anywhere, no venv, Python standard library only):

    python scripts/lint.py          check: ruff, Markdown format, codespell, yamllint, pytest
    python scripts/lint.py --fix    apply the ruff and Markdown fixes first, then check

Every tool runs through `uvx` or `uv run` at an exact version, never from PATH. The ruff
rules are Home Assistant core's (pyproject.toml). Exit status: 0 clean, 1 findings, 2 a
tool could not be run. See docs/development.md.
"""

import argparse
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


class ToolError(Exception):
    """A tool could not be fetched or run."""


def run(args: list[str]) -> int:
    """Run a command in the repository root and return its exit code."""
    print(f"$ {' '.join(args)}", flush=True)
    try:
        return subprocess.run(args, cwd=ROOT, check=False).returncode
    except OSError as error:
        raise ToolError(f"{args[0]}: {error}") from error


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
            code = run(
                [
                    "uv",
                    "run",
                    "--no-project",
                    "--with-requirements",
                    str(TEST_REQUIREMENTS),
                    "pytest",
                    "-q",
                ]
            )
            status |= code not in (0, 5)  # 5: no tests collected yet
    except ToolError as error:
        print(error, file=sys.stderr)
        return 2
    print("lint: clean" if status == 0 else "lint: findings", flush=True)
    return 1 if status else 0


if __name__ == "__main__":
    sys.exit(main())
