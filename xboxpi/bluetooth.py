"""bluetoothctl helpers.

The key detail: pair, trust and connect inside ONE bluetoothctl session with a
NoInputNoOutput agent registered as default. Separate one-shot commands pair
the controller but often don't store a bond, and BlueZ then refuses its HID
connection ("Rejected connection from !bonded device").
"""

from __future__ import annotations

import queue
import re
import subprocess
import threading
import time

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x01|\x02")
MAC = r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}"
MICROSOFT = "045E"

# Xbox controller product ids (vendor 045E). Classic-Bluetooth firmware on the
# One S reports a HID descriptor older Linux kernels can't parse; the BLE
# firmware (Xbox Accessories update) works.
CLASSIC_FIRMWARE = {"02E0": "Xbox One S (old firmware)", "02FD": "Xbox One S (old firmware)",
                    "0B05": "Elite Series 2 (old firmware)"}
BLE_FIRMWARE = {"0B20": "Xbox One S", "0B13": "Xbox Series X|S", "0B22": "Elite Series 2"}


def run(*args: str, timeout: float = 15) -> str:
    out = subprocess.run(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout)
    return ANSI.sub("", out.stdout)


def devices() -> dict[str, str]:
    """MAC -> name of every device BlueZ knows about."""
    found = {}
    for line in run("devices").splitlines():
        m = re.search(rf"Device ({MAC}) (.+)", line)
        if m:
            found[m.group(1)] = m.group(2).strip()
    return found


def info(mac: str) -> dict[str, str]:
    fields = {}
    for line in run("info", mac).splitlines():
        key, sep, value = line.strip().partition(": ")
        if sep and key not in fields:
            fields[key] = value.strip()
    return fields


def product_id(fields: dict[str, str]) -> str | None:
    """'0B20' from Modalias 'usb:v045Ep0B20d0523'."""
    m = re.search(r"v045Ep([0-9A-F]{4})", fields.get("Modalias", ""), re.I)
    return m.group(1).upper() if m else None


def remove(mac: str) -> None:
    run("remove", mac)


class _Session:
    """An interactive bluetoothctl whose output we can wait on."""

    def __init__(self):
        self.proc = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.lines: queue.Queue[str] = queue.Queue()
        self.seen: list[str] = []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in self.proc.stdout:
            self.lines.put(ANSI.sub("", line))

    def say(self, command: str) -> None:
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def wait(self, pattern: str, timeout: float) -> re.Match | None:
        rx = re.compile(pattern)
        for line in self.seen:
            if m := rx.search(line):
                return m
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.lines.get(timeout=0.5)
            except queue.Empty:
                continue
            self.seen.append(line)
            if m := rx.search(line):
                return m
        return None

    def drain(self, seconds: float) -> None:
        """Collect output for `seconds` without waiting on anything in particular."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                self.seen.append(self.lines.get(timeout=0.2))
            except queue.Empty:
                pass

    def close(self) -> None:
        try:
            self.say("quit")
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.proc.kill()


def pair(name: str = "Xbox Wireless Controller", timeout: float = 90, mac: str | None = None,
         log=print) -> str | None:
    """Scan for `name` (put the controller in pairing mode first), then pair,
    bond, connect and trust it. Pass `mac` to pin one controller. Returns its
    MAC, or None if it never appeared or did not check out."""
    s = _Session()
    try:
        for cmd in ("power on", "agent NoInputNoOutput", "default-agent", "pairable on", "scan on"):
            s.say(cmd)
        log(f"scanning for '{name}' (hold the pair button until the logo flashes fast) ...")
        if mac:
            found = s.wait(rf"Device ({re.escape(mac.upper())})\b", timeout)
        else:
            found = s.wait(rf"Device ({MAC}) {re.escape(name)}", timeout)
        if not found:
            log("not found")
            return None
        if not mac:
            # Anyone nearby can advertise this name. If more than one device
            # does, don't guess: make the user pick with --mac.
            s.drain(4)
            matches = candidates(s.seen, name)
            if len(matches) > 1:
                log(f"several devices are called '{name}': {', '.join(sorted(matches))}. "
                    "Run again with --mac <address> to pick yours.")
                return None
        mac = found.group(1)
        log(f"found {mac}, pairing ...")
        s.say("scan off")
        s.say(f"pair {mac}")
        if not s.wait(r"Pairing successful|AlreadyExists", 30):
            log("pairing did not complete")
            return None
        s.say(f"connect {mac}")
        s.wait(r"Connection successful|Failed to connect", 20)
        # Only trust it (auto-reconnect) once it identifies as a Microsoft device.
        vendor = vendor_id(info(mac))
        if vendor and vendor != MICROSOFT:
            log(f"{mac} reports vendor {vendor}, not Microsoft ({MICROSOFT}); removing it")
            s.say(f"remove {mac}")
            return None
        if not vendor:
            log("warning: could not read the vendor id; check `xboxpi doctor`")
        s.say(f"trust {mac}")
        s.wait(r"trust succeeded", 5)
        return mac
    finally:
        s.say("scan off")
        s.say("pairable off")
        s.close()


def candidates(lines: list[str], name: str) -> set[str]:
    """MACs of every discovered device advertising `name`."""
    rx = re.compile(rf"Device ({MAC}) {re.escape(name)}\s*$")
    return {m.group(1) for line in lines if (m := rx.search(line.strip()))}


def vendor_id(fields: dict[str, str]) -> str | None:
    """'045E' from Modalias 'usb:v045Ep0B20d0523'."""
    m = re.search(r"v([0-9A-F]{4})p", fields.get("Modalias", ""), re.I)
    return m.group(1).upper() if m else None
