#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose-dev.yaml"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"

IMAGE_NAME="${IMAGE_NAME:-cdky-agent-dev:dev}"
DOCKER_USERS="${DOCKER_USERS:-${USER:-cdky}}"
USER_ID="${USER_ID:-$(id -u)}"
GROUP_ID="${GROUP_ID:-$(id -g)}"

API_SERVICE="${API_SERVICE:-agent-api}"
DEV_SERVICE="${DEV_SERVICE:-agent-dev}"
DEFAULT_SHELL_SERVICE="${SERVICE_NAME:-${DEV_SERVICE}}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-120}"
LOG_TAIL="${LOG_TAIL:-200}"

export IMAGE_NAME
export DOCKER_USERS
export USER_ID
export GROUP_ID

# Prevent a single CONTAINER_NAME from forcing both services to the same name.
unset CONTAINER_NAME || true

log() {
  printf '[docker.sh] %s\n' "$*"
}

die() {
  printf '[docker.sh] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: ./docker/docker.sh <command> [args...]

Commands:
  init-env                Create docker/.env from docker/.env.example if missing
  config                  Show resolved docker compose config
  prepare                 Create local runtime files/directories (logs/chroma/history)
  build [service...]      Build all services or selected service(s)
  up                      Start services in background and wait until ready
  up-build                Build and start services, then wait until ready
  stop [service...]       Stop all or selected service(s)
  restart [service...]    Restart all or selected service(s)
  down                    Stop and remove containers/networks
  clean                   Down + remove orphans + volumes
  ps                      Show compose service status
  logs [service...]       Show logs (tail controlled by LOG_TAIL)
  shell [service]         Open interactive shell (default: agent-dev)
  exec <service> <cmd>    Execute command in a running service container
  whoami [service]        Print whoami/id/HOME in container (default: agent-dev)
  smoke                   Run API smoke checks in agent-api container
  test                    Run contract + functional pytest in agent-api container
  help                    Show this help

Environment variables:
  ENV_FILE        Compose env file path (default: docker/.env)
  IMAGE_NAME      Docker image name (default: cdky-agent-dev:dev)
  DOCKER_USERS    Runtime user in container (default: current user)
  USER_ID/GROUP_ID Build args for Dockerfile (default: current uid/gid)
  API_SERVICE     API service name (default: agent-api)
  DEV_SERVICE     UI service name (default: agent-dev)
  SERVICE_NAME    Default service for `shell`/`whoami` (default: agent-dev)
  WAIT_TIMEOUT    Seconds to wait for service readiness (default: 120)
  LOG_TAIL        Lines for logs command (default: 200)
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

ensure_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    return
  fi
  die "env file not found: ${ENV_FILE}. Run: ./docker/docker.sh init-env"
}

ensure_compose_file() {
  [[ -f "${COMPOSE_FILE}" ]] || die "compose file not found: ${COMPOSE_FILE}"
}

compose() {
  (
    cd "${PROJECT_ROOT}"
    docker compose \
      --env-file "${ENV_FILE}" \
      -f "${COMPOSE_FILE}" \
      "$@"
  )
}

prepare_workspace() {
  mkdir -p "${PROJECT_ROOT}/logs" "${PROJECT_ROOT}/chroma_db"
  touch "${PROJECT_ROOT}/.dev_bash_history"
  touch "${PROJECT_ROOT}/md5.text"
}

container_status() {
  local service="$1"
  local cid
  cid="$(compose ps -q "${service}" 2>/dev/null || true)"
  if [[ -z "${cid}" ]]; then
    echo "missing"
    return
  fi

  docker inspect \
    --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    "${cid}" 2>/dev/null || echo "unknown"
}

wait_for_service() {
  local service="$1"
  local timeout="$2"
  local start now status

  start="$(date +%s)"
  while true; do
    status="$(container_status "${service}")"
    case "${status}" in
      healthy|running)
        log "${service} is ${status}"
        return 0
        ;;
      unhealthy|exited|dead)
        compose ps "${service}" || true
        die "${service} is ${status}"
        ;;
    esac

    now="$(date +%s)"
    if (( now - start >= timeout )); then
      compose ps "${service}" || true
      die "timeout waiting for ${service} to be ready"
    fi

    sleep 2
  done
}

wait_ready() {
  wait_for_service "${API_SERVICE}" "${WAIT_TIMEOUT}"
  wait_for_service "${DEV_SERVICE}" "${WAIT_TIMEOUT}"
  wait_for_service "postgres" "${WAIT_TIMEOUT}"
  wait_for_service "redis" "${WAIT_TIMEOUT}"
}

compose_exec_interactive() {
  local service="$1"
  shift

  if [[ -t 0 ]]; then
    if command -v winpty >/dev/null 2>&1 && { [[ "${OSTYPE:-}" == msys* ]] || [[ "${OSTYPE:-}" == cygwin* ]] || [[ -n "${MSYSTEM:-}" ]]; }; then
      (
        cd "${PROJECT_ROOT}"
        winpty docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec "${service}" "$@"
      )
      return
    fi
    compose exec "${service}" "$@"
    return
  fi

  compose exec -T "${service}" "$@"
}

