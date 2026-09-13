# ZSA Keymapp permissions fix

Fixes Keymapp's `Failed to open a device ... Permission denied` error for ZSA keyboards using USB vendor ID `3297`, including the Moonlander Mark I.

Run from this folder:

```bash
sudo bash install.sh
```

The script installs `/etc/udev/rules.d/50-zsa-keymapp.rules`, granting the `plugdev` group read/write access to matching HID devices, and reloads udev rules. It also includes ZSA's Moonlander / Planck EZ flashing rule for the STM32 bootloader (`0483:df11`), which permits all local users to access that bootloader. Unplug and reconnect the keyboard, then reopen Keymapp. Repeated runs replace only this script's rule file.

The script checks the configured group membership of the user who invoked `sudo` before changing any rules. If that user is not in `plugdev`, it stops and prints the command to add them; log out and back in afterward, then rerun the script. Run it with `sudo` from your desktop account, rather than directly from a root shell. The check reads configured membership; it cannot confirm whether an already-running desktop session has picked up a recent group change.

The bootloader uses a different USB identity from the keyboard in normal operation, so the HID rule alone does not cover Moonlander flashing. These rules cover ZSA HID connections using vendor `3297` and Moonlander / Planck EZ flashing; other models may need additional rules from [ZSA's Linux installation guide](https://github.com/zsa/wally/wiki/Linux-install).

If a `/dev/hidrawN` permission error persists after reconnecting, check `ls -l /dev/hidrawN` using the path in the current error. It should show `root plugdev` and `crw-rw----`. Fully quit and reopen Keymapp before retrying. HID device numbers can change when reconnecting. A missing bootloader rule is a separate issue from permissions on the normal HID device.

To remove the rule:

```bash
sudo rm /etc/udev/rules.d/50-zsa-keymapp.rules
sudo udevadm control --reload-rules
```

Reconnect the keyboard afterward.
