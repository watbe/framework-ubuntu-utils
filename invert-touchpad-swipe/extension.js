// Invert Vertical Touchpad Swipe
//
// GNOME derives touchpad *gesture* direction from the same setting as touchpad
// *scrolling*: org.gnome.desktop.peripherals.touchpad natural-scroll. Flipping
// that setting in Settings -> Mouse & Touchpad reverses both at once, and there
// is no separate knob for gestures. See:
// https://gitlab.gnome.org/GNOME/gnome-shell/-/issues/8787
//
// This extension decouples them: vertical three-finger swipes are reversed,
// while the scroll direction setting keeps doing whatever you asked it to.
//
// ---------------------------------------------------------------------------
// How it works, and why it is done this way
// ---------------------------------------------------------------------------
//
// A SwipeTracker is the object that turns an input gesture into a shell
// animation (overview, app grid, workspace switch). Each tracker collects
// deltas from several gesture sources. On GNOME 50 an overview SwipeTracker
// carries these fields:
//
//   _touchpadGesture : TouchpadSwipeGesture   <- what we want to invert
//   _panGesture      : Clutter_PanGesture     <- touchscreen, leave alone
//   _history         : EventHistory
//   _snapPoints      : Array
//
// Note there is no _scrollGesture: on this version two-finger scrolling does
// not flow through the tracker at all, which is exactly why normal scrolling
// is unaffected by anything below.
//
// The obvious hook would be SwipeTracker.prototype._updateGesture. It is not
// usable for our purpose on GNOME 50, because its signature has been reduced
// to:
//
//   _updateGesture(time, delta)
//
// The emitting gesture object is no longer passed in, so from inside that
// method there is no way to tell a touchpad swipe from a touchscreen pan --
// patching it would invert both. (On older GNOME versions the signature was
// _updateGesture(gesture, time, delta, distance), which is why guides written
// for GNOME 4x do not work here.)
//
// So instead we patch one level upstream: the 'update' signal emission on
// TouchpadSwipeGesture itself. At that point we know the source is the
// touchpad by construction, because that is the only class we touched.
//
// The patch is applied to the *prototype*, so it affects every
// TouchpadSwipeGesture instance in the shell -- including the horizontal
// workspace-switching trackers. That is what the orientation check inside the
// override is for: only VERTICAL trackers get their delta negated.

import Clutter from 'gi://Clutter';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export default class InvertVerticalTouchpadSwipe extends Extension {
    enable() {
        // TouchpadSwipeGesture is not exported from swipeTracker.js, so we
        // cannot import the class directly. We reach it through a live
        // instance: the overview's SwipeTracker is created at shell startup
        // and always exists by the time extensions are enabled.
        const gesture = Main.overview?._swipeTracker?._touchpadGesture;
        if (!gesture) {
            // Most likely cause: a GNOME update renamed or restructured this
            // field. Check the field list with, in Looking Glass (Alt+F2, lg):
            //   Object.keys(Main.overview._swipeTracker).join(", ")
            console.error('invert-swipe: no _touchpadGesture found; ' +
                'GNOME internals have probably changed');
            return;
        }

        // Keep a reference to the prototype we patched rather than looking it
        // up again in disable(): guarantees we restore the same object even if
        // the shell has rebuilt its trackers in the meantime.
        this._proto = gesture.constructor.prototype;
        this._origEmit = this._proto.emit;

        const origEmit = this._origEmit;

        this._proto.emit = function (signal, ...args) {
            // 'update' carries the incremental swipe movement. Other signals
            // ('begin', 'end', 'cancel') pass through untouched.
            //
            // args for 'update' on GNOME 50 is [time, delta]. We defensively
            // check the length rather than destructuring, so that if a future
            // version adds or reorders parameters we degrade to "does nothing"
            // instead of corrupting an unrelated argument.
            if (signal === 'update' &&
                this.orientation === Clutter.Orientation.VERTICAL &&
                args.length >= 2)
                args[1] = -args[1];

            return origEmit.call(this, signal, ...args);
        };
    }

    disable() {
        // Extensions must fully undo their monkey-patching here; GNOME unloads
        // and reloads extensions on lock/unlock and on manual toggling.
        if (this._proto && this._origEmit)
            this._proto.emit = this._origEmit;

        this._proto = null;
        this._origEmit = null;
    }
}
