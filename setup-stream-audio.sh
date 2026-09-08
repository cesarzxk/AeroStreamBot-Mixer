#!/usr/bin/env bash
# setup-stream-audio.sh
# Routes desktop audio + mic into a single virtual sink called "stream-mix".
# Your streaming app should capture from: stream-mix.monitor
# Volume control: use pavucontrol, or run:
#   ./set-stream-volume.sh desktop 0.5   (desktop relative volume 0.0-1.0)
#   ./set-stream-volume.sh mic 0.8        (mic relative volume 0.0-1.0)
# Tear down with: ./teardown-stream-audio.sh

set -euo pipefail

SINK_NAME="stream-mix"
DESC="Stream audio mix (desktop + mic)"

# Already running?
if pactl list sinks short 2>/dev/null | grep -q "$SINK_NAME"; then
    echo "[$SINK_NAME] already exists. Teardown first: ./teardown-stream-audio.sh"
    exit 1
fi

# 1. Create a null sink — this is the virtual output your streaming app will capture
pactl load-module module-null-sink \
    sink_name="$SINK_NAME" \
    sink_properties="device.description=$DESC"

# Wait for sink to appear
for i in $(seq 1 10); do
    if pactl list sinks short 2>/dev/null | grep -q "$SINK_NAME"; then
        break
    fi
    sleep 0.3
done

# 2. Identify sources
DESKTOP_MONITOR=$(pactl list sources short 2>/dev/null | grep "$SINK_NAME.monitor" || true)
if [ -z "$DESKTOP_MONITOR" ]; then
    echo "ERROR: stream-mix.monitor not found — sink may not have appeared."
    exit 1
fi

# Default desktop monitor: the monitor of the current default sink
DEFAULT_SINK=$(pactl info 2>/dev/null | grep "Default Sink" | awk '{print $3}')
if [ -z "$DEFAULT_SINK" ]; then
    echo "ERROR: could not find default sink."
    exit 1
fi
# The monitor source name is the sink name + ".monitor"
DESKTOP_SRC="${DEFAULT_SINK}.monitor"

# Mic — the running microphone input (not the monitor)
MIC_SRC=$(pactl list sources short 2>/dev/null | grep -E "alsa_input.*Microphone" | grep -v "\.monitor" | head -1 | awk '{print $2}')
if [ -z "$MIC_SRC" ]; then
    echo "ERROR: could not find microphone source."
    exit 1
fi

echo "Desktop source:  $DESKTOP_SRC"
echo "Microphone:      $MIC_SRC"
echo "Virtual sink:    $SINK_NAME"
echo ""

# 3. Loop desktop audio → stream-mix
DESKTOP_LOOPBACK_INDEX=$(pactl load-module module-loopback \
    source="$DESKTOP_SRC" \
    sink="$SINK_NAME" \
    source_dont_move="true" \
    sink_dont_move="true" \
    2>/dev/null || echo "")

if [ -z "$DESKTOP_LOOPBACK_INDEX" ]; then
    echo "ERROR: failed to create desktop loopback."
    exit 1
fi
DESKTOP_LOOPBACK_ID="module-loopback.$DESKTOP_LOOPBACK_INDEX"

# 4. Loop mic → stream-mix
MIC_LOOPBACK_INDEX=$(pactl load-module module-loopback \
    source="$MIC_SRC" \
    sink="$SINK_NAME" \
    source_dont_move="true" \
    sink_dont_move="true" \
    2>/dev/null || echo "")

if [ -z "$MIC_LOOPBACK_INDEX" ]; then
    echo "ERROR: failed to create mic loopback."
    pactl unload-module "$DESKTOP_LOOPBACK_INDEX" 2>/dev/null || true
    exit 1
fi
MIC_LOOPBACK_ID="module-loopback.$MIC_LOOPBACK_INDEX"

# Default volumes: desktop at 50%, mic at 80%
# Volume is controlled per-sink-input — each loopback creates one on stream-mix.
# We set the initial volume by adjusting the source the loopback reads from,
# but only for the looped signal — we use a separate mechanism.
# For now, leave at full; use set-stream-volume.sh to control.
# (Those scripts find the sink inputs on stream-mix and adjust them.)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IDS_FILE="$SCRIPT_DIR/.stream-audio-ids"

# Save module IDs for the volume script
echo "$DESKTOP_LOOPBACK_INDEX $MIC_LOOPBACK_INDEX" > "$IDS_FILE"
echo "Saved module IDs to $IDS_FILE"
echo ""
echo "=== SETUP COMPLETE ==="
echo "Your streaming app should capture audio from:  $SINK_NAME.monitor"
echo ""
echo "Adjust volumes (each loopback creates a sink-input on stream-mix):"
echo "  ./set-stream-volume.sh desktop 0.5"
echo "  ./set-stream-volume.sh mic 0.8"
echo ""
echo "Tear down when done:"
echo "  ./teardown-stream-audio.sh"
