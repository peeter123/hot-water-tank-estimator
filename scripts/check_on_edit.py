#!/usr/bin/env python3
"""Claude Code PostToolUse hook: format and check the file that was just edited.

Reads the hook payload (JSON) from stdin. For a Python file it runs the pinned ruff fix,
format and check; for a Markdown file it repairs line endings and the final newline and
checks the format; for a YAML file it runs yamllint. When a test module exists for an
edited module under custom_components/ or scripts/, it runs that module's tests too.
Findings go to stderr with exit code 2, so Claude sees them. Standard library only.
"""

import json
from pathlib import Path
import subprocess
import sys

import lint  # scripts/lint.py: pinned versions and helpers
import md_format

ROOT = Path(__file__).resolve().parent.parent


def capture(args: list[str]) -> tuple[int, str]:
    """Run a command and return its exit code and combined output."""
    try:
        result = subprocess.run(
            args, cwd=ROOT, capture_output=True, text=True, check=False
        )
    except OSError as error:
        return 2, f"{args[0]}: {error}"
    return result.returncode, (result.stdout + result.stderr).strip()


def check_python(path: Path) -> list[str]:
    """Fix, format and check one Python file, then run its tests."""
    ruff = ["uvx", f"ruff@{lint.RUFF_VERSION}"]
    capture([*ruff, "check", "--fix", str(path)])
    capture([*ruff, "format", str(path)])
    problems = []
    code, output = capture([*ruff, "check", str(path)])
    if code:
        problems.append(output)
    test = ROOT / "tests" / f"test_{path.stem}.py"
    if test.is_file() and lint.TEST_REQUIREMENTS.is_file():
        try:
            cmd = lint.pytest_command("-q", test.relative_to(ROOT).as_posix())
        except lint.ToolError as error:
            return [*problems, f"tool failure: {error}"]
        code, output = capture(cmd)
        if cmd[0] == "docker" and code in lint.DOCKER_FAILURE_CODES:
            problems.append(
                f"tool failure: docker run failed with exit code {code}\n{output[-4000:]}"
            )
        elif lint.is_remote(cmd) and code == lint.remote_test.RUNNER_FAILED:
            problems.append(
                f"tool failure: the remote test runner could not be used\n{output[-4000:]}"
            )
        elif code:
            problems.append(output[-4000:])
    return problems


def check_markdown(path: Path) -> list[str]:
    """Repair line endings and the final newline, then check the Markdown format."""
    data = path.read_bytes()
    fixed = md_format.fix_bytes(data)
    if fixed != data:
        path.write_bytes(fixed)
    name = path.relative_to(ROOT).as_posix()
    return [
        f"{name}:{line}: {message}" for line, message in md_format.check_bytes(fixed)
    ]


def check_yaml(path: Path) -> list[str]:
    """Run yamllint on one YAML file."""
    code, output = capture(
        ["uvx", f"yamllint@{lint.YAMLLINT_VERSION}", "--strict", str(path)]
    )
    return [output] if code else []


def main() -> int:
    """Check the edited file named in the hook payload."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    name = (payload.get("tool_input") or {}).get("file_path")
    if not name:
        return 0
    path = Path(name).resolve()
    if not path.is_file() or ROOT not in path.parents:
        return 0
    relative = path.relative_to(ROOT).as_posix()
    if relative.startswith(("private/", ".claude/")):
        return 0
    if path.suffix == ".py":
        problems = check_python(path)
    elif path.suffix == ".md" and not relative.startswith(lint.MARKDOWN_EXCLUDE):
        problems = check_markdown(path)
    elif path.suffix in {".yaml", ".yml"}:
        problems = check_yaml(path)
    else:
        return 0
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
