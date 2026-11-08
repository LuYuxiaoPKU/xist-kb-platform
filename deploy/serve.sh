#!/usr/bin/env bash
# Start, stop and restart the XIST knowledge base API on the lab server.
#
# `systemctl --user` is not available on this host, so the process is kept alive
# by an explicit restart loop: if uvicorn dies, the loop starts it again after a
# short delay, and the loop itself holds the PID file. A plain `nohup uvicorn &`
# leaves a dead service with no record of how to bring it back, which is what the
# previous deployment did.
#
# Usage:
#   deploy/serve.sh start     # background, writes run/xist-kb.pid
#   deploy/serve.sh stop      # stops the loop and the server
#   deploy/serve.sh restart
#   deploy/serve.sh status
#
# Binding: 127.0.0.1 by default. Reach it from outside with an SSH tunnel
# (`ssh -L 8420:127.0.0.1:8420 luyx@host`), which is how the lab uses it. To bind
# externally instead, set XIST_KB_HOST=0.0.0.0 and configure
# XIST_KB_ALLOWED_NETS -- the API has no per-user accounts, only an optional
# shared key, so exposing it without a source restriction makes the whole corpus
# readable by anyone who reaches the port.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$APP_DIR/run"
PID_FILE="$RUN_DIR/xist-kb.pid"
LOG_FILE="$RUN_DIR/xist-kb.log"

PORT="${XIST_KB_PORT:-8420}"
HOST="${XIST_KB_HOST:-127.0.0.1}"
PYTHON="$APP_DIR/.venv/bin/python"

mkdir -p "$RUN_DIR"

running_pid() {
    # Prints the PID if the recorded process is alive, nothing otherwise. `kill
    # -0` succeeds for a zombie, so the process state is checked as well.
    [[ -f "$PID_FILE" ]] || return 1
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    [[ -n "$pid" ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    local state
    state="$(ps -o stat= -p "$pid" 2>/dev/null || true)"
    [[ "$state" == Z* ]] && return 1
    echo "$pid"
}

start() {
    if pid="$(running_pid)"; then
        echo "already running (pid $pid) on $HOST:$PORT"
        return 0
    fi
    echo "starting on $HOST:$PORT; log: $LOG_FILE"
    # The loop is the supervised process; uvicorn is its child. Restarting only
    # uvicorn keeps the PID file stable, so `stop` always finds the loop.
    #
    # `setsid` detaches the loop from the controlling terminal. Without it the
    # loop dies with the SSH session that started it, while its uvicorn child
    # survives as an orphan: the service answers requests but nothing supervises
    # it, and `status` reports "not running". That is exactly what the first
    # deployment of this script did.
    #
    # `$BASHPID` rather than `$$`: inside a subshell `$$` is the parent shell's
    # PID, so the file named the SSH session instead of the loop.
    setsid bash -c '
        echo $BASHPID > "$1"
        while true; do
            "$2" -m xist_kb.api.serve --host "$3" --port "$4" >>"$5" 2>&1 || true
            echo "$(date -Is) uvicorn exited, restarting in 5s" >>"$5"
            sleep 5
        done
    ' _ "$PID_FILE" "$PYTHON" "$HOST" "$PORT" "$LOG_FILE" </dev/null >>"$LOG_FILE" 2>&1 &
    sleep 3
    if pid="$(running_pid)"; then
        echo "started (pid $pid)"
    else
        echo "failed to start; see $LOG_FILE" >&2
        exit 1
    fi
}

stop() {
    if pid="$(running_pid)"; then
        # Kill the loop first so it does not restart uvicorn, then the child.
        pkill -P "$pid" 2>/dev/null || true
        kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.25
        done
        kill -9 "$pid" 2>/dev/null || true
        echo "stopped (pid $pid)"
    else
        echo "not running"
    fi
    rm -f "$PID_FILE"
    # A uvicorn that outlived the loop would keep the port bound and the DuckDB
    # file locked, which is what made an index rebuild fail with a rename error.
    pkill -f "xist_kb.api.serve --host $HOST --port $PORT" 2>/dev/null || true
}

status() {
    if pid="$(running_pid)"; then
        echo "running (pid $pid) on $HOST:$PORT"
        curl -fsS -m 5 "http://$HOST:$PORT/api/health" 2>/dev/null && echo || echo "health check failed"
    else
        echo "not running"
        exit 1
    fi
}

case "${1:-}" in
    start) start ;;
    stop) stop ;;
    restart) stop; start ;;
    status) status ;;
    *)
        echo "usage: $0 {start|stop|restart|status}" >&2
        exit 2
        ;;
esac
