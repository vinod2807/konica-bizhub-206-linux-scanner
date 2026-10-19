#!/usr/bin/env python3
"""Sequenced USB session for the Konica Minolta bizhub 206 scanner channel.

Project: konica-scanner-re (see KONICA_SCANNER_RE_INSTRUCTIONS.md)

Safety:
  * Claims interface 0 only.
  * Never detaches usblp / never touches interface 1 (print path).
  * Never resets the device.
  * Every write is bounded by MAX_WRITE.

Sequence tokens (comma-separated or repeated arguments):
  wp:<hex>   write <hex>, zero-padded to 64 bytes (scanner command block)
  w:<hex>    write <hex> verbatim
  r:<n>      read up to n bytes from bulk IN 0x85
  r84:<n>    read up to n bytes from bulk IN 0x84
  i:<n>      read up to n bytes from interrupt IN 0x87
  s:<ms>     sleep

Example:
  usb_session.py 'wp:030c0d0100050200000000000000' 'wp:030b08' 'r:8'
"""
import argparse
import sys
import time

import usb.core
import usb.util

VID, PID = 0x132B, 0x232B
EP_OUT = 0x03
EP_CMD_IN = 0x85
EP_DATA_IN = 0x84
EP_INT_IN = 0x87
MAX_WRITE = 8192
BLOCK = 64


def hx(data):
    return " ".join(f"{b:02x}" for b in data)


def parse_hex(spec):
    return bytes.fromhex(spec.replace(" ", "").replace("0x", ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tokens", nargs="+", help="sequence tokens (see docstring)")
    ap.add_argument("--timeout", type=int, default=3000,
                    help="per-read timeout in ms (default 3000)")
    args = ap.parse_args()

    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit("device 132b:232b not found")
    print(f"device: bus={dev.bus} addr={dev.address} "
          f"idVendor={dev.idVendor:#06x} idProduct={dev.idProduct:#06x}")

    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    print(f"interface 0: class={intf.bInterfaceClass:#04x} "
          f"subclass={intf.bInterfaceSubClass:#04x} "
          f"protocol={intf.bInterfaceProtocol:#04x}")

    try:
        if dev.is_kernel_driver_active(0):
            sys.exit("kernel driver active on interface 0; refusing to detach")
    except NotImplementedError:
        pass

    usb.util.claim_interface(dev, 0)
    try:
        for raw in args.tokens:
            for token in raw.split(","):
                token = token.strip()
                if not token:
                    continue
                if token.startswith("s:"):
                    ms = int(token[2:])
                    print(f"sleep {ms} ms")
                    time.sleep(ms / 1000.0)
                elif token.startswith("wp:") or token.startswith("w:"):
                    pad = token.startswith("wp:")
                    spec = token.split(":", 1)[1]
                    payload = parse_hex(spec)
                    if pad:
                        if len(payload) > BLOCK:
                            sys.exit(f"padded payload {len(payload)} > {BLOCK}")
                        payload = payload.ljust(BLOCK, b"\x00")
                    if not payload:
                        sys.exit("empty write")
                    if len(payload) > MAX_WRITE:
                        sys.exit(f"write {len(payload)} exceeds MAX_WRITE")
                    print(f"OUT {EP_OUT:#04x} <= {len(payload)}: {hx(payload)}")
                    written = dev.write(EP_OUT, payload, timeout=1000)
                    print(f"  wrote {written}")
                elif token.startswith("r:") or token.startswith("r84:") \
                        or token.startswith("i:"):
                    kind, val = token.split(":", 1)
                    n = int(val)
                    ep = {"r": EP_CMD_IN, "r84": EP_DATA_IN,
                          "i": EP_INT_IN}[kind]
                    try:
                        data = dev.read(ep, n, timeout=args.timeout)
                        print(f"IN  {ep:#04x} => {len(data)}: {hx(bytes(data))}")
                    except usb.core.USBTimeoutError:
                        print(f"IN  {ep:#04x} => timeout after "
                              f"{args.timeout} ms")
                    except usb.core.USBError as exc:
                        print(f"IN  {ep:#04x} => error: {exc}")
                else:
                    sys.exit(f"unknown token: {token!r}")
    finally:
        usb.util.release_interface(dev, 0)
        print("interface 0 released")


if __name__ == "__main__":
    main()
