# Lid-aware fingerprint authentication

Requires a password when starting a GNOME session, and offers fingerprint authentication for screen unlocking, `sudo`, `sudo -i`, and Polkit administrative prompts only when the laptop lid is open.

Designed for Ubuntu 26.04 with GDM/GNOME. Configuration was checked against Ubuntu 26.04.1, GNOME/GDM 50.1, and fprintd 1.94.5 on a Framework laptop. Automated tests cover file restoration and PAM control flow; physical fingerprint/login testing remains necessary after installation.

| Authentication | Lid open | Lid closed or state unavailable |
| --- | --- | --- |
| New login after boot or logout | Password | Password |
| Unlock an existing GNOME session | Fingerprint or password | Password |
| `sudo`, `sudo -i`, Polkit authentication | Fingerprint, then password fallback | Password |

Password login supplies the secret needed to unlock the GNOME **login keyring**, provided its password matches the login password. Fingerprint authentication does not unlock a locked keyring. This utility requires a password for every new session, including after logout, rather than tracking the first login per boot.

## Install

Run these commands from this directory (`cd lid-aware-fingerprint` from the repository root).

First enroll a fingerprint in **Settings → System → Users → Fingerprint Login**. If the required packages are missing:

```sh
sudo apt install fprintd libpam-fprintd
```

Leave the global **Fingerprint authentication** option in `sudo pam-auth-update` disabled. This utility supplies service-specific rules. It refuses an existing global fingerprint stack or an unfamiliar/MFA authentication stack instead of silently bypassing its rules.

Inspect the planned changes:

```sh
python3 install-lid-aware-fingerprint.py --dry-run
```

Keep a separate authenticated root terminal open during installation and testing (`sudo -i`), so you can remove the changes if necessary. Install:

```sh
sudo python3 install-lid-aware-fingerprint.py
```

New PAM authentication attempts use the changes immediately. **Reboot to apply the initial-login setting.** The script does not restart GDM, terminate your session, change fingerprint enrollment, or install packages.

Your normal user must have fingerprint unlocking enabled; the installer does not modify user preferences. Check this from your desktop terminal, without `sudo`:

```sh
gsettings get org.gnome.login-screen enable-fingerprint-authentication
```

If it is `false`, enable it as your normal user:

```sh
gsettings set org.gnome.login-screen enable-fingerprint-authentication true
```

The password-only initial-login setting is applied separately to GDM's greeter. A previously customized GDM-user dconf override or administrator dconf lock can override the greeter defaults and needs separate review.

## Remove

```sh
sudo python3 install-lid-aware-fingerprint.py --uninstall --dry-run
sudo python3 install-lid-aware-fingerprint.py --uninstall
```

Reboot to apply the restored initial-login setting. Removal restores pre-installation file contents, owners, and permissions, and deletes files introduced by the utility. In particular, if Polkit originally used its vendor configuration, removal deletes the local override so vendor defaults apply again. Existing enrolled fingerprints and any user preference you changed manually remain.

Both installation and removal can be repeated. Original files are saved, with metadata and installed-file hashes, in the root-readable `/var/lib/framework-lid-aware-fingerprint/state.json`. Do not delete this file while installed. Interrupted installation/removal can be recovered by running `--uninstall`; ordinary installation write errors trigger rollback automatically.

If a managed file was edited or replaced by a package update, removal stops **before changing any files** and names the conflicts. Review those changes against the original content in the backup manifest (`original.data` is base64 encoded). Reconcile the conflicting files to their original or installed versions, then rerun removal. There is deliberately no force-overwrite option. If authentication fails, use the root terminal kept open during setup, or Ubuntu recovery mode, to run removal.

## How it works

The installer makes local changes to:

- `/etc/gdm3/greeter.dconf-defaults`: disables fingerprints in the initial login greeter. Ubuntu's GDM startup compiles this file automatically.
- `/etc/pam.d/gdm-fingerprint`: inserts a `requisite` lid check immediately before fingerprint authentication. Closed or unknown lid state fails this authentication path; GDM's separate password path remains available.
- `/etc/pam.d/sudo`, `/etc/pam.d/sudo-i`, and `/etc/pam.d/polkit-1`: inserts a conditional fingerprint attempt before `common-auth`. A failed lid check skips just the fingerprint module. Successful fingerprints authenticate; a failed scan or timeout proceeds to the existing password stack. Account and session rules still apply.
- `/usr/local/libexec/framework-lid-is-open`: installs `lid-is-open.sh` as a root-owned executable. It accepts only an explicit `open` state from every lid under `/proc/acpi/button/lid/*/state`.

If a PAM service has no file in `/etc/pam.d`, the installer reads `/usr/lib/pam.d` and creates a local override. Vendor files and `common-auth` are not modified. Because local PAM overrides take precedence, review this utility after major PAM/Ubuntu upgrades; it intentionally supports only Ubuntu 26.04 and recognized service layouts.

The GDM check must **fail** the fingerprint stack when the lid is closed, rather than skipping its authentication module and accidentally allowing success without verification. The administrative stacks instead skip the optional fingerprint attempt and continue to password verification. The lid check by itself never authenticates a user.

## Behavior and limitations

- Lid state is sampled when authentication starts. Closing the lid during an active scan does not cancel it; reopening the lid may require starting a new authentication attempt.
- For `sudo` and Polkit, fingerprints and passwords run sequentially. An open lid allows one scan attempt, with a 10-second timeout before password fallback. GDM provides its own separate password path.
- Polkit may ask to authenticate an administrator other than the current user. That account needs enrolled fingerprints. The script does not change which account Polkit or sudo selects, authorization policies, or credential caching.
- GNOME keyring unlock dialogs are separate from Polkit and still require the keyring password. This does not change disk-encryption prompts, SSH, TTY login, `su`, KDE, or applications using other PAM services.
- A keyring explicitly locked during a session still needs its password. This utility does not inspect or unlock the keyring itself.
- Keep `common-auth` password-based after installation. Enabling global fingerprint authentication later would reintroduce unconditional fingerprint prompts through that shared stack.

## Verify

After reboot, verify that initial login requests a password and the login keyring opens. Then lock the session and test both lid positions (using an external display/input devices when closed).

Force a fresh sudo authentication attempt with:

```sh
sudo -k
sudo -v
```

With the lid open, test a successful fingerprint and a scan timeout followed by password fallback. Repeat with the lid closed; it should request the password directly. Test a fresh Polkit administrative prompt as well; cached authorization can suppress prompts. Finally, verify removal restores the original behavior.

Run the isolated automated tests without sudo:

```sh
python3 -m unittest discover -s . -p 'test_*.py' -v
```

Tests use temporary directories, `dconf compile`, and the real Linux-PAM library with deterministic success/failure modules substituted for hardware and password verification. They do not change live authentication or require fingerprint input. Restricted sandboxes can cause PAM's audit calls to return `System error`; run these tests in a normal local terminal.

References: Ubuntu's [PAM configuration](https://manpages.ubuntu.com/manpages/resolute/man5/pam.d.5.html), [pam_exec](https://manpages.ubuntu.com/manpages/resolute/man8/pam_exec.8.html), and [pam_fprintd](https://manpages.ubuntu.com/manpages/resolute/man8/pam_fprintd.8.html) manuals, and GNOME's [fingerprint authentication setting](https://help.gnome.org/system-admin-guide/login-fingerprint.html).
