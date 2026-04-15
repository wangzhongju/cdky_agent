#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose-dev.yaml"
SERVICE_NAME="${SERVICE_NAME:-agent-web}"
IMAGE_NAME="${IMAGE_NAME:-cdky-agent-api:dev}"
WEB_IMAGE_NAME="${WEB_IMAGE_NAME:-cdky-agent-web:dev}"
USER_ID="${USER_ID:-$(id -u)}"
GROUP_ID="${GROUP_ID:-$(id -g)}"
DOCKER_USERS="${DOCKER_USERS:-}"
BASE_IMAGE="${BASE_IMAGE:-ubuntu:22.04}"

detect_docker_user() {
  if [[ -n "${DOCKER_USERS}" ]]; then
    return
  fi

  if docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
    local image_user
    image_user="$(docker image inspect "${IMAGE_NAME}" --format '{{.Config.User}}' 2>/dev/null || true)"
    if [[ -n "${image_user}" ]]; then
      DOCKER_USERS="${image_user}"
      return
    fi
  fi

  DOCKER_USERS="cdky"
}

detect_docker_user

export IMAGE_NAME
export WEB_IMAGE_NAME
export SERVICE_NAME
export USER_ID
export GROUP_ID
export DOCKER_USERS

cd "${PROJECT_ROOT}"

compose() {
  docker compose --project-directory "${PROJECT_ROOT}" -f "${COMPOSE_FILE}" "$@"
}

compose_exec_interactive() {
  if [[ -t 0 ]]; then
    if command -v winpty >/dev/null 2>&1 && { [[ "${OSTYPE:-}" == msys* ]] || [[ "${OSTYPE:-}" == cygwin* ]] || [[ -n "${MSYSTEM:-}" ]]; }; then
      winpty docker compose --project-directory "${PROJECT_ROOT}" -f "${COMPOSE_FILE}" exec "${SERVICE_NAME}" "$@"
      return
    fi
    compose exec "${SERVICE_NAME}" "$@"
    return
  fi
  compose exec -T "${SERVICE_NAME}" "$@"
}

prepare_mounts() {
  docker run --rm \
    -e HOST_UID="${USER_ID}" \
    -e HOST_GID="${GROUP_ID}" \
    -v "${PROJECT_ROOT}:/app" \
    "${BASE_IMAGE}" \
    bash -lc '
      set -e
      mkdir -p /app/logs /app/frontend
      touch /app/.dev_bash_history
      for path in /app/logs /app/.dev_bash_history /app/md5.text; do
        if [ -e "$path" ]; then
          chown -R "${HOST_UID}:${HOST_GID}" "$path" || true
          chmod -R u+rwX "$path" || true
        fi
      done
    '
}

wait_for_healthy() {
  local service="${1:-${SERVICE_NAME}}"
  local container_id
  local status

  container_id="$(compose ps -q "${service}")"
  if [[ -z "${container_id}" ]]; then
    echo "container for ${service} is not running"
    return 1
  fi

  for _ in $(seq 1 36); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
    case "${status}" in
      healthy|running)
        echo "${service} status: ${status}"
        return 0
        ;;
      unhealthy|exited|dead)
        echo "${service} status: ${status}"
        return 1
        ;;
    esac
    sleep 5
  done

  echo "${service} did not become healthy in time"
  return 1
}

smoke() {
  prepare_mounts
  wait_for_healthy agent-api
  wait_for_healthy agent-web

  compose exec -T agent-web node - <<'JS'
(async () => {
  const response = await fetch("http://127.0.0.1:3000");
  if (!response.ok) {
    throw new Error(`unexpected web status: ${response.status}`);
  }
  console.log("web health: ok");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
JS

  compose exec -T agent-api python - <<'PY'
import json
import time
import urllib.parse
import urllib.request

api_health = urllib.request.urlopen("http://127.0.0.1:8000/healthz?deep=true", timeout=10)
assert api_health.status == 200, f"unexpected api health status: {api_health.status}"
print("api health: ok")

username = f"smoke-{int(time.time())}"
user_req = urllib.request.Request(
    "http://127.0.0.1:8000/v2/users",
    data=json.dumps({"username": username, "display_name": "Smoke User"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(user_req, timeout=10) as response:
    user = json.loads(response.read().decode("utf-8"))
user_id = user["user_id"]
print("user create: ok")

session_req = urllib.request.Request(
    "http://127.0.0.1:8000/v2/sessions",
    data=json.dumps({"user_id": user_id, "metadata": {"user_id": user_id}}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(session_req, timeout=10) as response:
    session = json.loads(response.read().decode("utf-8"))
assert session["session_id"], "session_id is empty"
print("session create: ok")

query = urllib.parse.urlencode({"user_id": user_id})
with urllib.request.urlopen(f"http://127.0.0.1:8000/v2/sessions?{query}", timeout=10) as response:
    sessions = json.loads(response.read().decode("utf-8"))
assert len(sessions) >= 1, "session list is empty"
print("session list: ok")
PY
}

enter_container() {
  prepare_mounts
  wait_for_healthy "${SERVICE_NAME}"
  compose_exec_interactive sh
}

show_user() {
  prepare_mounts
  wait_for_healthy "${SERVICE_NAME}"
  compose exec -T "${SERVICE_NAME}" sh -lc 'whoami && id'
}

case "${1:-}" in
  build)
    compose build
    ;;
  prepare)
    prepare_mounts
    ;;
  up)
    prepare_mounts
    compose up -d
    wait_for_healthy agent-api
    wait_for_healthy agent-web
    ;;
  smoke)
    smoke
    ;;
  logs)
    shift || true
    compose logs --tail=200 "$@"
    ;;
  shell|enter|into)
    enter_container
    ;;
  whoami)
    show_user
    ;;
  down)
    compose down
    ;;
  restart)
    prepare_mounts
    compose down
    compose up -d
    wait_for_healthy agent-api
    wait_for_healthy agent-web
    ;;
  *)
    echo "usage: $0 {build|prepare|up|smoke|logs|shell|enter|into|whoami|down|restart}"
    exit 1
    ;;
esac
