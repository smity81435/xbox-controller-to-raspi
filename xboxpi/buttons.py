"""Button and axis names, mapped to Linux input codes.

Button codes are the same over USB (xpad driver) and Bluetooth (hid-microsoft);
verified on an Xbox One S controller (model 1708, firmware 5.23). Sticks and
triggers use different axis codes per transport, so Gamepad detects the layout
from the device's capabilities instead of hard-coding one.
"""

from __future__ import annotations

from enum import Enum, IntEnum

# linux/input-event-codes.h
EV_KEY, EV_ABS, EV_FF = 0x01, 0x03, 0x15
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
ABS_GAS, ABS_BRAKE = 0x09, 0x0A
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11


class Button(IntEnum):
    A = 0x130
    B = 0x131
    X = 0x133
    Y = 0x134
    LB = 0x136
    RB = 0x137
    VIEW = 0x13A  # the two-squares button (BTN_SELECT)
    MENU = 0x13B  # the three-lines button (BTN_START)
    XBOX = 0x13C  # guide button (BTN_MODE)
    LS = 0x13D  # left stick click
    RS = 0x13E  # right stick click
    # The d-pad arrives as a hat axis; Gamepad turns it into these presses.
    DPAD_LEFT = 0x220
    DPAD_RIGHT = 0x221
    DPAD_UP = 0x222
    DPAD_DOWN = 0x223


class Axis(str, Enum):
    LEFT_X = "left_x"  # -1 (left) .. 1 (right)
    LEFT_Y = "left_y"  # -1 (up) .. 1 (down), as the kernel reports it
    RIGHT_X = "right_x"
    RIGHT_Y = "right_y"
    LT = "lt"  # 0 .. 1
    RT = "rt"


# Axis code -> Axis for each transport.
LAYOUT_USB = {ABS_X: Axis.LEFT_X, ABS_Y: Axis.LEFT_Y, ABS_RX: Axis.RIGHT_X, ABS_RY: Axis.RIGHT_Y,
              ABS_Z: Axis.LT, ABS_RZ: Axis.RT}
LAYOUT_BLUETOOTH = {ABS_X: Axis.LEFT_X, ABS_Y: Axis.LEFT_Y, ABS_Z: Axis.RIGHT_X, ABS_RZ: Axis.RIGHT_Y,
                    ABS_BRAKE: Axis.LT, ABS_GAS: Axis.RT}


def layout_for(abs_codes: set[int]) -> dict[int, Axis]:
    """Pick the axis layout from the axes a device reports."""
    if ABS_GAS in abs_codes or ABS_BRAKE in abs_codes:
        return LAYOUT_BLUETOOTH
    return LAYOUT_USB
