#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose-dev.yaml"
SERVICE_NAME="${SERVICE_NAME:-agent-dev}"
IMAGE_NAME="${IMAGE_NAME:-cdky-agent-dev:dev}"
USER_ID="${USER_ID:-$(id -u)}"
GROUP_ID="${GROUP_ID:-$(id -g)}"
DOCKER_USERS="${DOCKER_USERS:-}"
CONTAINER_NAME="${CONTAINER_NAME:-cdky-agent-dev}"
BASE_IMAGE="${BASE_IMAGE:-ubuntu:22.04}"

detect_docker_user() {
  # Prefer explicit DOCKER_USERS from environment.
  if [[ -n "${DOCKER_USERS}" ]]; then
    return
  fi

  # Reuse image runtime user when image already exists to avoid restart mismatch.
  if docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
    local image_user
    image_user="$(docker image inspect "${IMAGE_NAME}" --format '{{.Config.User}}' 2>/dev/null || true)"
    if [[ -n "${image_user}" ]]; then
      DOCKER_USERS="${image_user}"
      return
    fi
  fi

  # Fallback for first build.
  DOCKER_USERS="cdky"
}

detect_docker_user

export IMAGE_NAME
export SERVICE_NAME
export USER_ID
export GROUP_ID
export DOCKER_USERS
export CONTAINER_NAME

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
      mkdir -p /app/logs /app/chroma_db
      touch /app/.dev_bash_history
      for path in /app/logs /app/chroma_db /app/.dev_bash_history /app/md5.text; do
        if [ -e "$path" ]; then
          chown -R "${HOST_UID}:${HOST_GID}" "$path" || true
          chmod -R u+rwX "$path" || true
        fi
      done
    '
}

wait_for_healthy() {
  local container_id
  local status

  container_id="$(compose ps -q "${SERVICE_NAME}")"
  if [[ -z "${container_id}" ]]; then
    echo "container for ${SERVICE_NAME} is not running"
    return 1
  fi

  for _ in $(seq 1 24); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
    case "${status}" in
      healthy|running)
        echo "container status: ${status}"
        return 0
        ;;
      unhealthy|exited|dead)
        echo "container status: ${status}"
        return 1
        ;;
    esac
    sleep 5
  done

  echo "container did not become healthy in time"
  return 1
}

smoke() {
  prepare_mounts
  wait_for_healthy

  compose exec -T "${SERVICE_NAME}" python - <<'PY'
import json
import urllib.request

from agent.react_agent import ReactAgent
from agent.tools.agent_tools import get_weather
from rag.rag_service import RagSummarizeService

health = urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health", timeout=10)
assert health.status == 200, f"unexpected health status: {health.status}"
print("healthcheck: ok")

rag = RagSummarizeService()
rag_query = "\u626b\u5730\u673a\u5668\u4eba\u5982\u4f55\u7ef4\u62a4\u4fdd\u517b\uff1f"
rag_result = rag.rag_summarize(rag_query)
assert isinstance(rag_result, str) and rag_result.strip(), "rag result is empty"
print("rag: ok")
print(rag_result[:200])

weather_city = "\u676d\u5dde"
weather_result = get_weather.invoke({"city": weather_city})
if isinstance(weather_result, dict):
    weather_text = json.dumps(weather_result, ensure_ascii=False)
else:
    weather_text = str(weather_result)
assert weather_text.strip(), "weather result is empty"
print("weather: ok")
print(weather_text[:200])

agent = ReactAgent()
agent_output = []
agent_prompt = "\u8bf7\u7b80\u8981\u8bf4\u660e\u626b\u5730\u673a\u5668\u4eba\u6ee4\u7f51\u7ef4\u62a4\u5efa\u8bae"
for chunk in agent.execute_stream(agent_prompt):
    cleaned = chunk.strip()
    if cleaned:
        agent_output.append(cleaned)
    if len(agent_output) >= 4:
        break

assert agent_output, "agent output is empty"
assert any(item != agent_prompt for item in agent_output), "agent output only echoed the prompt"
print("agent: ok")
print("\\n".join(agent_output)[:200])
PY
}

enter_container() {
  prepare_mounts
  wait_for_healthy
  compose_exec_interactive bash -lc 'cd /app && exec bash -l'
}

show_user() {
  prepare_mounts
  wait_for_healthy
  compose exec -T "${SERVICE_NAME}" bash -lc 'whoami && id && printf "HOME=%s\\n" "$HOME"'
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
    wait_for_healthy
    ;;
  smoke)
    smoke
    ;;
  logs)
    compose logs --tail=200
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
    wait_for_healthy
    ;;
  *)
    echo "usage: $0 {build|prepare|up|smoke|logs|shell|enter|into|whoami|down|restart}"
    exit 1
    ;;
esac
