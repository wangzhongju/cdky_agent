# Local Docker Run Guide (Enterprise Edition)

## 1. Preconditions

- Docker Desktop is installed and running.
- `docker` and `docker compose` are available.
- Project root: `D:\work\cdky_agent`.

## 2. Prepare Environment

```powershell
Copy-Item docker/.env.example docker/.env
```

Required keys in `docker/.env`:

```env
DASHSCOPE_API_KEY=your_dashscope_api_key
GAODE_MCP_KEY=your_gaode_key
DATABASE_URL=postgresql+psycopg://agent:agent@postgres:5432/agent
REDIS_URL=redis://redis:6379/0
```

Optional OTLP:

```env
OTLP_ENDPOINT=http://otel-collector:4317
```

## 3. Start Services

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml up -d --build
```

This brings up:

- `agent-api` (FastAPI, port 8000)
- `agent-dev` (Streamlit UI, port 8501)
- `postgres`
- `redis`

## 4. Verify

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml ps
Invoke-WebRequest -UseBasicParsing "http://localhost:8000/healthz?deep=true"
Invoke-WebRequest -UseBasicParsing "http://localhost:8000/metrics"
```

UI:

- http://localhost:8501

## 5. Common Ops

```powershell
docker compose --project-directory . -f docker/docker-compose-dev.yaml logs --tail=200
docker compose --project-directory . -f docker/docker-compose-dev.yaml restart
docker compose --project-directory . -f docker/docker-compose-dev.yaml down
```

## 6. Run Full Tests (Inside Container)

```powershell
docker exec -w /app -e PYTHONPATH=/app cdky-agent-api pytest -q tests/test_api_contracts.py tests/test_functional_api.py
```

## 7. Shell Script Shortcut

If using bash shell, you can still use:

```bash
./docker/docker.sh up
./docker/docker.sh logs
./docker/docker.sh down
```

Script uses the same compose file and services.
