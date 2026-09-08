#!/usr/bin/env bash
# set-stream-volume.sh
# Adjust relative volume of desktop audio or microphone inside stream-mix.
# Usage:
#   ./set-stream-volume.sh desktop 0.6   # desktop at 60%
#   ./set-stream-volume.sh mic 0.9        # mic at 90%
#   ./set-stream-volume.sh desktop 0      # mute desktop
#   ./set-stream-volume.sh mic 1.0        # mic at full
#   ./set-stream-volume.sh desktop mute
#   ./set-stream-volume.sh mic unmute

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IDS_FILE="$SCRIPT_DIR/.stream-audio-ids"

if [ $# -ne 2 ]; then
    echo "Usage: $0 <desktop|mic> <0.0-1.0 volume or 'mute'/'unmute'>"
    exit 1
fi

CHANNEL="$1"
ARG="$2"

if [ "$CHANNEL" != "desktop" ] && [ "$CHANNEL" != "mic" ]; then
    echo "ERROR: channel must be 'desktop' or 'mic'"
    exit 1
fi

if [ ! -f "$IDS_FILE" ]; then
    echo "ERROR: no setup state found. Run ./setup-stream-audio.sh first."
    exit 1
fi

read -r DESKTOP_MOD MIC_MOD < "$IDS_FILE"

TARGET_MOD=""
if [ "$CHANNEL" = "desktop" ]; then
    TARGET_MOD="$DESKTOP_MOD"
else
    TARGET_MOD="$MIC_MOD"
fi

[ -z "$TARGET_MOD" ] && { echo "ERROR: no module ID for $CHANNEL."; exit 1; }

# Parse sink-inputs, accumulate blocks, match target.object + pulse.module.id
SINK_INPUT_INDEX=""
current_block=""
current_idx=""

check_block() {
    if [ -z "$current_block" ]; then return; fi
    if echo "$current_block" | grep -q 'target.object = "stream-mix"'; then
        modid=$(echo "$current_block" | grep 'pulse.module.id = ' | head -1 | sed 's/.*pulse.module.id = "\(.*\)".*/\1/')
        if [ "$modid" = "$TARGET_MOD" ]; then
            SINK_INPUT_INDEX="$current_idx"
        fi
    fi
}

while IFS= read -r line || [ -n "$line" ]; do
    if echo "$line" | grep -qE '^Sink Input #'; then
        check_block
        [ -n "$SINK_INPUT_INDEX" ] && break
        current_idx=$(echo "$line" | sed 's/Sink Input #//')
        current_block=""
    fi
    current_block+="$line"$'\n'
done < <(pactl list sink-inputs 2>/dev/null)
check_block

if [ -z "$SINK_INPUT_INDEX" ]; then
    echo "ERROR: could not find $CHANNEL sink input on stream-mix (module $TARGET_MOD)."
    echo "       Is setup-stream-audio.sh running?"
    exit 1
fi

if [ "$ARG" = "mute" ]; then
    pactl set-sink-input-mute "$SINK_INPUT_INDEX" 1
    echo "$CHANNEL muted"
elif [ "$ARG" = "unmute" ]; then
    pactl set-sink-input-mute "$SINK_INPUT_INDEX" 0
    echo "$CHANNEL unmuted"
else
    if ! [[ "$ARG" =~ ^[0-9]*(\.[0-9]+)?$ ]]; then
        echo "ERROR: volume must be a number 0.0-1.0 or 'mute'/'unmute'"
        exit 1
    fi
    # pactl expects percentages: convert 0.5 -> "50%"
    pct=$(awk "BEGIN {printf \"%.0f\", $ARG * 100}")
    pactl set-sink-input-volume "$SINK_INPUT_INDEX" "${pct}%" || {
        echo "ERROR: pactl set-sink-input-volume failed."
        exit 1
    }
    echo "$CHANNEL volume set to $ARG ($pct%)"
fi
