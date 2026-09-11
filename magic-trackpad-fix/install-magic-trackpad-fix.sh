#!/usr/bin/env bash
# Keep a wired Apple Magic Trackpad 2 (Lightning, USB 05ac:0265) working
# with the laptop lid closed on Ubuntu.
#
# Some libinput versions classify this USB trackpad as internal. This udev
# rule explicitly marks it external so lid handling does not suppress input.
# Confirmed on Ubuntu 26.04 with libinput 1.31.1; also resolved input failing
# after reboot on the affected machine. Other Apple models are unaffected.
#
# Usage:
#   sudo bash install-magic-trackpad-fix.sh
#   sudo bash install-magic-trackpad-fix.sh --uninstall
#
# After either operation, unplug/reconnect the trackpad or reboot. Reloading
# udev rules alone does not make an existing desktop input device reload them.
# No packages, downloads, or kernel changes are needed. Installation is safe
# to repeat; it replaces only the rule file named below.

set -euo pipefail

rule_file=/etc/udev/rules.d/91-apple-magic-trackpad-external.rules
action=${1:-install}

if (( $# > 1 )); then
    echo "Expected at most one argument; use --help." >&2
    exit 2
fi

case "$action" in
    -h|--help)
        printf 'Usage: sudo bash %s [--uninstall]\n' "$0"
        echo 'Marks the Lightning Magic Trackpad 2 as external for lid-close handling.'
        echo 'Unplug/reconnect the trackpad or reboot after installing or removing.'
        exit 0
        ;;
    install|--uninstall) ;;
    *) echo "Unknown argument: $action (use --help)." >&2; exit 2 ;;
esac

if (( EUID != 0 )); then
    echo "Run this script with sudo (use --help for usage)." >&2
    exit 1
fi
if ! command -v udevadm >/dev/null 2>&1; then
    echo "udevadm is required; this script is intended for Ubuntu with udev." >&2
    exit 1
fi

if [[ "$action" == --uninstall ]]; then
    rm -f -- "$rule_file"
    echo "Removed $rule_file"
else
    temporary_rule=$(mktemp)
    trap 'rm -f -- "$temporary_rule"' EXIT
    cat > "$temporary_rule" <<'RULE'
# Apple Magic Trackpad 2 (Lightning): allow input while the laptop lid is closed.
# Override libinput's internal-touchpad fallback for USB vendor/product 05ac:0265.
ACTION!="remove", SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_TOUCHPAD}=="1", ATTRS{id/bustype}=="0003", ATTRS{id/vendor}=="05ac", ATTRS{id/product}=="0265", ENV{ID_INPUT_TOUCHPAD_INTEGRATION}="external"
RULE
    install -d -m 0755 /etc/udev/rules.d
    install -m 0644 -- "$temporary_rule" "$rule_file"
    echo "Installed $rule_file"
fi

udevadm control --reload-rules
echo 'Done. Unplug/reconnect the trackpad once, or reboot, to apply the change.'
