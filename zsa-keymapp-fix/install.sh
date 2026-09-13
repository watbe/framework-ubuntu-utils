#!/usr/bin/env bash
# Allow Keymapp connections and Moonlander/Planck EZ firmware flashing.
set -euo pipefail

if (( $# > 0 )); then
    printf 'Usage: sudo bash %s\n' "$0"
    if (( $# == 1 )) && [[ "$1" == --help || "$1" == -h ]]; then
        exit 0
    fi
    exit 2
fi

if (( EUID != 0 )); then
    echo "Run this script with sudo." >&2
    exit 1
fi
if ! command -v udevadm >/dev/null 2>&1; then
    echo "udevadm is required; this script is intended for Ubuntu with udev." >&2
    exit 1
fi
if ! getent group plugdev >/dev/null; then
    echo "The plugdev group must exist before installing this rule." >&2
    exit 1
fi

# Check the desktop user's configured groups, not sudo's root account.
desktop_user=${SUDO_USER:-}
if [[ -z "$desktop_user" || "$desktop_user" == root ]]; then
    echo "Run this script using sudo from your desktop user's account so its plugdev membership can be checked." >&2
    exit 1
fi
if ! user_groups=$(id -nG -- "$desktop_user"); then
    echo "Could not check groups for $desktop_user." >&2
    exit 1
fi
if [[ " $user_groups " != *" plugdev "* ]]; then
    printf 'User %s is not in plugdev. Run:\n' "$desktop_user" >&2
    printf '  sudo usermod -aG plugdev -- %q\n' "$desktop_user" >&2
    echo 'Then log out and back in, and rerun this script.' >&2
    exit 1
fi
printf 'Confirmed %s belongs to plugdev.\n' "$desktop_user"

# Use a separate file to preserve any existing ZSA flashing rules.
rule_file=/etc/udev/rules.d/50-zsa-keymapp.rules
temporary_rule=$(mktemp)
trap 'rm -f -- "$temporary_rule"' EXIT
cat > "$temporary_rule" <<'RULE'
# Allow plugdev members to access ZSA keyboards in Keymapp.
KERNEL=="hidraw*", ATTRS{idVendor}=="3297", MODE="0660", GROUP="plugdev"

# ZSA's Moonlander / Planck EZ STM32 bootloader flashing rule.
SUBSYSTEMS=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="df11", MODE:="0666", SYMLINK+="stm32_dfu"
RULE
install -m 0644 -- "$temporary_rule" "$rule_file"
udevadm control --reload-rules
echo "Installed $rule_file"
echo 'Unplug and reconnect the keyboard, then reopen Keymapp.'
echo 'Your desktop user must belong to plugdev; log out and back in if newly added.'
