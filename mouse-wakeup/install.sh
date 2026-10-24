#!/usr/bin/env bash
# Select USB and Bluetooth devices that may wake the laptop from suspend.
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec /usr/bin/python3 "$source_dir/wake-devices.py" "$@"
