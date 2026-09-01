#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR="$(pwd)"
RUN_DIR="${ROOT_DIR}/.run/backendai"
QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true

log() {
  if [[ "${QUIET}" != "true" ]]; then
    echo "$@"
  fi
}

stop_pid_file() {
  local name="$1"
  local pid_file="$2"
  local expected_pattern="$3"

  if [[ ! -f "${pid_file}" ]]; then
    log "==> ${name}: not running (no pid file)"
    return 0
  fi

  local pid
  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if [[ -z "${pid}" || ! "${pid}" =~ ^[0-9]+$ ]]; then
    log "==> ${name}: removing invalid pid file"
    rm -f "${pid_file}"
    return 0
  fi

  if ! kill -0 "${pid}" 2>/dev/null; then
    log "==> ${name}: process ${pid} is already gone"
    rm -f "${pid_file}"
    return 0
  fi

  local cmdline=""
  if [[ -r "/proc/${pid}/cmdline" ]]; then
    cmdline="$(tr '\0' ' ' <"/proc/${pid}/cmdline")"
  fi
  if [[ -n "${cmdline}" && ! "${cmdline}" =~ ${expected_pattern} ]]; then
    echo "WARN: ${name} pid ${pid} now belongs to another process; refusing to kill it." >&2
    echo "      command: ${cmdline}" >&2
    rm -f "${pid_file}"
    return 1
  fi

  log "==> Stopping ${name} (pid ${pid})"
  # Ask direct children to stop first (Next.js may have helper processes), then
  # stop the tracked parent. Never use broad pkill patterns that could touch the
  # separate model-server processes.
  pkill -TERM -P "${pid}" 2>/dev/null || true
  kill -TERM "${pid}" 2>/dev/null || true

  local waited=0
  while kill -0 "${pid}" 2>/dev/null && (( waited < 10 )); do
    sleep 1
    waited=$((waited + 1))
  done

  if kill -0 "${pid}" 2>/dev/null; then
    log "==> ${name}: forcing shutdown"
    pkill -KILL -P "${pid}" 2>/dev/null || true
    kill -KILL "${pid}" 2>/dev/null || true
  fi
  rm -f "${pid_file}"
}

mkdir -p "${RUN_DIR}"
status=0
stop_pid_file "frontend" "${RUN_DIR}/frontend.pid" 'next.*(dev|start)' || status=1
stop_pid_file "backend" "${RUN_DIR}/backend.pid" 'uvicorn.*app\.main:app' || status=1
exit "${status}"
