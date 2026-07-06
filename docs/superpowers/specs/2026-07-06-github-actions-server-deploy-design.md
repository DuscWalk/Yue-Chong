# GitHub Actions Server Deploy Design

## Goal

Pushes to the GitHub repository `git@github.com:DuscWalk/Yue-Chong.git` should automatically sync the QQ rolebot code to the Ubuntu server and restart `qq-rolebot.service` after tests pass.

## Current State

- The local repository is initialized and has several commits, but no remote.
- The GitHub repository exists and currently only contains an initial README commit.
- The server runs the bot from `/opt/qq-rolebot`, but that directory is not a git checkout.
- Runtime files such as `/opt/qq-rolebot/.env`, `/opt/qq-rolebot/data`, model assets, voice references, and generated caches must remain server-only.
- The bot service is managed by systemd as `qq-rolebot.service`.

## Recommended Approach

Use GitHub Actions as the deployment coordinator. On push to the primary branch, the workflow will:

1. Check out the repository.
2. Run local CI checks: `ruff` and `pytest`.
3. Connect to the server through SSH.
4. Ensure `/opt/qq-rolebot` is a git checkout of the repository.
5. Preserve server-only runtime files.
6. Install or refresh the editable Python package in the existing conda environment.
7. Run server-side tests.
8. Restart `qq-rolebot.service`.
9. Print service status and recent logs for quick diagnosis.

This keeps deployment deterministic while leaving secrets and large artifacts off GitHub.

## Authentication

Use SSH key authentication for GitHub Actions to reach the server. The server will receive a dedicated deploy public key in root's `authorized_keys`. The matching private key will be stored in GitHub Actions secrets.

Required GitHub secrets:

- `DEPLOY_HOST`: server IP or hostname.
- `DEPLOY_USER`: `root`.
- `DEPLOY_SSH_KEY`: private key for deployment.
- `DEPLOY_PORT`: optional, defaults to `22` if omitted by the workflow.

The model API key, Tavily key, OneBot token, QQ account data, voice references, model weights, and generated media must not be stored in the repository. They remain in `/opt/qq-rolebot/.env` or server-only directories.

## Server Checkout Strategy

The first deployment needs to convert `/opt/qq-rolebot` from a plain directory into a git checkout. To avoid losing runtime files:

- Move the existing directory to a timestamped backup such as `/opt/qq-rolebot.pre-git-YYYYMMDDHHMMSS`.
- Clone the GitHub repository into a fresh `/opt/qq-rolebot`.
- Copy `.env` from the backup if the fresh checkout does not have one.
- Keep `data/` on the server. If it already exists in the backup, move or copy it back into the new checkout.
- Do not copy `__pycache__`, `.pytest_cache`, `.ruff_cache`, tarballs, or local temporary artifacts.

Subsequent deployments will run `git fetch` and `git reset --hard origin/<branch>` inside `/opt/qq-rolebot`.

## Branching

Use `master` as the deployment branch because the local repository currently uses `master`. The remote repository's initial README commit will be incorporated into local history before the first push so pushes do not require force.

## Safety

- The deployment script must abort on errors.
- It must verify it is operating on `/opt/qq-rolebot` before deleting or moving anything.
- It must never print secret values.
- It must run tests before restarting the service.
- It must leave server-only artifact directories outside git tracking.

## Testing

Local verification:

- `python -m ruff check .`
- `python -m pytest -q`

Server verification:

- `/opt/miniconda3/envs/qq-rolebot/bin/python -m ruff check .`
- `/opt/miniconda3/envs/qq-rolebot/bin/python -m pytest -q`
- `systemctl is-active qq-rolebot`

## User Workflow

After setup, the normal workflow is:

1. Edit code or persona files locally.
2. Commit changes.
3. Push to GitHub.
4. GitHub Actions deploys to the server.
5. Check the Actions log or `journalctl -u qq-rolebot` if the bot behaves unexpectedly.
