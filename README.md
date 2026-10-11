# xbox-controller-to-raspi

Use an Xbox controller with a Raspberry Pi over Bluetooth (or USB), from Python.

Includes `xboxpi`, a small library and command-line tool that pairs the controller properly, checks for the usual problems, and gives you simple button callbacks.

Tested with an Xbox One S controller (model 1708, firmware 5.23) on a Raspberry Pi 3 B+ running Raspberry Pi OS 13 (64-bit).

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install git+https://github.com/smity81435/xbox-controller-to-raspi.git
```

Your user needs to be in the `input` group to read the controller:

```bash
sudo usermod -aG input $USER   # then log out and back in
```

## Pair the controller

1. Turn the controller on, then hold the small pair button on top until the Xbox logo flashes fast.
2. Run:

```bash
.venv/bin/xboxpi pair
```

Anyone nearby can advertise the same Bluetooth name, so `pair` refuses if it sees more than one, and only trusts a device that reports Microsoft as its maker. In a busy place, pin your controller with `--mac` (its address is shown by `xboxpi pair` or `bluetoothctl devices`).

3. Check everything:

```bash
.venv/bin/xboxpi doctor
.venv/bin/xboxpi test      # press buttons to see them
```

## Use it in Python

```python
from xboxpi import Button, Gamepad

pad = Gamepad()

@pad.on_press(Button.A)
def a_pressed():
    print("A")

@pad.on_hold(Button.B, seconds=2)
def b_held():
    print("held B for 2 seconds")
    pad.rumble(300)

pad.run()   # or pad.start() to run in the background
```

The controller reconnects automatically if it sleeps or drops out. See `examples/basic.py` for sticks and the d-pad.

## If it doesn't work

| Problem | Fix |
|---|---|
| Connects, but no buttons show up. `dmesg` says `parse failed` | Old controller firmware. Update it with the **Xbox Accessories** app on Windows or an Xbox, over a USB cable, then pair again. |
| `Rejected connection from !bonded device` in `journalctl -u bluetooth` | The pairing didn't save. Run `bluetoothctl remove <MAC>`, then `xboxpi pair`. |
| Bluetooth is off on a fresh Pi | `sudo rfkill unblock bluetooth` then `bluetoothctl power on` |
| Permission denied on `/dev/input` | Add your user to the `input` group (above). For a systemd service, add `SupplementaryGroups=input`. |
| Controller turns itself off | Press the Xbox button; it reconnects to the Pi by itself once paired. |

Over USB (micro-USB cable) it works with no pairing at all.
