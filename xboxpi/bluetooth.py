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

    def close(self) -> None:
        try:
            self.say("quit")
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.proc.kill()


def pair(name: str = "Xbox Wireless Controller", timeout: float = 90, log=print) -> str | None:
    """Scan for `name` (put the controller in pairing mode first), then pair,
    bond, trust and connect it. Returns its MAC, or None if it never appeared."""
    s = _Session()
    try:
        for cmd in ("power on", "agent NoInputNoOutput", "default-agent", "pairable on", "scan on"):
            s.say(cmd)
        log(f"scanning for '{name}' (hold the pair button until the logo flashes fast) ...")
        m = s.wait(rf"Device ({MAC}) {re.escape(name)}", timeout)
        if not m:
            log("not found")
            return None
        mac = m.group(1)
        log(f"found {mac}, pairing ...")
        s.say("scan off")
        s.say(f"pair {mac}")
        if not s.wait(r"Pairing successful|AlreadyExists", 30):
            log("pairing did not complete")
        s.say(f"trust {mac}")
        s.say(f"connect {mac}")
        s.wait(r"Connection successful|Failed to connect", 20)
        return mac
    finally:
        s.close()
