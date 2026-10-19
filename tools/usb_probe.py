#!/usr/bin/env python3
"""One-shot USB probe for the Konica Minolta bizhub 206 scanner channel.

Project: konica-scanner-re (see KONICA_SCANNER_RE_INSTRUCTIONS.md)

Safety contract:
  * Claims interface 0 only (vendor-specific scanner channel).
  * Never detaches usblp from interface 1 (print path).
  * Never resets the device.
  * Writes the given payload(s) verbatim (one USB transfer per payload), then
    makes one read attempt per IN endpoint. No retry loops, no polling.

Usage:
  usb_probe.py '1b 45'            # raw ESC E
  usb_probe.py --read-only        # just listen, do not write
  usb_probe.py '02 00 00 00 0e 00 00 00 01 00 00 00 1b 45'   # 12-byte hdr + ESC E
  usb_probe.py '<call>' '<request>'                            # call + request packet
"""
import argparse
import sys
import time

import usb.core
import usb.util

VID, PID = 0x132B, 0x232B
EP_OUT = 0x03
EP_BULK_IN = (0x84, 0x85)
EP_INT_IN = 0x87

# Do not exceed this on any single write (spec safety rule).
MAX_WRITE = 8192


def hx(data):
    return " ".join(f"{b:02x}" for b in data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("payloads", nargs="*", default=[],
                    help="hex byte string(s) to write, one USB transfer each, "
                         "e.g. '1b 45'")
    ap.add_argument("--read-only", action="store_true",
                    help="do not write; only listen on IN endpoints")
    ap.add_argument("--timeout", type=int, default=2000,
                    help="per-endpoint IN timeout in ms (default 2000)")
    args = ap.parse_args()

    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit("device 132b:232b not found")
    print(f"device: bus={dev.bus} addr={dev.address} "
          f"idVendor={dev.idVendor:#06x} idProduct={dev.idProduct:#06x}")

    try:
        cfg = dev.get_active_configuration()
    except usb.core.USBError as exc:
        sys.exit(f"no active configuration: {exc}")
    intf = cfg[(0, 0)]
    print(f"interface 0: class={intf.bInterfaceClass:#04x} "
          f"subclass={intf.bInterfaceSubClass:#04x} "
          f"protocol={intf.bInterfaceProtocol:#04x}")

    try:
        kernel_driver = dev.is_kernel_driver_active(0)
    except NotImplementedError:
        kernel_driver = False
    if kernel_driver:
        sys.exit("kernel driver is active on interface 0; refusing to detach it")

    usb.util.claim_interface(dev, 0)
    try:
        if not args.read_only:
            if not args.payloads:
                sys.exit("no payloads given (use --read-only to only listen)")
            for spec in args.payloads:
                payload = bytes.fromhex(spec.replace(" ", "").replace("0x", ""))
                if not payload:
                    sys.exit(f"empty payload: {spec!r}")
                if len(payload) > MAX_WRITE:
                    sys.exit(f"payload {len(payload)} bytes exceeds "
                             f"MAX_WRITE={MAX_WRITE}")
                print(f"OUT {EP_OUT:#04x} <= {len(payload)} bytes: {hx(payload)}")
                written = dev.write(EP_OUT, payload, timeout=1000)
                print(f"wrote {written} bytes")
                time.sleep(0.2)
        else:
            print("read-only mode: not writing anything")

        time.sleep(0.3)

        for ep in EP_BULK_IN:
            try:
                data = dev.read(ep, 4096, timeout=args.timeout)
                print(f"IN  {ep:#04x} => {len(data)} bytes: {hx(bytes(data))}")
            except usb.core.USBTimeoutError:
                print(f"IN  {ep:#04x} => timeout after {args.timeout} ms")
            except usb.core.USBError as exc:
                print(f"IN  {ep:#04x} => error: {exc}")

        try:
            data = dev.read(EP_INT_IN, 64, timeout=args.timeout)
            print(f"INT {EP_INT_IN:#04x} => {len(data)} bytes: {hx(bytes(data))}")
        except usb.core.USBTimeoutError:
            print(f"INT {EP_INT_IN:#04x} => timeout after {args.timeout} ms")
        except usb.core.USBError as exc:
            print(f"INT {EP_INT_IN:#04x} => error: {exc}")
    finally:
        usb.util.release_interface(dev, 0)
        print("interface 0 released")


if __name__ == "__main__":
    main()
