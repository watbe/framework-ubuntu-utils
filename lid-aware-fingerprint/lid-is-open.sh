#!/bin/sh
# PAM helper: allow fingerprints only when every reported lid is open.
# Default: immediately decline an unavailable reader so sudo can ask for a password.
# GDM: wait quietly instead; a failure makes GNOME display an error and retry.
lid_is_open() {
    found=0
    for state in /proc/acpi/button/lid/*/state; do
        [ -r "$state" ] || return 1
        /usr/bin/grep -Eq '^state:[[:space:]]+open[[:space:]]*$' "$state" || return 1
        found=1
    done
    [ "$found" = 1 ]
}

case "${1:-}" in
    '') lid_is_open ;;
    --wait-for-open)
        # pam_exec waits for this process. Stop if its worker is cancelled/killed
        # so password unlocks and abandoned prompts do not leave polling helpers.
        worker=$PPID
        while ! lid_is_open; do
            # Check our current parent, not kill -0: a dead worker may remain
            # as a zombie, and its PID may later be reused by another process.
            /usr/bin/grep -Eq "^PPid:[[:space:]]+$worker$" "/proc/$$/status" || exit 1
            /usr/bin/sleep 1
        done
        ;;
    *) exit 2 ;;
esac
