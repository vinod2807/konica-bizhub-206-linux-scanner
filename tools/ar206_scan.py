#!/usr/bin/env python3
"""Scan from a Konica Minolta bizhub 206 over USB.

This drives the scanner directly with the AR206.DS USB command set; no
Windows driver, TWAIN layer, or SANE backend is involved.

Verified protocol (flatbed, A4, 300 dpi, mono):
    status     03 0d 0a                  -> 10 bytes
    params     03 0c 0d 00 00 00 + 13
    geometry   03 0b 08                  -> 8 bytes
    init       03 09 01                  -> 1 byte (0 = ok)
    set length 03 08 04 00 00 00 + len4 + 01   (this also starts the scan)
    read chunk 03 0e 04 00 00 00 + len4
                 -> 5-byte header on EP 0x85: status, avail_lo, avail_hi
                 -> avail bytes of payload on EP 0x85

Important: do NOT send 03 0a.  In AR206.DS that command is only issued on
the error/abort path; sending it after set-length stops the scan and no
image data is produced.

Also do NOT send 03 11 01 after a scan.  The DS only uses that command
from its TWAIN UI/session-close handlers; on this unit it resets the USB
session and leaves the bulk endpoints unresponsive until a power-cycle.

Safety: claims interface 0 only, never resets the device, and never touches
interface 1 / usblp.  If a transfer wedges, power-cycle the scanner.
"""

import argparse
import datetime
import os
import struct
import sys
import time
import zlib

import usb.core
import usb.util

VID, PID = 0x132B, 0x232B
EP_OUT = 0x03
EP_IN = 0x85
BLOCK = 64
MAX_CHUNK = 65024

# Window is expressed in 600-dpi units by the driver.
PAPERS = {
    "a4": (2, 4960, 7015),
    "a3": (0, 7015, 9921),
}
DPI_CODE = {150: 0, 300: 1, 600: 2}
DPI_INDEX = 5


class ScanError(Exception):
    pass


def _cmd(*parts):
    data = b"".join(parts)
    if len(data) > BLOCK:
        raise ValueError(f"command {len(data)} > {BLOCK}")
    return data.ljust(BLOCK, b"\x00")


def _write(dev, data, timeout=3000):
    dev.write(EP_OUT, data, timeout=timeout)


def _read(dev, n, timeout=10000):
    return bytes(dev.read(EP_IN, n, timeout=timeout))


def _read_exact(dev, n, timeout=10000):
    buf = bytearray()
    while len(buf) < n:
        try:
            part = _read(dev, n - len(buf), timeout=timeout)
        except usb.core.USBTimeoutError as exc:
            raise ScanError(
                f"timeout reading {len(buf)}/{n} bytes; "
                "if the scanner is unresponsive, power-cycle it"
            ) from exc
        if not part:
            break
        buf.extend(part)
    return bytes(buf)


def build_params(paper, dpi, source):
    code, win_w, win_h = PAPERS[paper]
    p = bytearray(13)
    p[0] = DPI_CODE[dpi]
    p[1] = 0                  # mono
    p[2] = DPI_INDEX
    p[3] = code
    p[4:8] = b"\x00\x00\x00\x00"
    p[8:10] = win_w.to_bytes(2, "little")
    p[10:12] = win_h.to_bytes(2, "little")
    # 0 = flatbed.  ADF is not yet validated; keep it opt-in.
    p[12] = 0 if source == "flatbed" else 2
    return bytes(p)


def scan(dev, paper="a4", dpi=300, source="flatbed", progress=True,
         close=False):
    params = build_params(paper, dpi, source)

    _write(dev, _cmd(b"\x03\x0d\x0a"))
    status = _read(dev, 10)
    if progress:
        print(f"status: {status.hex(' ')}")

    _write(dev, _cmd(b"\x03\x0c\x0d\x00\x00\x00", params))
    time.sleep(0.05)

    _write(dev, _cmd(b"\x03\x0b\x08"))
    geom = _read(dev, 8)
    line_w = geom[0] | (geom[1] << 8)
    height = geom[2] | (geom[3] << 8)
    win_w = geom[4] | (geom[5] << 8)
    win_h = geom[6] | (geom[7] << 8)
    if progress:
        print(f"geometry: line={line_w} height={height} "
              f"window={win_w}x{win_h}")
    if line_w == 0 or height == 0 or win_w == 0 or win_h == 0:
        raise ScanError(f"parameter block rejected (geometry {geom.hex(' ')})")

    _write(dev, _cmd(b"\x03\x09\x01"))
    init = _read(dev, 1)
    if init != b"\x00":
        raise ScanError(f"init failed: {init.hex(' ')}")

    row_bytes = (line_w + 7) // 8          # mono
    length = row_bytes * height
    if progress:
        print(f"image: {row_bytes} bytes/row x {height} = {length} bytes")

    _write(dev, _cmd(b"\x03\x08\x04\x00\x00\x00",
                     length.to_bytes(4, "little"), b"\x01"))
    time.sleep(0.8)                        # let the carriage/lamp start

    raw = bytearray()
    first = True
    while len(raw) < length:
        want = min(MAX_CHUNK, length - len(raw))
        _write(dev, _cmd(b"\x03\x0e\x04\x00\x00\x00",
                         want.to_bytes(4, "little")))
        hdr = _read_exact(dev, 5, timeout=15000 if first else 10000)
        first = False
        if len(hdr) != 5:
            raise ScanError(f"short data header: {hdr.hex(' ')}")
        if hdr[0] != 0:
            raise ScanError(f"read chunk status {hdr[0]:#04x}")
        avail = hdr[1] | (hdr[2] << 8)
        if avail == 0:
            break
        take = min(avail, length - len(raw))
        raw.extend(_read_exact(dev, take, timeout=10000))
        if progress:
            pct = 100 * len(raw) / length
            print(f"\r  {len(raw):>8}/{length} bytes ({pct:5.1f}%)",
                  end="", flush=True)
    if progress:
        print()
    if len(raw) != length:
        raise ScanError(f"short image: got {len(raw)} of {length} bytes")

    # The DS's normal scan path does not send 03 11 01; that command is
    # only issued from its TWAIN UI/session-close handlers.  On this unit
    # it resets the USB session and leaves the bulk endpoints unresponsive
    # until a power-cycle, so keep it opt-in for diagnostics only.
    if close:
        try:
            _write(dev, _cmd(b"\x03\x11\x01"))
            _read(dev, 1, timeout=3000)
        except usb.core.USBError:
            pass

    return bytes(raw), (line_w, height, win_w, win_h)


