#!/bin/sh
# PAM helper: allow fingerprints only when every reported lid is open.
# Missing, unreadable or unexpected state falls back to password authentication.
found=0
for state in /proc/acpi/button/lid/*/state; do
    [ -r "$state" ] || exit 1
    /usr/bin/grep -Eq '^state:[[:space:]]+open[[:space:]]*$' "$state" || exit 1
    found=1
done
[ "$found" = 1 ]
