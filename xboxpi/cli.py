"""xboxpi command line: pair, doctor, test."""

from __future__ import annotations

import argparse
import logging
import sys


def cmd_pair(args) -> int:
    from . import bluetooth

    mac = bluetooth.pair(args.name, timeout=args.timeout, mac=args.mac)
    if not mac:
        return 1
    fields = bluetooth.info(mac)
    print(f"{mac}: paired={fields.get('Paired')} bonded={fields.get('Bonded')} "
          f"trusted={fields.get('Trusted')} connected={fields.get('Connected')}")
    pid = bluetooth.product_id(fields)
    if pid in bluetooth.CLASSIC_FIRMWARE:
        print("warning: old controller firmware; Linux may not read its buttons. Run `xboxpi doctor`.")
    return 0 if fields.get("Bonded") == "yes" else 1


def cmd_doctor(args) -> int:
    from .doctor import report, run_checks

    return report(run_checks())


def cmd_test(args) -> int:
    from .buttons import Button
    from .gamepad import Gamepad

    pad = Gamepad()

    @pad.on_connect
    def connected(name):
        print(f"connected: {name}  (hold A for 2 s to rumble, Ctrl-C to quit)")
        pad.rumble(200)

    @pad.on_disconnect
    def gone():
        print("disconnected; waiting ...")

    @pad.on_any
    def button(b, down):
        print(f"{b.name:10} {'down' if down else 'up'}")

    @pad.on_axis
    def axis(a, value):
        if args.axes:
            print(f"{a.value:10} {value:+.2f}")

    def bar(fraction):
        if fraction is not None:
            print(f"hold A [{'#' * int(fraction * 20):20}]", end="\r", flush=True)

    @pad.on_hold(Button.A, seconds=2, progress=bar)
    def held():
        print("\nheld A for 2 s")
        pad.rumble(400)

    print("waiting for a controller ...")
    try:
        pad.run()
    except KeyboardInterrupt:
        pass
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="xboxpi", description="Xbox controllers on a Raspberry Pi")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pair", help="pair, bond and trust a controller in pairing mode")
    p.add_argument("--name", default="Xbox Wireless Controller", help="Bluetooth name to look for")
    p.add_argument("--timeout", type=float, default=90, help="seconds to scan")
    p.add_argument("--mac", help="pair only this controller address (recommended in busy places)")
    p.set_defaults(fn=cmd_pair)

    p = sub.add_parser("doctor", help="check Bluetooth, permissions, pairing and firmware")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("test", help="print button and stick events live")
    p.add_argument("--axes", action="store_true", help="also print stick and trigger movement")
    p.set_defaults(fn=cmd_test)

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