run_smoke() {
  wait_for_service "${API_SERVICE}" "${WAIT_TIMEOUT}"

  compose exec -T "${API_SERVICE}" python - <<'PY'
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": "docker-smoke",
    "x-trace-id": "docker-smoke-trace",
}

def request(method: str, path: str, payload=None):
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, headers=HEADERS, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8")

code, body = request("GET", "/healthz?deep=true")
assert code == 200, f"healthz failed: {code} {body}"
print("healthz: ok")

code, body = request("GET", "/v1/capabilities")
caps = json.loads(body)
assert code == 200 and isinstance(caps, list) and len(caps) > 0, "capabilities empty"
print(f"capabilities: ok ({len(caps)})")

code, body = request("GET", "/metrics")
assert code == 200 and "enterprise_api_requests_total" in body, "metrics missing"
print("metrics: ok")

code, body = request(
    "POST",
    "/v1/tasks",
    {"goal": "给我生成我的使用报告", "constraints": {}, "context_ref": {"session_id": "docker-smoke"}, "input": {}},
)
task = json.loads(body)
task_id = task["task_id"]

final = None
for _ in range(30):
    time.sleep(1)
    code, body = request("GET", f"/v1/tasks/{task_id}")
    data = json.loads(body)
    final = data.get("status")
    if final in {"COMPLETED", "FAILED"}:
        break

assert final == "COMPLETED", f"task lifecycle failed: {final}"
print("a2a task: ok")
PY
}

run_tests() {
  wait_for_service "${API_SERVICE}" "${WAIT_TIMEOUT}"
  compose exec -T "${API_SERVICE}" bash -lc 'cd /app && PYTHONPATH=/app pytest -q tests/test_api_contracts.py tests/test_functional_api.py'
}

init_env() {
  local example_file="${SCRIPT_DIR}/.env.example"
  if [[ -f "${ENV_FILE}" ]]; then
    log "env file already exists: ${ENV_FILE}"
    return
  fi
  [[ -f "${example_file}" ]] || die "missing example env file: ${example_file}"
  cp "${example_file}" "${ENV_FILE}"
  log "created env file: ${ENV_FILE}"
}

require_command docker
ensure_compose_file

cmd="${1:-help}"
shift || true

case "${cmd}" in
  help|-h|--help)
    usage
    ;;
  init-env)
    init_env
    ;;
  config)
    ensure_env_file
    compose config
    ;;
  prepare)
    prepare_workspace
    log "workspace prepared"
    ;;
  build)
    ensure_env_file
    prepare_workspace
    if [[ $# -gt 0 ]]; then
      compose build "$@"
    else
      compose build
    fi
    ;;
  up)
    ensure_env_file
    prepare_workspace
    compose up -d
    wait_ready
    ;;
  up-build|rebuild)
    ensure_env_file
    prepare_workspace
    compose up -d --build
    wait_ready
    ;;
  stop)
    ensure_env_file
    if [[ $# -gt 0 ]]; then
      compose stop "$@"
    else
      compose stop
    fi
    ;;
  restart)
    ensure_env_file
    prepare_workspace
    if [[ $# -gt 0 ]]; then
      compose restart "$@"
      for svc in "$@"; do
        wait_for_service "${svc}" "${WAIT_TIMEOUT}"
      done
    else
      compose restart
      wait_ready
    fi
    ;;
  down)
    ensure_env_file
    compose down
    ;;
  clean)
    ensure_env_file
    compose down --remove-orphans --volumes
    ;;
  ps|status)
    ensure_env_file
    compose ps
    ;;
  logs)
    ensure_env_file
    if [[ $# -gt 0 ]]; then
      compose logs --tail="${LOG_TAIL}" "$@"
    else
      compose logs --tail="${LOG_TAIL}"
    fi
    ;;
  shell|enter|into)
    ensure_env_file
    service="${1:-${DEFAULT_SHELL_SERVICE}}"
    wait_for_service "${service}" "${WAIT_TIMEOUT}"
    compose_exec_interactive "${service}" bash -lc 'cd /app && exec bash -l'
    ;;
  exec)
    ensure_env_file
    [[ $# -ge 2 ]] || die "usage: $0 exec <service> <command...>"
    service="$1"
    shift
    wait_for_service "${service}" "${WAIT_TIMEOUT}"
    compose_exec_interactive "${service}" "$@"
    ;;
  whoami)
    ensure_env_file
    service="${1:-${DEFAULT_SHELL_SERVICE}}"
    wait_for_service "${service}" "${WAIT_TIMEOUT}"
    compose exec -T "${service}" bash -lc 'whoami && id && printf "HOME=%s\n" "$HOME"'
    ;;
  smoke)
    ensure_env_file
    run_smoke
    ;;
  test)
    ensure_env_file
    run_tests
    ;;
  *)
    usage
    die "unknown command: ${cmd}"
    ;;
esac
