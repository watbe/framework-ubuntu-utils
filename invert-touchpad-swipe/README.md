# Invert Vertical Touchpad Swipe

A small GNOME Shell extension that reverses the direction of **vertical
three-finger touchpad swipes** while leaving the **touchpad scroll direction
unchanged**.

Tested on Ubuntu 26.04 LTS (GNOME Shell 50, Wayland).

## Why

GNOME derives touchpad gesture direction from the same setting as touchpad
scrolling: `org.gnome.desktop.peripherals.touchpad natural-scroll`. Toggling
"Natural Scrolling" in Settings → Mouse & Touchpad flips gestures *and*
scrolling together, and there is no separate setting for gestures alone. This
is [gnome-shell issue #8787](https://gitlab.gnome.org/GNOME/gnome-shell/-/issues/8787).

## What it changes

| Input | Behaviour |
| --- | --- |
| Vertical 3+ finger touchpad swipe (overview, app grid) | **Reversed** |
| Horizontal 3+ finger touchpad swipe (workspace switching) | Unchanged |
| Two-finger scrolling | Unchanged |
| Touchscreen panning | Unchanged |

GNOME treats three-finger and four-finger swipes identically, so this affects
both.

## Install

From the root of this repository, run:

```sh
cd invert-touchpad-swipe
./install.sh
```

Then log out and back in — Wayland sessions cannot restart the shell in place,
so `Alt+F2 r` is not available — and enable it:

```sh
gnome-extensions enable invert-touchpad-swipe@local
```

To remove:

```sh
./uninstall.sh
```

Disabling restores the original behaviour immediately, without a logout.

## How it works

A `SwipeTracker` turns an input gesture into a shell animation. On GNOME 50 an
overview tracker collects deltas from `_touchpadGesture`
(`TouchpadSwipeGesture`) and `_panGesture` (`Clutter_PanGesture`, touchscreen).
There is no `_scrollGesture` on this version, which is why two-finger scrolling
is untouched by anything here.

The extension overrides `emit` on `TouchpadSwipeGesture.prototype` and negates
the delta carried by the `update` signal, but only when the receiving tracker's
orientation is vertical.

The more obvious hook — `SwipeTracker.prototype._updateGesture` — does not work
on GNOME 50. Its signature was reduced to `_updateGesture(time, delta)`, with no
gesture argument, so from inside it there is no way to distinguish a touchpad
swipe from a touchscreen pan; patching it inverts both. Older guides target the
GNOME 4x signature `_updateGesture(gesture, time, delta, distance)` and will
appear to do nothing (or will silently negate the wrong argument) on GNOME 50.

## Customising

Both behaviours live in a single condition in `extension.js`:

- **Horizontal instead of vertical**: change `Clutter.Orientation.VERTICAL` to
  `Clutter.Orientation.HORIZONTAL`.
- **Both axes**: drop the `this.orientation === ...` clause entirely.

Re-run `./install.sh` and log out and back in after editing.

## Caveats

This patches GNOME Shell internals, which are private and change between
releases — the `_updateGesture` signature changed within the 4x series alone.
Expect to revisit it at the next GNOME major version. `metadata.json` declares
support for GNOME 50 only, so on an unsupported shell the extension will refuse
to load rather than misbehave.

## Troubleshooting

Check whether it loaded and what it reported:

```sh
gnome-extensions info invert-touchpad-swipe@local
journalctl -b -o cat /usr/bin/gnome-shell | grep -i 'invert-swipe\|extension'
```

`no _touchpadGesture found` in the log means GNOME renamed or restructured the
field. Inspect the current shape in Looking Glass (`Alt+F2`, then `lg`, then the
Evaluator tab):

```js
Object.keys(Main.overview._swipeTracker).join(", ")
```

If gestures stop responding entirely, disable the extension and log back in:

```sh
gnome-extensions disable invert-touchpad-swipe@local
```

## Source and license

Copied from [watbe/invert-touchpad-swipe](https://github.com/watbe/invert-touchpad-swipe)
at commit [`0c2c8c4`](https://github.com/watbe/invert-touchpad-swipe/commit/0c2c8c426fd0a0d43777036338b65a14d0eee7de).
The extension and scripts are unchanged; installation instructions and the
metadata URL have been updated for this copy. Licensed under the
[Mozilla Public License 2.0](LICENSE).
