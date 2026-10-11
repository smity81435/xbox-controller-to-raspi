"""`xboxpi doctor`: check every step that broke for us, and say how to fix it."""

from __future__ import annotations

import grp
import os
import subprocess
from dataclasses import dataclass

from . import bluetooth


@dataclass
class Check:
    name: str
    ok: bool | None  # None = could not tell
    detail: str = ""
    fix: str = ""


def _sh(*cmd: str) -> tuple[int, str]:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return out.returncode, out.stdout + out.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def controller_check(mac: str, name: str, fields: dict[str, str]) -> list[Check]:
    """Checks for one paired controller, from `bluetoothctl info` fields."""
    checks = []
    pid = bluetooth.product_id(fields)
    if pid in bluetooth.CLASSIC_FIRMWARE:
        checks.append(Check(
            f"{name} firmware", False, f"product id {pid}: {bluetooth.CLASSIC_FIRMWARE[pid]}",
            "Update it: Xbox Accessories app on Windows or an Xbox, over a USB cable. The new firmware "
            "uses Bluetooth LE (id 0B20), which Linux handles. Then `xboxpi pair` again.",
        ))
    elif pid in bluetooth.BLE_FIRMWARE:
        checks.append(Check(f"{name} firmware", True, f"product id {pid}: {bluetooth.BLE_FIRMWARE[pid]} (BLE)"))
    elif pid:
        checks.append(Check(f"{name} firmware", None, f"product id {pid} (not in our list)"))
    bonded = fields.get("Bonded") == "yes"
    checks.append(Check(f"{name} bonded", bonded, f"{mac} paired={fields.get('Paired')} bonded={fields.get('Bonded')}",
                        "" if bonded else f"`bluetoothctl remove {mac}` then `xboxpi pair`"))
    checks.append(Check(f"{name} trusted", fields.get("Trusted") == "yes", "",
                        f"`bluetoothctl trust {mac}` (lets it reconnect by itself)"))
    connected = fields.get("Connected") == "yes"
    checks.append(Check(f"{name} connected", connected, "",
                        "" if connected else "press the Xbox button; it reconnects to the last host"))
    return checks


def run_checks() -> list[Check]:
    checks: list[Check] = []

    try:
        import evdev  # noqa: F401
        checks.append(Check("evdev installed", True))
    except ImportError:
        checks.append(Check("evdev installed", False, fix="pip install evdev (Linux only)"))
        evdev = None

    code, out = _sh("systemctl", "is-active", "bluetooth")
    checks.append(Check("bluetooth service", out.strip() == "active", out.strip(),
                        "sudo systemctl enable --now bluetooth"))

    code, out = _sh("rfkill", "list", "bluetooth")
    if code == 0:
        blocked = "blocked: yes" in out.lower()
        checks.append(Check("bluetooth not rfkill-blocked", not blocked, "", "sudo rfkill unblock bluetooth"))

    powered = "Powered: yes" in bluetooth.run("show")
    checks.append(Check("adapter powered", powered, "", "bluetoothctl power on"))

    try:
        gid = grp.getgrnam("input").gr_gid
        in_group = os.geteuid() == 0 or gid in os.getgroups()
        checks.append(Check("can read /dev/input (input group)", in_group, "",
                            "sudo usermod -aG input $USER, then log out and in "
                            "(systemd services: SupplementaryGroups=input)"))
    except KeyError:
        checks.append(Check("can read /dev/input (input group)", None, "no 'input' group"))

    pads = {mac: name for mac, name in bluetooth.devices().items() if "xbox" in name.lower()}
    if not pads:
        checks.append(Check("paired Xbox controller", False, "none paired", "`xboxpi pair`"))
    for mac, name in pads.items():
        checks.extend(controller_check(mac, name, bluetooth.info(mac)))

    found: list[str] = []
    if evdev is not None:
        names = []
        for path in evdev.list_devices():
            try:
                names.append(evdev.InputDevice(path).name)
            except OSError:
                pass
        found = [n for n in names if "xbox" in n.lower()]
        checks.append(Check("input device created", bool(found), ", ".join(found) or "none",
                            "" if found else "connected but no input device: check firmware above and "
                            "`dmesg | grep -i microsoft` for 'parse failed'"))

    # Only worth digging through the kernel log when the pad produced no input
    # device; old "parse failed" lines linger after a firmware update fixes it.
    code, out = _sh("dmesg") if not found else (1, "")
    if code == 0:
        bad = [line for line in out.splitlines() if "045E" in line.upper() and "parse failed" in line]
        if bad:
            checks.append(Check("kernel parsed the controller", False, bad[-1].strip(),
                                "old controller firmware: update it with Xbox Accessories"))
    return checks


def report(checks: list[Check]) -> int:
    mark = {True: "OK  ", False: "FAIL", None: "??  "}
    for c in checks:
        line = f"[{mark[c.ok]}] {c.name}"
        if c.detail:
            line += f": {c.detail}"
        print(line)
        if c.ok is False and c.fix:
            print(f"       fix: {c.fix}")
    return 0 if all(c.ok is not False for c in checks) else 1
