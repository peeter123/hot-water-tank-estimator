# Remote test runner

Home Assistant's test plugin cannot load on native Windows. This folder builds a long-running Linux container that
accepts the repository files over SSH and runs pytest and hassfest there. `scripts/remote_test.py` is the client.

The image holds a venv at `/opt/venv` with the pinned test requirements, and Home Assistant core at the matching tag
in `/opt/ha-core` with a separate venv, `/opt/hassfest-venv`, for the `hassfest` command. `sshd` listens on port 2222
and accepts key login only, for the non-root user `runner`. The host key is kept in a volume, so a rebuild does not
change it.

## Deploy

On any Docker host, with the repository root as the build context. Only `requirements_test.txt`, `.dockerignore` and
`docker/` are needed there (or a clean clone); never copy `private/`:

1. Put one or more SSH public keys in `AUTHORIZED_KEYS`, one per line.
2. Run `docker compose up -d --build` in this folder.

On a NAS with a compose UI, upload those files (or a clean clone), create the project from
`docker/test-runner/compose.yaml` and set `AUTHORIZED_KEYS` as a project environment variable.

After a change to `requirements_test.txt`, rebuild with the same command.

## Use from the development PC

1. Create a key pair, for example `ssh-keygen -t ed25519 -f ~/.ssh/hwte_test_runner_ed25519`, and give the public key
   to the container as `AUTHORIZED_KEYS`.
2. Create the git-ignored file `private/test-runner.json`:

   ```json
   {"host": "docker-host.example", "port": 2222, "user": "runner", "key": "~/.ssh/hwte_test_runner_ed25519"}
   ```

   Set `HWTE_TEST_RUNNER_CONFIG` to use another path.

3. Run `python scripts/remote_test.py pytest`, `python scripts/remote_test.py hassfest`, or add `--dry-run` to see
   what would be sent.

The exit code is the remote command's. Exit code 2 means the runner could not be reached or `ssh` could not run.
