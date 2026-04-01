# Local Docker Run Guide

## 1. Preconditions
- Docker Desktop is installed and running.
- `docker` and `docker compose` commands are available.
- Project root: `D:\work\cdky_agent`.

Check:

```powershell
docker --version
docker compose version
```

## 2. Environment Variables
Create `docker/.env` from template and fill real keys:

```powershell
Copy-Item docker/.env.example docker/.env
```

`docker/.env` should include:

```env
DASHSCOPE_API_KEY=<your_real_key>
GAODE_MCP_KEY=<your_real_key>
```

## 3. Start Service (Recommended)

### Option A: Use project script (Git Bash / Linux shell)
```bash
./docker/docker.sh up
```

### Option B: Use docker compose directly (PowerShell)
```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml up -d --build
```

## 4. Verify Service

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml ps
```

Expected status: `Up ... (healthy)`

Health endpoint:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8501/_stcore/health
```

Expected response body: `ok`

Open UI:
- http://localhost:8501

## 5. Daily Commands

Script mode:

```bash
./docker/docker.sh logs
./docker/docker.sh whoami
./docker/docker.sh smoke
./docker/docker.sh restart
./docker/docker.sh down
```

Compose mode:

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml logs --tail=200
docker compose --project-directory . -f docker/docker-compose-dev.yaml restart
docker compose --project-directory . -f docker/docker-compose-dev.yaml down
```

## 6. Root Cause of `unable to find user wangzhongju`
Error:

```text
Error response from daemon: unable to find user wangzhongju: no matching entries in passwd file
```

Why it happened:
- Old `docker/docker.sh` used `DOCKER_USERS=${DOCKER_USERS:-$(id -un)}`.
- On your machine this resolved to `wangzhongju`.
- But image was built with default Dockerfile user `cdky`.
- `restart` originally did not force rebuild, so runtime user and image user could diverge.

## 7. Fix Applied in This Repo
`docker/docker.sh` has been updated:
- Runtime user now auto-detects from existing image `Config.User` first, then falls back to `cdky`.
- `compose exec` no longer forces `-u <host_username>`.
- `up` and `restart` keep fast mode (`compose up -d`) without rebuild.

So runtime user and image user stay aligned by default, and restart remains fast.

## 8. Recommended Recovery Steps (Run Once)
If you already hit the user mismatch error before this fix, run:

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml down
docker compose --project-directory . -f docker/docker-compose-dev.yaml up -d --build
```

Then verify again with section 4.

## 9. Notes
- If you intentionally want a custom container username, set `DOCKER_USERS`, `USER_ID`, and `GROUP_ID` consistently and rebuild image.
- On Windows without WSL/Git Bash, prefer direct `docker compose` commands in PowerShell.
- `./docker/docker.sh into` now auto-detects Git Bash/mintty on Windows and uses `winpty` for interactive shell compatibility.
