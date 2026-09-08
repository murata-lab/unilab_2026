#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHECKPOINT="$SCRIPT_DIR/sam2.1_hiera_large.pt"
TEMP_FILE="$CHECKPOINT.download"
URL="https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"

if [ -f "$CHECKPOINT" ] && [ "$(wc -c < "$CHECKPOINT")" -gt 800000000 ]; then
    echo "SAM2 checkpoint is already present: $CHECKPOINT"
    exit 0
fi

echo "Downloading SAM2.1 large checkpoint (about 856 MiB)..."
if command -v curl >/dev/null 2>&1; then
    curl -L --fail --progress-bar -o "$TEMP_FILE" "$URL"
elif command -v wget >/dev/null 2>&1; then
    wget -O "$TEMP_FILE" "$URL"
else
    echo "curl or wget is required." >&2
    exit 1
fi

mv "$TEMP_FILE" "$CHECKPOINT"
echo "Saved: $CHECKPOINT"
