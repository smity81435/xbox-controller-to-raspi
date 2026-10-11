from xboxpi import Axis, Button, Dispatcher
from xboxpi.bluetooth import candidates, product_id, vendor_id
from xboxpi.buttons import (ABS_BRAKE, ABS_GAS, ABS_HAT0X, ABS_RX, ABS_X, ABS_Z, EV_ABS, EV_KEY,
                            LAYOUT_BLUETOOTH, LAYOUT_USB, layout_for)
from xboxpi.doctor import controller_check


def test_press_release_and_any():
    d = Dispatcher()
    log = []
    d.on_press(Button.A)(lambda: log.append("A down"))
    d.on_release(Button.A)(lambda: log.append("A up"))
    d.on_any(lambda b, down: log.append((b, down)))
    d.feed(EV_KEY, Button.A, 1, 0)
    d.feed(EV_KEY, Button.A, 2, 0)  # autorepeat ignored
    d.feed(EV_KEY, Button.A, 0, 1)
    assert log == [(Button.A, True), "A down", (Button.A, False), "A up"]


def test_hold_fires_once_with_progress_and_cancel():
    d = Dispatcher()
    fired, progress = [], []
    d.on_hold(Button.A, seconds=2, progress=progress.append)(lambda: fired.append(1))
    d.feed(EV_KEY, Button.A, 1, 10.0)
    d.tick(11.0)
    assert progress == [0.5] and not fired
    d.tick(12.0)
    d.tick(13.0)
    assert fired == [1] and progress[-1] is None
    d.feed(EV_KEY, Button.A, 0, 13.5)
    d.feed(EV_KEY, Button.A, 1, 20.0)
    d.feed(EV_KEY, Button.A, 0, 20.5)  # let go early
    d.tick(25.0)
    assert fired == [1] and progress[-1] is None


def test_dpad_hat_becomes_buttons():
    d = Dispatcher()
    log = []
    d.on_any(lambda b, down: log.append((b.name, down)))
    d.feed(EV_ABS, ABS_HAT0X, -1, 0)
    d.feed(EV_ABS, ABS_HAT0X, 1, 0)
    d.feed(EV_ABS, ABS_HAT0X, 0, 0)
    assert log == [("DPAD_LEFT", True), ("DPAD_LEFT", False), ("DPAD_RIGHT", True), ("DPAD_RIGHT", False)]


def test_axes_normalise_with_deadzone_and_layout():
    d = Dispatcher(deadzone=0.1)
    seen = {}
    d.on_axis(lambda a, v: seen.__setitem__(a, v))
    d.set_device({ABS_X, ABS_Z, ABS_GAS, ABS_BRAKE}, {ABS_X: (0, 65535), ABS_Z: (0, 65535), ABS_GAS: (0, 1023)})
    d.feed(EV_ABS, ABS_X, 65535, 0)
    d.feed(EV_ABS, ABS_Z, 32768, 0)  # centre, inside the deadzone
    d.feed(EV_ABS, ABS_GAS, 1023, 0)
    assert seen == {Axis.LEFT_X: 1.0, Axis.RIGHT_X: 0.0, Axis.RT: 1.0}


def test_layout_detection():
    assert layout_for({ABS_X, ABS_RX, ABS_Z}) is LAYOUT_USB
    assert layout_for({ABS_X, ABS_Z, ABS_GAS, ABS_BRAKE}) is LAYOUT_BLUETOOTH


def test_firmware_detection():
    assert product_id({"Modalias": "usb:v045Ep0B20d0523"}) == "0B20"
    old = controller_check("AA:BB:CC:DD:EE:FF", "Xbox Wireless Controller",
                           {"Modalias": "usb:v045Ep02FDd0903", "Bonded": "no", "Paired": "yes"})
    assert old[0].ok is False and "Xbox Accessories" in old[0].fix
    assert old[1].ok is False  # not bonded
    new = controller_check("AA:BB:CC:DD:EE:FF", "Xbox Wireless Controller",
                           {"Modalias": "usb:v045Ep0B20d0523", "Bonded": "yes", "Trusted": "yes", "Connected": "yes"})
    assert all(c.ok for c in new)


def test_pairing_spots_lookalikes_and_checks_vendor():
    lines = [
        "[NEW] Device 5C:BA:37:F6:6E:4D Xbox Wireless Controller",
        "[CHG] Device 5C:BA:37:F6:6E:4D RSSI: -60",
        "[NEW] Device 11:22:33:44:55:66 Xbox Wireless Controller",
        "[NEW] Device AA:BB:CC:DD:EE:FF Xbox Wireless Controller Pro",
    ]
    assert candidates(lines, "Xbox Wireless Controller") == {"5C:BA:37:F6:6E:4D", "11:22:33:44:55:66"}
    assert vendor_id({"Modalias": "usb:v045Ep0B20d0523"}) == "045E"
    assert vendor_id({"Modalias": "usb:v1D6Bp0246d0540"}) == "1D6B"
    assert vendor_id({}) is None
