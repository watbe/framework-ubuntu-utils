#!/usr/bin/env bash
#
# Disables and removes the extension.

set -euo pipefail

UUID="invert-touchpad-swipe@local"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$UUID"

# Disabling first restores the patched prototype in the running shell, so
# gestures return to normal immediately without a logout.
if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions disable "$UUID" 2>/dev/null || true
fi

rm -rf "$DEST"
echo "Removed $DEST"
