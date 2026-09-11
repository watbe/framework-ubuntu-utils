# Magic Trackpad fix

Run the commands below from this utility’s directory (`cd magic-trackpad-fix` from the repository root).

`install-magic-trackpad-fix.sh` keeps a wired Apple Magic Trackpad 2 (Lightning, USB ID `05ac:0265`) working when the laptop lid is closed. It installs a udev rule marking the trackpad as external, correcting libinput's classification of it as an internal touchpad. Other Apple trackpad models are unaffected.

Install the fix:

```sh
sudo bash install-magic-trackpad-fix.sh
```

Remove the fix:

```sh
sudo bash install-magic-trackpad-fix.sh --uninstall
```

After either operation, unplug and reconnect the trackpad or reboot to apply the change. No packages, downloads, or kernel changes are needed. The fix was confirmed on Ubuntu 26.04 with libinput 1.31.1.
