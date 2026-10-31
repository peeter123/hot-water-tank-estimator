#!/usr/bin/env python3
"""Run the tests on the remote test runner (docker/test-runner) over SSH.

Usage (Python standard library only; needs the `ssh` client and `git`):

    python scripts/remote_test.py pytest [ARGS...]   sync the files, run pytest (default -q)
    python scripts/remote_test.py hassfest           sync the files, run hassfest
    python scripts/remote_test.py shell COMMAND      sync the files, run COMMAND in the synced folder
    python scripts/remote_test.py --dry-run pytest   print the files and the ssh command, send nothing

The runner is configured by private/test-runner.json (or the file named by the environment
variable HWTE_TEST_RUNNER_CONFIG): {"host": ..., "port": 2222, "user": "runner", "key": ...}.
Exit status: the remote command's, or 255 (RUNNER_FAILED, as ssh itself uses) when the runner
could not be used (no or bad config, no ssh, no connection). pytest and hassfest never exit
with 255.
"""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import uuid

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "private" / "test-runner.json"
CONFIG_ENV = "HWTE_TEST_RUNNER_CONFIG"
REMOTE_PYTHON = "/opt/venv/bin/python"
REMOTE_HASSFEST = "/usr/local/bin/hassfest"
# Exit status when the runner could not be used; ssh exits 255 on connection errors too.
RUNNER_FAILED = 255
SSH_FAILED = 255
# Stands for the run's own folder in a command; run_remote replaces it.
SRC_PLACEHOLDER = "@SRC@"
STALE_MINUTES = 1440
CONNECT_TIMEOUT = 10
NEVER_SYNC = ("private/", ".git/")

TarEntry = tuple[tarfile.TarInfo, bytes]


class RunnerError(Exception):
    """The remote test runner could not be used (config, ssh, connection or sync failed)."""


def config_path() -> Path:
    """The runner config file, from the environment or the default location."""
    override = os.environ.get(CONFIG_ENV)
    return Path(override).expanduser() if override else DEFAULT_CONFIG


def load_config() -> dict | None:
    """The runner config, or None when the file is absent (the caller falls back)."""
    path = config_path()
    if not path.is_file():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RunnerError(f"{path}: {error}") from error
    if not isinstance(config, dict) or "host" not in config:
        raise RunnerError(f"{path}: needs at least a 'host' entry")
    return config


def ssh_command(config: dict, remote: str) -> list[str]:
    """The ssh command line that runs `remote` on the runner."""
    cmd = [
        "ssh",
        "-p",
        str(config.get("port", 2222)),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={CONNECT_TIMEOUT}",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
    ]
    if config.get("key"):
        cmd += ["-i", str(Path(config["key"]).expanduser()), "-o", "IdentitiesOnly=yes"]
    cmd += [f"{config.get('user', 'runner')}@{config['host']}", remote]
    return cmd


def git_output(*args: str) -> str:
    """The output of a git command in the repository root."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
        )
    except OSError as error:
        raise RunnerError(f"git: {error}") from error
    if result.returncode != 0:
        raise RunnerError(f"git {args[0]}: {result.stderr.strip()}")
    return result.stdout


def files_to_sync() -> list[str]:
    """Tracked and untracked-but-not-ignored files, never private/ or .git."""
    names = git_output("ls-files", "--cached", "--others", "--exclude-standard")
    return [
        name
        for name in names.splitlines()
        if not name.startswith(NEVER_SYNC) and (ROOT / name).is_file()
    ]


def index_modes() -> dict[str, int]:
    """The file modes git's index records (100755 means executable), by path."""
    modes = {}
    for line in git_output("ls-files", "-s").splitlines():
        info, _, name = line.partition("\t")
        modes[name] = int(info.split()[0], 8) & 0o777
    return modes


def read_files(names: list[str]) -> list[TarEntry]:
    """Read every file, text files with LF line endings, before anything is sent."""
    modes = index_modes()
    entries = []
    for name in names:
        path = ROOT / name
        try:
            data = path.read_bytes()
            mtime = int(path.stat().st_mtime)
        except OSError as error:
            raise RunnerError(f"cannot read {name}: {error}") from error
        if b"\r\n" in data:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                pass  # binary: leave untouched
            else:
                data = data.replace(b"\r\n", b"\n")
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mtime = mtime
        # The index mode when git knows the file, else executable only for a shebang.
        info.mode = modes.get(name) or (0o755 if data.startswith(b"#!") else 0o644)
        entries.append((info, data))
    return entries


