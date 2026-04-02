#!/bin/bash
set -e

echo "=== OpenClaw Container Starting ==="

# Check if config.yaml is mounted
if [ ! -f /app/configs/config.yaml ]; then
    echo "ERROR: config.yaml not found at /app/configs/config.yaml"
    echo "Please mount your config.yaml file to /app/configs/config.yaml"
    exit 1
fi

echo "Found config.yaml, mapping to OpenClaw configuration..."

# Map external config to OpenClaw config
python3 /app/config-mapper.py

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to map configuration"
    exit 1
fi

echo "Configuration mapped successfully"

# Ensure sessions directory exists
mkdir -p /root/.openclaw/agents/main/sessions

# Start OpenClaw gateway in background
echo "Starting OpenClaw gateway..."
openclaw gateway --allow-unconfigured &
GATEWAY_PID=$!

# Wait for gateway to be ready
echo "Waiting for OpenClaw gateway to be ready..."
sleep 5

# Check if gateway is running
if ! kill -0 $GATEWAY_PID 2>/dev/null; then
    echo "ERROR: OpenClaw gateway failed to start"
    exit 1
fi

echo "OpenClaw gateway started successfully (PID: $GATEWAY_PID)"

# Start API server
echo "Starting API server..."
python3 /app/api-server.py &
API_PID=$!

echo "API server started (PID: $API_PID)"

# Wait for either process to exit
wait -n

# If we get here, one of the processes exited
echo "A process has exited, shutting down..."
kill $GATEWAY_PID $API_PID 2>/dev/null || true
exit 1
