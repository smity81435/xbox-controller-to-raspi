"""Print what the controller does. Run: python examples/basic.py"""

from xboxpi import Axis, Button, Gamepad

pad = Gamepad()


@pad.on_connect
def connected(name):
    print(f"connected: {name}")


@pad.on_press(Button.A)
def a():
    print("A pressed")


@pad.on_press(Button.DPAD_LEFT)
def left():
    print("d-pad left")


@pad.on_hold(Button.MENU, seconds=3)
def menu_held():
    print("menu held 3 s, rumbling")
    pad.rumble(500)


@pad.on_axis
def moved(axis, value):
    if axis in (Axis.LT, Axis.RT) or abs(value) > 0.5:
        print(f"{axis.value}: {value:+.2f}")


pad.run()
