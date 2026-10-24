# USB and Bluetooth suspend wake

Choose which eligible USB or paired Bluetooth devices may wake the laptop
from suspend. This includes USB mice/keyboards and Bluetooth trackpads such
as the Apple Magic Trackpad. The installer applies the selection immediately
and keeps it across reboots. It does not suspend the laptop to test it.

From the repository root, run the chooser:

```sh
sudo bash mouse-wakeup/install.sh
```

Enter one or more device numbers, separated by commas or spaces. Enter with
no selection cancels without changes. Running the chooser again replaces the
previous selection and restores settings for devices that were deselected.
Other devices' individual wake permissions are left as they were.

To list candidates without changing anything or using sudo:

```sh
bash mouse-wakeup/install.sh --list
```

For noninteractive use, pass the IDs printed by `--list`:

```sh
sudo bash mouse-wakeup/install.sh --device 'ID_FROM_LIST' --device 'ANOTHER_ID'
```

The old G700s-only installer at this path is superseded by this chooser.
Installation removes its old `91-logitech-g700s-wakeup.rules` file, if present.

## Eligible devices and shared hardware

- USB candidates must expose a nonempty `power/wakeup` control. Hubs are not
  selection targets. Devices with a serial number are matched by USB vendor,
  product and serial, regardless of port. Devices without a serial are grouped
  by vendor/product; selecting that group affects **all units of that model**,
  including any units that do have serial numbers.
- Bluetooth candidates must be paired, expose BlueZ's `WakeAllowed` property,
  and have a supported wake-capable USB/PCI adapter path. Selection sets
  `WakeAllowed=true` through BlueZ, which saves the per-device policy. Devices
  need not be connected if BlueZ already knows their wake capability.
- Wake-capable USB hubs and PCI controllers along a selected device's path
  are also enabled so they can forward wake requests. These are shared:
  enabling the Bluetooth adapter also allows other devices whose own
  `WakeAllowed` policy is already true to request wake. Enabling USB hub wake
  can also allow connection/disconnection events to wake the laptop.

USB hub rules are tied to the current physical port/controller. Re-run the
chooser after moving devices to a different dock or controller so their
forwarding paths are included. The utility supports USB and PCI wake controls;
other adapter transports are not offered unless a supported wake path exists.

An exposed control means the kernel/BlueZ allows the request; it does not
prove that the device, firmware and dock will successfully resume the laptop.
Clicking versus movement behavior depends on the device. A manual suspend test
is still required for each selection.

On this machine on 24 October 2026, the Bluetooth Magic Trackpad already had
`WakeAllowed=true`, while the Intel PCI Bluetooth adapter (`8086:e476`,
`btintel_pcie`) had `power/wakeup=disabled`. Selecting the trackpad enables
that adapter path as well as setting the device's BlueZ policy.

## Removal and recovery

```sh
sudo bash mouse-wakeup/install.sh --uninstall
```

Removal deletes the generated udev rules and restores recorded hardware wake
settings on matching devices that are currently present. Matching serial-numbered
USB devices can be restored even after moving ports. If several indistinguishable
USB units originally had different settings and move ports, an ambiguous setting
is left unchanged with a message. Absent USB devices return to their normal
policy when reconnected after rule removal. Bluetooth permissions are restored
through BlueZ; if BlueZ is unavailable, bring it back and retry removal.

Generated files:

- `/etc/udev/rules.d/91-framework-input-wakeup.rules`: selected device and
  forwarding-path wake controls, reapplied on device add/bind/change.
- `/var/lib/framework-input-wakeup/state.json`: private undo information and
  selection IDs. No Bluetooth pairing keys are read or copied.

Undo information is saved before settings are applied and retained if an
operation fails, so `--uninstall` can recover a partial installation. Repeated
installation preserves the recorded original settings rather than recording
the enabled settings as a new baseline.

## Screen blanking and suspend policy

This utility changes suspend-wake permissions, not screen-lock or automatic
suspend policy. The separate wired Magic Trackpad classification fix is also
unchanged. When only the display is blank, normal mouse/trackpad activity
should wake it without a suspend-wake rule. The G700s successfully woke the
external display in unlocked and locked-screen tests on 24 October 2026;
the previously reported intermittent display-only failure was not reproduced.

The existing docked-AC keep-awake workaround may block a manual suspend test.
If needed, pause it and restore it afterwards:

```sh
systemctl --user stop framework-dock-wake.service
# Suspend through Ubuntu's system menu and test your selected devices.
systemctl --user start framework-dock-wake.service
```

## Requirements and validation

Ubuntu with udev, Python 3, and PyGObject (`python3-gi`) for Bluetooth discovery.
USB selection still works if BlueZ discovery is unavailable; it prints the
Bluetooth error rather than silently claiming Bluetooth support.

```sh
bash -n mouse-wakeup/install.sh
python3 -m unittest discover -s mouse-wakeup -p 'test_*.py'
```

Tests use simulated hardware and validate generated rules with `udevadm verify`;
they do not change the machine's wake settings or trigger suspend.

References: [Linux USB power management](https://docs.kernel.org/driver-api/usb/power-management.html),
[BlueZ Device API](https://kernel.googlesource.com/pub/scm/bluetooth/bluez.git/+/refs/tags/5.85/doc/org.bluez.Device.rst).
