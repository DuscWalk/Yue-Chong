# GitHub Actions Server Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure the repository so pushes to GitHub run CI and deploy the QQ rolebot to `/opt/qq-rolebot` on the server.

**Architecture:** GitHub Actions performs local CI, then connects to the server with a dedicated SSH key and runs a checked-in deployment script. The script converts `/opt/qq-rolebot` into a git checkout on first run, preserves `.env` and `data/`, runs server-side checks, and restarts `qq-rolebot.service`.

**Tech Stack:** GitHub Actions, OpenSSH, bash, git, Python 3.11, ruff, pytest, systemd, conda environment `/opt/miniconda3/envs/qq-rolebot`.

---

### Task 1: Add Deployment Script

**Files:**
- Create: `scripts/deploy_server.sh`

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${1:?repo url is required}"
BRANCH="${2:?branch is required}"
TARGET_SHA="${3:?target sha is required}"

APP_DIR="/opt/qq-rolebot"
PYTHON="/opt/miniconda3/envs/qq-rolebot/bin/python"
SERVICE="qq-rolebot.service"

timestamp() {
  date +%Y%m%d%H%M%S
}

require_safe_app_dir() {
  if [[ "$APP_DIR" != "/opt/qq-rolebot" ]]; then
    echo "Refusing to deploy to unexpected APP_DIR=$APP_DIR" >&2
    exit 1
  fi
}

restore_runtime_files() {
  local backup_dir="$1"

  if [[ -f "$backup_dir/.env" && ! -f "$APP_DIR/.env" ]]; then
    cp "$backup_dir/.env" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env" || true
  fi

  if [[ -d "$backup_dir/data" && ! -d "$APP_DIR/data" ]]; then
    mv "$backup_dir/data" "$APP_DIR/data"
  fi

  mkdir -p "$APP_DIR/data"
}

checkout_code() {
  require_safe_app_dir

  if [[ -d "$APP_DIR/.git" ]]; then
    cd "$APP_DIR"
    git remote set-url origin "$REPO_URL"
    git fetch --prune origin "$BRANCH"
    git checkout -B "$BRANCH" "origin/$BRANCH"
    git reset --hard "$TARGET_SHA"
    git clean -fd -e .env -e data/ -e voice_refs/ -e voice_cache/ -e models/
    return
  fi

  local backup_dir="/opt/qq-rolebot.pre-git-$(timestamp)"
  if [[ -e "$APP_DIR" ]]; then
    mv "$APP_DIR" "$backup_dir"
  fi

  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
  git fetch origin "$TARGET_SHA"
  git reset --hard "$TARGET_SHA"

  if [[ -d "$backup_dir" ]]; then
    restore_runtime_files "$backup_dir"
  else
    mkdir -p "$APP_DIR/data"
  fi
}

install_and_test() {
  cd "$APP_DIR"
  "$PYTHON" -m pip install -e ".[dev]"
  "$PYTHON" -m ruff check .
  "$PYTHON" -m pytest -q
}

restart_service() {
  systemctl restart "$SERVICE"
  systemctl is-active "$SERVICE"
  journalctl -u "$SERVICE" -n 40 --no-pager
}

main() {
  checkout_code
  install_and_test
  restart_service
}

main "$@"
```

- [ ] **Step 2: Make it executable**

Run: `git update-index --chmod=+x scripts/deploy_server.sh`

- [ ] **Step 3: Validate bash syntax**

Run: `bash -n scripts/deploy_server.sh` on a shell with bash available, or defer syntax validation to GitHub Actions if local bash is unavailable.

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy_server.sh
git commit -m "chore: add server deployment script"
```

### Task 2: Add GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: CI and Deploy

on:
  push:
    branches:
      - master
  workflow_dispatch:

concurrency:
  group: qq-rolebot-production
  cancel-in-progress: false

