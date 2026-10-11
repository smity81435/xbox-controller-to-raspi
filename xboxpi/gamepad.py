"""Callback API over evdev.

    pad = Gamepad()

    @pad.on_press(Button.A)
    def jump(): ...

    @pad.on_hold(Button.A, seconds=2, progress=lambda f: draw_bar(f))
    def confirm(): ...

    pad.start()          # background thread; or pad.run() to block

Dispatcher holds all the event logic and touches no hardware, so it can be
unit tested; Gamepad adds device discovery, reconnects and rumble.
"""

from __future__ import annotations

import logging
import select
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from .buttons import (ABS_HAT0X, ABS_HAT0Y, EV_ABS, EV_KEY, LAYOUT_USB, Axis, Button,
                      layout_for)

log = logging.getLogger(__name__)

TRIGGERS = (Axis.LT, Axis.RT)


@dataclass
class _Hold:
    button: Button
    seconds: float
    fn: Callable[[], None]
    progress: Callable[[float | None], None] | None
    started: float | None = None


def _call(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:  # noqa: BLE001 - a bad callback must not kill input handling
        log.exception("gamepad callback %r failed", fn)


class Dispatcher:
    def __init__(self, deadzone: float = 0.08):
        self.deadzone = deadzone
        self._press: dict[Button, list] = defaultdict(list)
        self._release: dict[Button, list] = defaultdict(list)
        self._any: list = []
        self._axis: list = []
        self._holds: list[_Hold] = []
        self._layout = LAYOUT_USB
        self._ranges: dict[int, tuple[int, int]] = {}
        self._axis_values: dict[Axis, float] = {}
        self._hat = {ABS_HAT0X: 0, ABS_HAT0Y: 0}
        self.pressed: set[Button] = set()

    # Registration ------------------------------------------------------

    def on_press(self, button: Button):
        def register(fn):
            self._press[button].append(fn)
            return fn
        return register

    def on_release(self, button: Button):
        def register(fn):
            self._release[button].append(fn)
            return fn
        return register

    def on_hold(self, button: Button, seconds: float = 1.0, progress: Callable[[float | None], None] | None = None):
        """fn fires once after `button` is held for `seconds`. progress(f) gets 0..1
        while holding and None when the hold ends (fired or let go early)."""
        def register(fn):
            self._holds.append(_Hold(button, seconds, fn, progress))
            return fn
        return register

    def on_any(self, fn: Callable[[Button, bool], None]):
        """fn(button, pressed) for every button change, d-pad included."""
        self._any.append(fn)
        return fn

    def on_axis(self, fn: Callable[[Axis, float], None]):
        """fn(axis, value): sticks -1..1 with a deadzone, triggers 0..1."""
        self._axis.append(fn)
        return fn

    # Input -------------------------------------------------------------

    def set_device(self, abs_codes: set[int], ranges: dict[int, tuple[int, int]]) -> None:
        self._layout = layout_for(abs_codes)
        self._ranges = ranges

    def feed(self, etype: int, code: int, value: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if etype == EV_KEY:
            if value == 2:  # autorepeat
                return
            try:
                button = Button(code)
            except ValueError:
                return
            self._button(button, bool(value), now)
        elif etype == EV_ABS:
            if code in self._hat:
                self._dpad(code, value, now)
            elif code in self._layout:
                self._axis_event(self._layout[code], code, value)

    def tick(self, now: float | None = None) -> None:
        """Call often (Gamepad does, every 50 ms) so holds can fire."""
        now = time.time() if now is None else now
        for hold in self._holds:
            if hold.started is None:
                continue
            fraction = (now - hold.started) / hold.seconds if hold.seconds else 1.0
            if fraction < 1.0:
                if hold.progress:
                    _call(hold.progress, fraction)
                continue
            hold.started = None
            if hold.progress:
                _call(hold.progress, None)
            _call(hold.fn)

    def axis(self, axis: Axis) -> float:
        return self._axis_values.get(axis, 0.0)

    # Internals ---------------------------------------------------------

    def _button(self, button: Button, down: bool, now: float) -> None:
        if down == (button in self.pressed):
            return
        if down:
            self.pressed.add(button)
        else:
            self.pressed.discard(button)
        for fn in self._any:
            _call(fn, button, down)
        for fn in (self._press if down else self._release)[button]:
            _call(fn)
        for hold in self._holds:
            if hold.button != button:
                continue
            if down:
                hold.started = now
            elif hold.started is not None:
                hold.started = None
                if hold.progress:
                    _call(hold.progress, None)

    def _dpad(self, code: int, value: int, now: float) -> None:
        neg, pos = ((Button.DPAD_LEFT, Button.DPAD_RIGHT) if code == ABS_HAT0X
                    else (Button.DPAD_UP, Button.DPAD_DOWN))
        old = self._hat[code]
        self._hat[code] = value
        if old < 0:
            self._button(neg, False, now)
        elif old > 0:
            self._button(pos, False, now)
        if value < 0:
            self._button(neg, True, now)
        elif value > 0:
            self._button(pos, True, now)

    def _axis_event(self, axis: Axis, code: int, value: int) -> None:
        lo, hi = self._ranges.get(code, (0, 255) if axis in TRIGGERS else (-32768, 32767))
        span = (hi - lo) or 1
        if axis in TRIGGERS:
            norm = min(max((value - lo) / span, 0.0), 1.0)
        else:
            norm = min(max(2 * (value - lo) / span - 1, -1.0), 1.0)
            if abs(norm) < self.deadzone:
                norm = 0.0
        norm = round(norm, 3)
        if self._axis_values.get(axis) == norm:
            return
        self._axis_values[axis] = norm
        for fn in self._axis:
            _call(fn, axis, norm)


class Gamepad(Dispatcher):
    """Finds the first matching pad, feeds its events, reconnects when it drops."""

    def __init__(self, names: tuple[str, ...] = ("xbox", "x-box"), deadzone: float = 0.08,
                 reconnect_s: float = 5.0):
        super().__init__(deadzone)
        self.names = tuple(n.lower() for n in names)
        self.reconnect_s = reconnect_s
        self.device = None
        self._connect_fns: list = []
        self._disconnect_fns: list = []
        self._stop = threading.Event()

    @property
    def connected(self) -> bool:
        return self.device is not None

    def on_connect(self, fn: Callable[[str], None]):
        self._connect_fns.append(fn)
        return fn

    def on_disconnect(self, fn: Callable[[], None]):
        self._disconnect_fns.append(fn)
        return fn

    def start(self) -> "Gamepad":
        threading.Thread(target=self.run, name="xboxpi", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        waiting_logged = False
        while not self._stop.is_set():
            dev = self._find()
            if dev is None:
                if not waiting_logged:
                    log.info("waiting for a controller")
                    waiting_logged = True
                self._stop.wait(self.reconnect_s)
                continue
            waiting_logged = False
            self._attach(dev)
            try:
                self._read(dev)
            except OSError as e:
                log.info("controller disconnected: %s", e)
            finally:
                self._detach(dev)

    def rumble(self, ms: int = 300, strong: float = 0.75, weak: float = 0.5) -> bool:
        """Best effort; returns False if the pad or driver can't rumble."""
        dev = self.device
        if dev is None:
            return False
        try:
            from evdev import ecodes, ff

            effect = ff.Effect(
                ecodes.FF_RUMBLE, -1, 0, ff.Trigger(0, 0), ff.Replay(ms, 0),
                ff.EffectType(ff_rumble_effect=ff.Rumble(
                    strong_magnitude=int(strong * 0xFFFF), weak_magnitude=int(weak * 0xFFFF))),
            )
            dev.write(ecodes.EV_FF, dev.upload_effect(effect), 1)
            return True
        except Exception as e:  # noqa: BLE001
            log.debug("rumble failed: %s", e)
            return False

    # Internals ---------------------------------------------------------

    def _find(self):
        try:
            import evdev
        except ImportError as e:  # not Linux, or evdev missing
            raise RuntimeError("xboxpi needs the evdev package on Linux") from e
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue  # no permission: is the user in the 'input' group?
            if Button.A in dev.capabilities().get(EV_KEY, []) and any(n in dev.name.lower() for n in self.names):
                return dev
            dev.close()
        return None

    def _attach(self, dev) -> None:
        abs_caps = dict(dev.capabilities(absinfo=True).get(EV_ABS, []))
        self.set_device(set(abs_caps), {code: (info.min, info.max) for code, info in abs_caps.items()})
        self.device = dev
        log.info("controller connected: %s", dev.name)
        for fn in self._connect_fns:
            _call(fn, dev.name)

    def _detach(self, dev) -> None:
        self.device = None
        for button in list(self.pressed):  # don't leave buttons stuck down
            self._button(button, False, time.time())
        try:
            dev.close()
        except OSError:
            pass
        for fn in self._disconnect_fns:
            _call(fn)

    def _read(self, dev) -> None:
        while not self._stop.is_set():
            ready, _, _ = select.select([dev.fd], [], [], 0.05)
            now = time.time()
            if ready:
                for event in dev.read():
                    self.feed(event.type, event.code, event.value, now)
            self.tick(now)
