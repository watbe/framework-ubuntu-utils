#!/usr/bin/env bash
#
# Installs the extension into the current user's GNOME Shell extension
# directory. No root required -- nothing outside $HOME is touched.

set -euo pipefail

UUID="invert-touchpad-swipe@local"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$UUID"

# Fail early on the two things most likely to be wrong.
command -v gnome-extensions >/dev/null 2>&1 || {
    echo "error: gnome-extensions not found; this needs GNOME Shell." >&2
    exit 1
}

shell_version="$(gnome-shell --version | awk '{print $3}')"
case "$shell_version" in
    50*) ;;
    *)   echo "warning: tested only on GNOME Shell 50, you have $shell_version." >&2
         echo "         It may do nothing, or throw on enable. See README." >&2 ;;
esac

mkdir -p "$DEST"
install -m 644 "$SRC/extension.js"  "$DEST/extension.js"
install -m 644 "$SRC/metadata.json" "$DEST/metadata.json"

echo "Installed to $DEST"
echo
echo "Ubuntu 26.04 and other modern GNOME systems are Wayland-only, so the"
echo "shell cannot be restarted in place. Log out and back in, then run:"
echo
echo "    gnome-extensions enable $UUID"