jobs:
  test-and-deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 20

    env:
      DEPLOY_PORT: ${{ secrets.DEPLOY_PORT || '22' }}
      REPO_URL: https://github.com/DuscWalk/Yue-Chong.git
      DEPLOY_BRANCH: master

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install -U pip
          python -m pip install -e ".[dev]"

      - name: Run lint
        run: python -m ruff check .

      - name: Run tests
        run: python -m pytest -q

      - name: Configure SSH
        run: |
          mkdir -p ~/.ssh
          printf '%s\n' "${{ secrets.DEPLOY_SSH_KEY }}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          ssh-keyscan -p "$DEPLOY_PORT" -H "${{ secrets.DEPLOY_HOST }}" >> ~/.ssh/known_hosts

      - name: Upload deploy script
        run: |
          scp -P "$DEPLOY_PORT" -i ~/.ssh/deploy_key \
            scripts/deploy_server.sh \
            "${{ secrets.DEPLOY_USER }}@${{ secrets.DEPLOY_HOST }}:/tmp/qq-rolebot-deploy.sh"

      - name: Deploy on server
        run: |
          ssh -p "$DEPLOY_PORT" -i ~/.ssh/deploy_key \
            "${{ secrets.DEPLOY_USER }}@${{ secrets.DEPLOY_HOST }}" \
            "bash /tmp/qq-rolebot-deploy.sh '$REPO_URL' '$DEPLOY_BRANCH' '${{ github.sha }}'"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: deploy rolebot from github actions"
```

### Task 3: Document GitHub Secrets and First Push

**Files:**
- Modify: `docs/deployment.md`
- Modify: `README.md`

- [ ] **Step 1: Add deployment documentation**

Add a section explaining:

```markdown
## GitHub Actions deployment

Pushes to `master` run CI and deploy to `/opt/qq-rolebot`.

Required GitHub repository secrets:

- `DEPLOY_HOST`: server host.
- `DEPLOY_USER`: `root`.
- `DEPLOY_PORT`: `22`.
- `DEPLOY_SSH_KEY`: private key whose public half is listed in `/root/.ssh/authorized_keys`.

The deployment keeps `.env`, `data/`, model files, voice references, and generated audio on the server.
```

- [ ] **Step 2: Commit**

```bash
git add docs/deployment.md README.md
git commit -m "docs: describe github actions deployment"
```

### Task 4: Prepare SSH Key and Server Access

**Files:**
- No tracked files.

- [ ] **Step 1: Generate a dedicated key outside the repository**

Run:

```powershell
ssh-keygen -t ed25519 -C "github-actions-yue-chong" -f "$env:USERPROFILE\.ssh\yue_chong_github_actions" -N '""'
```

- [ ] **Step 2: Add the public key to the server**

Run a paramiko or ssh command that appends `$env:USERPROFILE\.ssh\yue_chong_github_actions.pub` to `/root/.ssh/authorized_keys` with `700` directory permissions and `600` file permissions.

- [ ] **Step 3: Verify key login**

Run:

```powershell
ssh -i "$env:USERPROFILE\.ssh\yue_chong_github_actions" root@120.26.110.68 "echo ok"
```

Expected: `ok`.

### Task 5: Link Local Repository to GitHub

**Files:**
- Git metadata only.

- [ ] **Step 1: Add origin**

Run:

```bash
git remote add origin git@github.com:DuscWalk/Yue-Chong.git
```

If `origin` already exists, run:

```bash
git remote set-url origin git@github.com:DuscWalk/Yue-Chong.git
```

- [ ] **Step 2: Merge remote initial README without losing local files**

Run:

```bash
git fetch https://github.com/DuscWalk/Yue-Chong.git master:refs/remotes/github/master
git merge --allow-unrelated-histories -X ours --no-edit github/master
```

- [ ] **Step 3: Verify status**

Run: `git status --short`

Expected: only intentional uncommitted persona edits may remain.

### Task 6: User Adds GitHub Secrets and Pushes

**Files:**
- No tracked files.

- [ ] **Step 1: Add GitHub secrets**

In GitHub repository settings, add:

```text
DEPLOY_HOST=120.26.110.68
DEPLOY_USER=root
DEPLOY_PORT=22
DEPLOY_SSH_KEY=<contents of ~/.ssh/yue_chong_github_actions private key>
```

- [ ] **Step 2: Push**

Run:

```bash
git push -u origin master
```

Expected: GitHub accepts the push and starts the workflow.

### Task 7: Verify Deployment

**Files:**
- No tracked files.

- [ ] **Step 1: Watch GitHub Actions**

Confirm the workflow passes local CI, SSH upload, server tests, and service restart.

- [ ] **Step 2: Verify server state**

Run:

```bash
cd /opt/qq-rolebot
git rev-parse --short HEAD
systemctl is-active qq-rolebot
journalctl -u qq-rolebot -n 80 --no-pager
```

Expected: commit matches the pushed commit, service is active, logs show bot startup and OneBot adapter loading.
