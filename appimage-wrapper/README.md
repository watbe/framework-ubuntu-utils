# Single-instance AppImage wrappers

Run the commands below from this utility’s directory (`cd appimage-wrapper` from the repository root).

`generate-appimage-wrapper.py` generates a standalone `{app}-single` launcher in `~/.local/bin`. Supply a local AppImage path, symlink, or `file://` URI. It does not download or execute the AppImage, or modify desktop launchers.

```sh
python3 generate-appimage-wrapper.py ~/Apps/Beeper-4.3.113-x86_64.AppImage
```

This creates `~/.local/bin/beeper-single`. On each launch, it finds matching versions in the original directory and chooses the highest filename using GNU version sorting (so `4.10` follows `4.9`). The first numeric version token preceded by a space, dot, underscore, or hyphen is replaced with a wildcard; the app prefix, architecture, and channel suffix remain fixed. A leading `v` on the version is supported. Names without a recognized version match exactly. An old version's path can be supplied even after that file has been removed.

The wrapper uses the same lock across matched versions. A second launch exits successfully without starting another instance. Arguments are forwarded unchanged. `flock --no-fork` preserves the launch PID and inherited startup environment for desktop tracking.

Set the `Exec` line in your personal `.desktop` launcher to the wrapper's absolute path, preserving its existing `%u`, `%U`, `%f`, or `%F` argument if present. For example:

```ini
Exec=/home/wayne/.local/bin/beeper-single %u
```

Quote the executable path with double quotes if it contains spaces. Fully quit an already-running app before switching to the wrapper.

Keep the existing desktop file name, `Icon`, and `StartupWMClass` fields so the desktop can associate the application window with its launcher. The wrapper cannot correct an application's mismatched Wayland app ID or window class.

Use `--output-dir DIRECTORY` to choose another destination, or `--force` to replace an existing wrapper. The generator requires Python 3; generated wrappers require Bash, `flock`, GNU `sort`, and a desktop session with `XDG_RUNTIME_DIR` set. Run it as your normal user, without `sudo`.

All launches must go through the wrapper. Launching the AppImage directly bypasses the lock; an updater that rewrites the desktop launcher may also bypass it. Duplicate launches do not focus the existing window or deliver links/files to it. Applications that detach into the background and close inherited file descriptors may release the lock early. Version sorting follows filenames rather than full semantic-version precedence; inspect the generated pattern for unusual naming schemes. Remove the generated wrapper and restore the original desktop command to undo the setup.

Run the generator's integration checks with `python3 -B -m unittest -v test_appimage_wrapper.py`.
