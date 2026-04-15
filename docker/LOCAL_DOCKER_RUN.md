# Local Docker Run Guide

## 1. Preconditions

- Docker Desktop is installed and running.
- `docker` and `docker compose` are available.
- Project root: `D:\work\cdky_agent`.

## 2. Prepare Environment

```powershell
Copy-Item docker/.env.example .env
```

Required keys in `.env`:

```env
DASHSCOPE_API_KEY=your_dashscope_api_key
GAODE_MCP_KEY=your_gaode_key
DATABASE_URL=postgresql+psycopg://agent:agent@postgres:5432/agent
REDIS_URL=redis://redis:6379/0
```

Optional frontend origin override:

```env
NEXT_PUBLIC_AGENT_API_BASE_URL=http://127.0.0.1:8000
```

## 3. Start Services

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml up -d --build
```

This brings up:

- `agent-web` (Next.js Web UI, port 3000)
- `agent-api` (FastAPI, port 8000)
- `postgres`
- `redis`

## 4. Verify

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml ps
Invoke-WebRequest -UseBasicParsing "http://localhost:3000"
Invoke-WebRequest -UseBasicParsing "http://localhost:8000/healthz?deep=true"
Invoke-WebRequest -UseBasicParsing "http://localhost:8000/metrics"
```

UI:

- http://localhost:3000

## 5. Common Ops

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml logs --tail=200
docker compose --project-directory . -f docker/docker-compose-dev.yaml restart
docker compose --project-directory . -f docker/docker-compose-dev.yaml down
```

## 6. Run Tests

Backend tests:

```powershell
docker exec cdky-agent-api sh -lc 'cd /app && PYTHONPATH=/app pytest -q'
```

Frontend tests and build:

```powershell
docker run --rm -v D:\work\cdky_agent\frontend:/app -w /app node:20-alpine sh -lc "npm ci && npm test && npm run build"
```

## 7. Shell Script Shortcut

If using a bash shell:

```bash
./docker/docker.sh up
./docker/docker.sh smoke
./docker/docker.sh logs
./docker/docker.sh down
```

The script uses the same compose file and validates both Web and API services.
