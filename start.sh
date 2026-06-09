#!/bin/sh
# Start the Flask backend in the background, then run nginx in the foreground.
# Both share the same container.

set -e

# Tell Flask to bind to localhost only (nginx fronts it)
export FLASK_HOST=127.0.0.1
export FLASK_PORT=5001
# Disable Werkzeug reloader / debug for a single-process prod-like run
export FLASK_DEBUG=False

echo "[start.sh] launching Flask backend on 127.0.0.1:5001 ..."
cd /app/backend
uv run python run.py > /app/logs/flask.log 2>&1 &
FLASK_PID=$!

# Wait for Flask to be ready (max 60s)
echo "[start.sh] waiting for Flask to respond on /health ..."
i=0
while [ $i -lt 60 ]; do
    if curl -sSf -m 2 http://127.0.0.1:5001/health >/dev/null 2>&1; then
        echo "[start.sh] Flask is up (pid $FLASK_PID)."
        break
    fi
    i=$((i+1))
    sleep 1
done
if [ $i -ge 60 ]; then
    echo "[start.sh] WARN: Flask did not become ready in 60s; check /app/logs/flask.log"
fi

# Make sure nginx can write its pid file
mkdir -p /run
chown -R www-data:www-data /var/lib/nginx /var/log/nginx /run 2>/dev/null || true

echo "[start.sh] launching nginx on 0.0.0.0:3000 ..."
exec nginx -g "daemon off;"