def pack(entries: list[TarEntry], out: io.IOBase) -> None:
    """Write the entries as an uncompressed tar stream."""
    with tarfile.open(fileobj=out, mode="w|") as tar:
        for info, data in entries:
            tar.addfile(info, io.BytesIO(data))


def sync(config: dict, entries: list[TarEntry], folder: str) -> None:
    """Extract the entries into a new folder on the runner, after removing stale run folders."""
    remote = (
        "rm -rf /work/src ; "  # the layout before per-run folders
        f"find /work -maxdepth 1 -name 'run.*' -mmin +{STALE_MINUTES} -exec rm -rf {{}} + ; "
        f"mkdir -p {folder} && tar -xf - -C {folder}"
    )
    try:
        process = subprocess.Popen(ssh_command(config, remote), stdin=subprocess.PIPE)
    except OSError as error:
        raise RunnerError(f"ssh: {error}") from error
    assert process.stdin is not None
    # An error here means ssh died early (broken pipe; EINVAL on Windows): its exit code says why.
    with contextlib.suppress(OSError):
        pack(entries, process.stdin)
    with contextlib.suppress(OSError):
        process.stdin.close()
    code = process.wait()
    if code == SSH_FAILED:
        raise RunnerError(
            f"cannot reach the test runner at {config['host']} (ssh exit 255)"
        )
    if code != 0:
        raise RunnerError(f"syncing the files to the test runner failed (exit {code})")


def run_remote(
    argv: list[str], dry_run: bool = False, shell_command: str | None = None
) -> int:
    """Sync the files into a run folder, run the command there and return its exit code.

    argv is shlex-quoted into one command; shell_command, when given, replaces it and is passed
    to the remote shell as written (so `a; b` and pipes work). SRC_PLACEHOLDER in the command
    stands for the run folder, which is the working directory and is removed when the command
    ends, whatever its result.

    The output streams live. Raises RunnerError when the runner is not configured, ssh cannot
    run or cannot connect (ssh exit 255), or a file cannot be read: main reports that as exit
    status RUNNER_FAILED and lint as "a tool could not run".
    """
    config = load_config()
    if config is None:
        raise RunnerError(f"no test runner configured: {config_path()} does not exist")
    names = files_to_sync()
    folder = f"/work/run.{uuid.uuid4().hex[:12]}"
    if shell_command is not None:
        command = f"{{ {shell_command}\n}}"
    else:
        command = shlex.join(argv)
    command = command.replace(SRC_PLACEHOLDER, folder)
    remote = f"trap 'rm -rf {folder}' EXIT; cd {folder} && {command}"
    if dry_run:
        print(f"{len(names)} files would be sent to {folder}:")
        print("\n".join(names))
        print(shlex.join(ssh_command(config, remote)))
        return 0
    entries = read_files(names)
    print(f"$ sync {len(names)} files to the test runner", flush=True)
    try:
        sync(config, entries, folder)
    except RunnerError:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            # Best effort; the cleanup of stale folders is the backstop.
            subprocess.run(
                ssh_command(config, f"rm -rf {folder}"), check=False, timeout=30
            )
        raise
    print(f"$ {command}", flush=True)
    try:
        code = subprocess.run(ssh_command(config, remote), check=False).returncode
    except OSError as error:
        raise RunnerError(f"ssh: {error}") from error
    if code == SSH_FAILED:
        raise RunnerError(
            f"the connection to the test runner at {config['host']} failed"
        )
    return code


def main() -> int:
    """Parse the command line and run the chosen command."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the files and the ssh command only",
    )
    parser.add_argument("command", choices=["pytest", "hassfest", "shell"])
    parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="arguments for the command"
    )
    args = parser.parse_args()
    shell_command = None
    if args.command == "pytest":
        argv = [REMOTE_PYTHON, "-m", "pytest", *(args.args or ["-q"])]
    elif args.command == "hassfest":
        argv = [REMOTE_HASSFEST, SRC_PLACEHOLDER, *args.args]
    else:
        if not args.args:
            parser.error("shell needs a command")
        argv = []
        shell_command = " ".join(args.args)
    try:
        return run_remote(argv, args.dry_run, shell_command)
    except RunnerError as error:
        print(f"remote_test: {error}", file=sys.stderr)
        return RUNNER_FAILED


if __name__ == "__main__":
    sys.exit(main())
