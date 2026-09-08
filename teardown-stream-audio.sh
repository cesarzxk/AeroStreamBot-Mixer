#!/usr/bin/env bash
# teardown-stream-audio.sh
# Removes the stream-mix sink and its loopbacks.
# Reversible: run setup-stream-audio.sh again after.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SINK_NAME="stream-mix"

# Force-unload any null-sink and loopback modules (the teardown may have missed them)
for mod in $(pactl list short modules 2>/dev/null | grep "module-null-sink" | awk '{print $1}'); do
    echo "Unloading null-sink module $mod"
    pactl unload-module "$mod" || true
done
for mod in $(pactl list short modules 2>/dev/null | grep "module-loopback" | awk '{print $1}'); do
    if pactl list module "$mod" 2>/dev/null | grep -q "sink = \"$SINK_NAME\""; then
        echo "Unloading loopback module $mod"
        pactl unload-module "$mod" || true
    fi
done

# Wait for sink to disappear
for i in $(seq 1 10); do
    if ! pactl list sinks short 2>/dev/null | grep -q "$SINK_NAME"; then
        break
    fi
    sleep 0.3
done

if pactl list sinks short 2>/dev/null | grep -q "$SINK_NAME"; then
    echo "WARNING: $SINK_NAME still present after teardown."
else
    echo "Teardown complete — $SINK_NAME removed."
fi

# Clean up saved state
if [ -f "$SCRIPT_DIR/.stream-audio-ids" ]; then
    rm -f "$SCRIPT_DIR/.stream-audio-ids"
    echo "Removed state file."
fi
