#!/usr/bin/env python3
"""Staged USB test for the Konica Minolta bizhub 206 scanner (AR206.DS protocol).

Safety:
  * Claims interface 0 only; never touches interface 1 / usblp.
  * Never resets the device.
  * `--stage geometry` stops after `03 0c` + `03 0b 08`, so a bad
    parameter block is detected before any scan/start command.
  * All writes are 64-byte command blocks.

Usage:
  ar206_test.py --stage geometry
  ar206_test.py --stage full --out probe/round13-scan.bin
  ar206_test.py --stage full --auto-ep --out probe/round13-scan.bin
  ar206_test.py --stage geometry --params 01000502000000006013671b00

Wire format for the 13-byte parameter block:
  03 0c 0d 00 00 00 <param0..param12>

The default parameter block is the 206 static template completed for A4:
  01 00 05 02 00 00 00 00 60 13 67 1b 00
  byte0  300 dpi code (0=150, 1=300, 2=600)
  byte1  0 = mono
  byte2  5 = default resolution index
  byte3  2 = A4
  bytes4-7   window left/top = 0
  bytes8-11  A4 window 4960 x 7015 (600-dpi units, LE)
  byte12 0 = flatbed / no ADF paper

Command responses (1/8/10 bytes) and image data (5-byte header +
payload) both arrive on bulk IN 0x85.  Bulk IN 0x84 never carried data.

The AR206 driver starts a scan with the trailing 0x01 of the set-length
command (03 08 04 ... 01).  It sends 03 0a only on its error/abort path,
so this tool does not send 03 0a unless --send-0a is given.
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
BLOCK = 64

DEFAULT_PARAMS = bytes.fromhex("01000502000000006013671b00")
assert len(DEFAULT_PARAMS) == 13, len(DEFAULT_PARAMS)


def hx(data):
    return " ".join(f"{b:02x}" for b in data)


def cmd(*parts):
    data = b"".join(parts)
    if len(data) > BLOCK:
        raise ValueError(f"command {len(data)} > {BLOCK}")
    return data.ljust(BLOCK, b"\x00")


def write64(dev, data, label):
    print(f"OUT <= {label}: {hx(data[:24])}{' ...' if len(data) > 24 else ''}")
    n = dev.write(EP_OUT, data, timeout=2000)
    print(f"    wrote {n}")


def preview(data, limit=32):
    s = hx(data[:limit])
    if len(data) > limit:
        s += f" ... ({len(data)} bytes)"
    return s


def read(dev, ep, n, label, timeout=3000):
    try:
        data = bytes(dev.read(ep, n, timeout=timeout))
        print(f"IN  => {label} [ep {ep:#04x}]: {len(data)}: {preview(data)}")
        return data
    except usb.core.USBTimeoutError:
        print(f"IN  => {label} [ep {ep:#04x}]: timeout after {timeout} ms")
        return None
    except usb.core.USBError as exc:
        print(f"IN  => {label} [ep {ep:#04x}]: error: {exc}")
        return None


def read_exact(dev, ep, n, label, timeout=5000):
    """Drain exactly n bytes, tolerating short bulk packets."""
    buf = bytearray()
    while len(buf) < n:
        try:
            part = bytes(dev.read(ep, n - len(buf), timeout=timeout))
        except usb.core.USBTimeoutError:
            print(f"IN  => {label} [ep {ep:#04x}]: timeout at "
                  f"{len(buf)}/{n} bytes")
            break
        except usb.core.USBError as exc:
            print(f"IN  => {label} [ep {ep:#04x}]: error at "
                  f"{len(buf)}/{n} bytes: {exc}")
            break
        if not part:
            break
        buf.extend(part)
    print(f"IN  => {label} [ep {ep:#04x}]: {len(buf)}/{n} bytes")
    return bytes(buf)


def le32(v):
    return v.to_bytes(4, "little")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("status", "geometry", "full"),
                    default="geometry")
    ap.add_argument("--params", default=DEFAULT_PARAMS.hex(),
                    help="13-byte parameter block as hex")
    ap.add_argument("--out", default="probe/round13-scan.bin")
    ap.add_argument("--chunk", type=int, default=65024,
                    help="read-data chunk size (default 65024, the DS max)")
    ap.add_argument("--max-chunks", type=int, default=28,
                    help="stop after this many data chunks (default 28)")
    ap.add_argument("--header-ep", type=lambda s: int(s, 0), default=EP_CMD_IN,
                    help="endpoint for the 5-byte data header (default 0x85)")
    ap.add_argument("--data-ep", type=lambda s: int(s, 0), default=None,
                    help="endpoint for payload (default: same as header)")
    ap.add_argument("--auto-ep", action="store_true",
                    help="try 0x84 first, then 0x85, for the header")
    ap.add_argument("--delay", type=float, default=0.3,
                    help="seconds to wait after set-length before reading (default 0.3)")
    ap.add_argument("--send-0a", action="store_true",
                    help="send 03 0a; the DS only does this on the error/abort path")
    ap.add_argument("--close", action="store_true",
                    help="send 03 11 01 after the scan; this resets the USB "
                         "session on this unit and requires a power-cycle")
    ap.add_argument("--read-cap", type=int, default=0,
                    help="cap each payload read to this many bytes (0 = no cap)")
    ap.add_argument("--intr-probe", action="store_true",
                    help="read 8 bytes from interrupt IN 0x87 after set-length")
    args = ap.parse_args()

    params = bytes.fromhex(args.params.replace(" ", ""))
    if len(params) != 13:
        sys.exit(f"params must be 13 bytes, got {len(params)}")

    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit("device 132b:232b not found")
    print(f"device: bus={dev.bus} addr={dev.address}")

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
        # 1. Status
        write64(dev, cmd(b"\x03\x0d\x0a"), "03 0d 0a (status)")
        status = read(dev, EP_CMD_IN, 10, "status")
        if status is None:
            sys.exit("status timed out; device may still be stalled")
        if args.stage == "status":
            return

        # 2. Set parameters (write only -- do NOT read).
        write64(dev, cmd(b"\x03\x0c\x0d\x00\x00\x00", params),
                "03 0c 0d 00 00 00 + 13 params")
        time.sleep(0.1)

        # 3. Geometry
        write64(dev, cmd(b"\x03\x0b\x08"), "03 0b 08 (geometry)")
        geom = read(dev, EP_CMD_IN, 8, "geometry")
        if geom is None:
            sys.exit("geometry timed out: parameter block likely rejected")

        width = geom[0] | (geom[1] << 8)
        height = geom[2] | (geom[3] << 8)
        print(f"geometry: width={width} height={height} raw={hx(geom)}")
        if width == 0 or height == 0:
            sys.exit("geometry is zero: parameter block not accepted")
        if args.stage == "geometry":
            return

        # 4. Init
        write64(dev, cmd(b"\x03\x09\x01"), "03 09 01 (init)")
        init = read(dev, EP_CMD_IN, 1, "init")
        if init is None:
            sys.exit("init timed out")

        # 5. Set image length. byte1 of the param block selects bytes/pixel.
        mode = params[1]
        if mode == 3:
            row_bytes = width * 3
        elif mode in (0, 1):
            row_bytes = (width + 7) // 8
        else:
            row_bytes = width
        length = row_bytes * height
        print(f"mode={mode} row_bytes={row_bytes} length={length}")

        write64(dev, cmd(b"\x03\x08\x04\x00\x00\x00", le32(length), b"\x01"),
                "03 08 04 (set length)")
        time.sleep(0.1)

        # 6. The AR206 DS does NOT send 03 0a on the success path: that
        #    command is only issued after setup returns -1 (abort path).
        #    The set-length command's trailing 0x01 is what starts the scan.
        if args.send_0a:
            write64(dev, cmd(b"\x03\x0a"), "03 0a (abort path)")
        time.sleep(args.delay)
        if args.intr_probe:
            read(dev, 0x87, 8, "interrupt after set-length", timeout=2000)

        # 7. Read data
        out = bytearray()
        for i in range(args.max_chunks):
            chunk = min(args.chunk, length - len(out))
            if chunk <= 0:
                break
            write64(dev, cmd(b"\x03\x0e\x04\x00\x00\x00", le32(chunk)),
                    f"03 0e 04 (read chunk {i}, {chunk} bytes)")

            if args.auto_ep:
                hdr = read(dev, 0x84, 5, f"chunk {i} header", timeout=2500)
                ep = 0x84
                if hdr is None:
                    hdr = read(dev, 0x85, 5, f"chunk {i} header", timeout=2500)
                    ep = 0x85
            else:
                ep = args.header_ep
                hdr = read(dev, ep, 5, f"chunk {i} header")
            if hdr is None:
                break
            if hdr[0] != 0:
                print(f"chunk {i}: status byte {hdr[0]:#04x}, stopping")
                break
            avail = hdr[1] | (hdr[2] << 8)
            print(f"chunk {i}: available={avail} header_ep={ep:#04x}")
            if avail == 0:
                break
            data_ep = args.data_ep if args.data_ep is not None else ep
            # Never read past the declared image length.
            want = min(avail, length - len(out))
            if args.read_cap:
                want = min(want, args.read_cap)
            data = read_exact(dev, data_ep, want, f"chunk {i} data",
                              timeout=8000)
            if not data:
                break
            out.extend(data)
            if len(data) < want:
                break
            time.sleep(0.02)

        print(f"received {len(out)} of expected {length} bytes")
        if out:
            with open(args.out, "wb") as f:
                f.write(out)
            print(f"wrote {args.out}")

        # 8. Close (opt-in only).  The normal scan path does not send this;
        #    on this unit it resets the USB session and wedges the bulk
        #    endpoints until a power-cycle.
        if args.close:
            try:
                write64(dev, cmd(b"\x03\x11\x01"), "03 11 01 (close)")
                read(dev, EP_CMD_IN, 1, "close")
            except usb.core.USBError as exc:
                print(f"close failed: {exc}")
    finally:
        usb.util.release_interface(dev, 0)
        print("interface 0 released")


if __name__ == "__main__":
    main()
