#!/usr/bin/env bash
set -e

# Ensure container directory permissions are valid
mkdir -p /var/lib/hermes/db \
         /var/lib/hermes/artifacts \
         /var/lib/hermes/logs \
         /var/lib/hermes/registry \
         /var/lib/hermes/blobs \
         /workspaces

echo "=== HERMES 2.x Container Runtime ==="
echo "Python: $(python3 --version)"
echo "Database path: $HERMES_DATABASE_PATH"
echo "Registry path: $HERMES_REGISTRY_FILE"
echo "Artifacts path: $HERMES_ARTIFACTS_DIR"
echo "Container mode: $HERMES_CONTAINER_MODE"
echo "Workspaces root: $HERMES_WORKSPACES_ROOT"

# Forward termination signals (SIGTERM/SIGINT) to Uvicorn for graceful shutdown
cleanup() {
    echo "Received termination signal (SIGTERM/SIGINT). Forwarding to Uvicorn (PID: $UVICORN_PID)..."
    if [ -n "$UVICORN_PID" ]; then
        kill -TERM "$UVICORN_PID" 2>/dev/null || true
        wait "$UVICORN_PID" 2>/dev/null || true
    fi
    echo "HERMES runtime container shutdown complete."
}

trap cleanup SIGTERM SIGINT

# Start Uvicorn ASGI server binding to 0.0.0.0:8765 inside the container
python3 -m uvicorn core.server.app:app \
    --host 0.0.0.0 \
    --port 8765 \
    --timeout-graceful-shutdown 15 &

UVICORN_PID=$!

# Wait for Uvicorn process to terminate and capture exit status
wait "$UVICORN_PID" 2>/dev/null || true
EXIT_STATUS=$?

echo "Uvicorn exited with status: $EXIT_STATUS"
exit "$EXIT_STATUS"