def expand_mono(raw, row_bytes, width, height, rotate=0):
    """Expand 1-bit MSB-first (1=black) pixels to 8-bit gray, rotated."""
    table = [bytes(0 if (b & (0x80 >> i)) else 255 for i in range(8))
             for b in range(256)]
    crop_bytes = (width + 7) // 8

    if rotate in (0, 180):
        rows = []
        for y in range(height):
            row = raw[y * row_bytes:y * row_bytes + crop_bytes]
            px = b"".join(table[b] for b in row)[:width]
            rows.append(px)
        if rotate == 180:
            rows = [r[::-1] for r in reversed(rows)]
        return width, height, b"".join(rows)

    # 90 / 270: build each source column once, then emit output rows.
    cols = []
    for x in range(width):
        bx, sh = divmod(x, 8)
        col = bytearray(height)
        for y in range(height):
            col[y] = 0 if (raw[y * row_bytes + bx] & (0x80 >> sh)) else 255
        cols.append(col)

    out = bytearray()
    if rotate == 90:          # clockwise
        for x in range(width):
            out.extend(cols[x][::-1])
    else:                     # 270, counter-clockwise
        for x in range(width - 1, -1, -1):
            out.extend(cols[x])
    return height, width, bytes(out)


def write_png(path, width, height, pix):
    rows = b"".join(b"\x00" + bytes(pix[y * width:(y + 1) * width])
                    for y in range(height))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                      8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def write_pdf(path, width, height, pix, dpi=300):
    page_w = width / dpi * 72.0
    page_h = height / dpi * 72.0
    img = zlib.compress(bytes(pix), 9)
    content = (f"q\n{page_w:.4f} 0 0 {page_h:.4f} "
               f"0 0 cm\n/Im0 Do\nQ\n").encode()

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
         f"{page_w:.4f} {page_h:.4f}] "
         f"/Resources << /XObject << /Im0 4 0 R >> >> "
         f"/Contents 5 0 R >>").encode(),
        (f"<< /Type /XObject /Subtype /Image /Width {width} "
         f"/Height {height} /ColorSpace /DeviceGray "
         f"/BitsPerComponent 8 /Filter /FlateDecode "
         f"/Length {len(img)} >>").encode() + b"\nstream\n" + img +
        b"\nendstream",
        f"<< /Length {len(content)} >>".encode() + b"\nstream\n" +
        content + b"endstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n%\xff\xff\xff\xff\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objs) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (f"trailer\n<< /Size {len(objs) + 1} "
            f"/Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    with open(path, "wb") as f:
        f.write(pdf)


def main():
    ap = argparse.ArgumentParser(
        description="Scan from a Konica Minolta bizhub 206 over USB")
    ap.add_argument("--paper", choices=("a4", "a3"), default="a4")
    ap.add_argument("--dpi", type=int, choices=(150, 300, 600), default=300)
    ap.add_argument("--source", choices=("flatbed", "adf"), default="flatbed")
    ap.add_argument("--rotate", type=int, choices=(0, 90, 180, 270),
                    default=0, help="rotate output clockwise (default 0)")
    ap.add_argument("--out", default=None, help="PNG output path")
    ap.add_argument("--pdf", default=None, help="optional PDF output path")
    ap.add_argument("--raw", default=None, help="optional raw dump path")
    ap.add_argument("--close", action="store_true",
                    help="send 03 11 01 after scanning (resets the USB "
                         "session on this unit; for diagnostics only)")
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = args.out or f"scan-{stamp}.png"

    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        sys.exit("device 132b:232b not found")
    try:
        if dev.is_kernel_driver_active(0):
            sys.exit("kernel driver active on interface 0; refusing to detach")
    except NotImplementedError:
        pass

    usb.util.claim_interface(dev, 0)
    try:
        raw, (line_w, height, win_w, win_h) = scan(
            dev, args.paper, args.dpi, args.source, close=args.close)
    finally:
        usb.util.release_interface(dev, 0)

    if args.raw:
        with open(args.raw, "wb") as f:
            f.write(raw)

    row_bytes = (line_w + 7) // 8
    w, h, pix = expand_mono(raw, row_bytes, win_w, height, args.rotate)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    write_png(out, w, h, pix)
    print(f"wrote {out} ({w}x{h})")
    if args.pdf:
        os.makedirs(os.path.dirname(os.path.abspath(args.pdf)), exist_ok=True)
        write_pdf(args.pdf, w, h, pix, dpi=args.dpi)
        print(f"wrote {args.pdf}")


if __name__ == "__main__":
    main()
