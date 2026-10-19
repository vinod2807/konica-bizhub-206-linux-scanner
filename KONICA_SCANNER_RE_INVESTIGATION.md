# Konica Minolta bizhub 206 – Linux Scanner Reverse Engineering

Investigation log for the project described in
`/home/vinod/Downloads/KONICA_SCANNER_RE_INSTRUCTIONS.md`.

Project root: `/home/vinod/konica-scanner-re`
Host: `alpine-jwm`, Alpine Linux v3.24, kernel 6.18.57-0-lts (x86_64), musl.

Raw recon artefacts: `recon/` (see `recon/INDEX.md`).

---

## Round 1 – Phase 1 Recon (2026-10-19)

Status: **Phase 1 steps 1–3 complete. Step 4 questions pending.** No device
commands were issued (only descriptor reads / SANE probing). No system config
was modified.

### 1. Environment (confirmed)

```
Linux alpine-jwm 6.18.57-0-lts #1-Alpine SMP PREEMPT_DYNAMIC 2026-10-16 ...
Alpine Linux v3.24
```

Relevant packages present:

| Package | Version |
|---|---|
| sane | 1.4.0-r4 |
| sane-utils (scanimage) | 1.4.0-r4 |
| sane-airscan | 0.99.36-r0 |
| simple-scan | 50.0-r0 |
| libusb | 1.0.30-r0 |
| python3 | 3.14.8-r0 |
| gcc / gcc-gdb | 15.2.0-r5 |
| usbutils (lsusb) | 019-r0 |
| sane-backend-epsonds / epson2 | 1.4.0-r4 |

Virtualisation for a Windows VM is available if ever needed: CPU reports `vmx`,
`kvm_intel` and `kvm` modules are loaded, and `qemu-system-x86_64` 11.0.3 is
packaged. **Not used – see "Blockers".**

### 2. Device enumeration (confirmed by `usbutils`)

Source: `recon/lsusb-v.txt`, `recon/lsusb.txt`, `recon/lsusb-t.txt`,
`recon/dmesg-usb.txt`.

```
Bus 001 Device 004: ID 132b:232b KONICA MINOLTA KONICA MINOLTA 206
  bcdUSB 2.00, High Speed (480 Mbps), Self Powered, MaxPower 2 mA
  iSerial A8A6041029423
  bNumConfigurations 1, 2 interfaces

Interface 0 – class 0xff / 0xff / 0xff  (vendor specific)  ← scanner channel
  EP 0x03  Bulk OUT   512 B   (host -> device)
  EP 0x84  Bulk IN    512 B
  EP 0x85  Bulk IN    512 B
  EP 0x87  Interrupt IN 64 B, bInterval 11
  no kernel driver bound (confirmed via /sys: 1-2:1.0 -> (none))

Interface 1 – class 0x07 / 0x01 / 0x02  (USB printer)      ← print channel
  EP 0x01  Bulk OUT   512 B
  EP 0x82  Bulk IN    512 B
  bound to `usblp` -> /dev/usblp0  (1-2:1.1 -> usblp)
```

dmesg shows one earlier USB disconnect + re-enumeration of this device
(`usb 1-2: USB disconnect, device number 3` at t≈3772, re-enumerated as
device 4 at t≈8007). Cause unknown; consistent with the spec's warning that the
device is fragile on USB. Not caused by this recon round.

Note: `lsusb -v` prints `unable to initialize usb spec` on this host (usbutils
019 doesn't ship the USB spec file); descriptors are still complete.

### 3. SANE state (confirmed)

Source: `recon/sane-find-scanner.txt`, `recon/scanimage-L.txt`,
`recon/sane-libs.txt`, `recon/sane-conf-listing.txt`.

- `sane-find-scanner`:
  `found possible USB scanner (vendor=0x132b [KONICA MINOLTA], product=0x232b [KONICA MINOLTA 206]) at libusb:001:004`
- `scanimage -L` returns only the Epson:
  `device 'epsonds:net:192.168.1.19' is a Epson PID 1186 ESC/I-2`
- Installed backends under `/usr/lib/sane/`: `airscan`, `epson2`, `epsonds`,
  `lexmark_x2600` only. No Konica backend.
- Current `/etc/sane.d/` state (from prior Epson work, see snapshots in
  `recon/dll.conf.snapshot`, `recon/dll.d.snapshot`, `recon/epsonds.conf.snapshot`):
  `dll.d/epsonds` enabled; `dll.d/epson2` and `dll.d/airscan` commented out;
  `epsonds.conf` has a manual `net 192.168.1.19`.
  These are unrelated to the Konica and should not be disturbed.

### 4. Sibling-model search (spec Phase 1 step 3) — no quick win

Sources: `recon/sane-supported-konica.txt`,
`recon/sane-konica-minolta-wiki.txt`, `recon/sane-magicolor-man.txt`.

- SANE's supported-device list contains exactly **one** Konica Minolta scanner:
  **magicolor 1690MF** (USB `0x132b/0x2089` and network), via the unmaintained
  `sane-magicolor` backend.
- **bizhub 162/132** is listed as **Unsupported**, with the note: "Uses a
  similar protocol as the magicolor 1690MF, according to Ilia Sotnikov."
- The kainhofer wiki (Reinhold) documents bizhub devices separately and states
  support "is not included in the Sane scanner library, and I have no plans to
  implement them."
- Conclusion: **no sibling SANE backend applies to the 206.** The quick-win
  exit condition in Phase 1.3 is not met; we continue.

### 5. Documented-protocol lead (new, important for Phase 4/5)

Source: `recon/bizhub-scan-wiki.txt` (Reinhold's wiki, "The Scanning Protocol
of the Konica Minolta bizhub devices", 2011).

- Reverse engineered from **LAN captures** (Windows TWAIN + Wireshark) of
  **bizhub C203** and **bizhub 363**, not from the 206 and not over USB.
- Network transport: TCP port **59158** on the copier.
- Framing: a **12-byte header** `tt 00 00 00 ss ss ss ss xx 00 00 yy`
  (target 01=HDD box, 02=scanner; size little-endian; type 01=send,
  02=request, 04=no data; direction 00=host, 80=scanner), followed by SCL data.
- Command language is HP **SCL**: `ESC E` (welcome/init), `ESC*s##E`
  (inquire), `ESC*s##U` (binary upload), `ESC*w0J` (lock), `ESC*z24G` /
  `ESC*z27H` (image parameters, 24/27 bytes), `ESC*w0S` (read scan data),
  `ESC*f0S` (start scan), `ESC*s265U` (image extent), `ESC*oE` (clear errors).
- Parameter tables: resolutions 100–600 dpi, colour mode, compression
  (none / JPEG / BW pixelwise), duplex, paper-size IDs, image-format IDs.
- **Unknown:** whether the 206's USB interface 0 carries this same SCL protocol
  (possibly with USB bulk framing instead of the 12-byte TCP header). This is
  the central hypothesis to test.

This documentation is *inferred* for our device — it applies *confirmed* only to
C203/363 over LAN. It is not a substitute for captures, but it gives a concrete
starting point for a safe, small live probe (`ESC E` first).

### 6. Print-side cross-check (spec "Known facts")

Observed on this host:

- CUPS queue is **`KONICA206_ALPINE`** (default), device URI
  `usb://KONICA%20MINOLTA/206?serial=A8A6041029423&interface=1`.
- It uses the **standard CUPS `usb` backend** (`/usr/lib/cups/backend/usb`)
  with a retrofitted PPD `/usr/share/cups/model/KonicaMinolta-206-native.ppd`
  (`*NickName: KONICA MINOLTA 206 (ICC-free, full-bleed retrofit)`).
- **Not found:** a PAPPL queue, a custom libusb CUPS backend, or queues named
  `KONICA_MINOLTA_206` / `konica206uri` (names used in the spec).
- No vendor scanner installer (`.exe`/`.ds`/WIA/TWAIN) found on disk
  (searched `/home/vinod`, maxdepth 4).

Discrepancy is logged here as **spec assumption vs. observed host**; the print
path is left strictly untouched per safety rule 1.

### 7. Safety / side effects

- Interface 0 was only enumerated; no bulk traffic sent.
- `usblp` on interface 1 was not detached; no device reset; no unplug cycle.
- `sane-find-scanner` performed its usual read-only probing.
- No CUPS/queue, PPD or SANE config change was made in this round.

### 8. Blockers / open questions

1. **Phase 2 (capture) needs Windows.** The spec's capture setup is a QEMU/KVM
   Windows VM with the printer passed through (`usbmon`/Wireshark), or USBPcap
   on bare-metal Windows. The operator instruction received is **"do not install
   Windows."** Phase 2 cannot proceed as written until this is resolved.
2. **Phase 3 (static analysis) needs the vendor installer** (TWAIN `.ds` +
   WIA files). None is present on disk; we need the installer or extracted
   binaries (to be kept in git-ignored `vendor/`).
3. **ADF:** unknown whether this 206 unit has an ADF (the wiki mentions ADF
   parameters 24/25/20201; the spec asked us to confirm).
4. No capture means any protocol work is **inferred, not confirmed**.

### 9. Next proposed step (needs operator decision)

Options, in order of rigor:

- **A. Capture on a Windows host** the operator already has (USBPcap), then
  bring `.pcapng` files here → proceed with Phases 4–6 normally.
- **B. Permit a temporary Windows VM** on this host for capture (revises the
  "no Windows" instruction; KVM is ready).
- **C. Skip capture; probe the documented SCL protocol live** over USB
  interface 0: start with `ESC E` (and only that) using small (≤8192 B) bulk
  writes, log the raw exchange, then decide. Requires explicit approval to send
  traffic to the device, plus a recovery plan if it drops off the bus.
- **D. Pause** the project.

Awaiting decision. Per working style, no further device contact until then.

---

## Round 13 – Correct 206 driver found; 64-byte command family decoded (2026-10-19)

Status: **breakthrough on the protocol; one malformed probe stalled the device.**
No new device traffic in this round (static analysis only).

### 1. The 206 has its own driver package

The 225i/205i package was the wrong family. The 206 belongs to the **bizhub
226/206** series. The correct package is:

```
BH226GDIWinx64_200EN.zip
  BH226GDIWinx64_200EN/
    AR206.DS   (507904 bytes, TWAIN data source, "KONICA MINOLTA 206 TWAIN")
    AR226.DS
    AR246.DS
    W2206.dll  (WIA driver)
    ARWTG.inf  (scanner INF)
```

Downloaded for static analysis only into git-ignored `vendor/bh226-200/`.
`AR206.DS` contains the string `KONICA MINOLTA 206 Scanner` and the USB
transport `\\.\Usbscan%d`. This is the authoritative protocol reference.

### 2. Command map in `AR206.DS`

All commands are a 64-byte block on bulk OUT `0x03`; reads come from bulk IN
`0x85`.

| Address | Wire command | Read |
|---|---|---|
| `0x1001db40` | `03 08 04 00 00 00 <len0..3> 01` | none |
| `0x1001dc00` | `03 09 01` | 1 byte |
| `0x1001dcd0` | `03 0a` | none |
| `0x1001dd50` | `03 0b 08` | 8 bytes (geometry) |
| `0x1001de20` | **`03 0c 0d 00 00 00` + 13 param bytes** | none |
| `0x1001ded0` | `03 0d 0a` | 10 bytes (status) |
| `0x1001e0b0` | `03 0e 04 00 00 00 <len0..3>` | 5-byte header + data |
| `0x1001e260` | `03 0f 01 <mode>` | 1 byte |
| `0x1001e3a0` | `03 10 01 02` | 1 byte |
| `0x1001e490` | `03 11 01` | 1 byte |

Transport selector `[0x10071ad0] == 1` selects USB (`0x1001d640` write,
`0x1001d610` read). The 206 uses the same 64-byte family and the same
`03 0c` framing as the 225i/205i.

### 3. Root cause of the `03 0c 0d` stall

Both the 225i/205i and the 206 build:

```
03 0c 0d 00 00 00 <13 param bytes>      (params start at offset 6)
```

In `AR206.DS` `0x1001de20` the command bytes are written at offsets 0–2
(`03 0c 0d`) and offsets 3–5 are zeroed; a temporary `push edi`/`pop edi`
shifts the copy-loop base, so `param[0..12]` lands at offsets 6–18, **not**
on top of `0x0d`. The 225i `0x1001f180` builds the same layout with
`mov dword [ebp-0x104], 0xd0c03` and `mov word [ebp-0x100], 0`.

The original probe sent `03 0c 0d` + the 13-byte block **with the three zero
bytes missing**, so every parameter was shifted three bytes earlier. The
device parsed offset 3 as part of the parameter block, rejected it, and
stopped accepting further OUT transfers. The first “corrected” probe then
dropped the `0d 00 00 00` prefix entirely, which was also malformed. This is
the cause of both stalls.

### 4. 206 parameter block (`0x100665e8`, built by `fcn.100166c0`)

Static template:

```
01 00 05 02 00 00 00 00 00 00 00 00 00
```

Builder `fcn.100166c0` at `0x100166c0` fills:

| Offset | Meaning | Source |
|---|---|---|
| 0 | resolution code | `[0x10070ae8]`: 0=150, 1=300, 2=600 dpi |
| 1 | pixel/mode | `3 - [0x10071ad8]` (default 0 = mono) |
| 2 | resolution index | 5 when `[0x10070b08] == 0` |
| 3 | paper code | `[0x100719c4]` (from table `0x10066560`) |
| 4–7 | window left/top | 0 |
| 8–9 | window width | table1 `0x10066590[paper_index]` (LE) |
| 10–11 | window height | table2 `0x100665bc[paper_index]` (LE) |
| 12 | source/ADF flag | 0 = no ADF paper/flatbed; 1/2 = ADF from `[0x10070b30]` + status bit |

Paper tables (16-bit LE):

```
index:      0     1     2     3     4     5     6     7
width:   7015  6070  4960  4299  3496  4960  5102  5197
height:  9921  8598  7015  6070  4960  7795  7795  7795
```

Index 0 = A3 (7015×9921), index 2 = A4 (4960×7015). The static template's
paper code is 2, so the first corrected probe uses A4:

```
03 0c 0d 00 00 00 01 00 05 02 00 00 00 00 60 13 67 1b 00
```

### 5. Full scan sequence (from `fcn.10012f20` / `fcn.1001e000`)

1. `03 09 01` → read 1 (init)
2. `03 0d 0a` → read 10 (status)
3. `03 0c 0d 00 00 00 <13 params>` (write only)
4. `03 0b 08` → read 8 (geometry: width LE at [0..1], height LE at [2..3],
   bytes 4–7 unknown)
5. `03 09 01` → read 1 (init again)
6. `03 08 04 00 00 00 <len0..3> 01` where `len = width_bytes × height`
   (`width_bytes = width` for 1 byte/px, `(width+7)/8` for mode 0/1,
   `width*3` for mode 3)
7. `03 0a` (start)
8. loop `03 0e 04 00 00 00 <chunk0..3>` → read 5-byte header
   (byte0 status, bytes1–2 = 16-bit available length) then read that many
   bytes from `0x85`
9. `03 11 01` (close)

### 6. Next test (device currently stalled; needs power-cycle)

1. Power-cycle the 206 (USB 5 V), verify `03 0d 0a` still answers.
2. Send only `03 0c 0d 00 00 00 01 00 05 02 00 00 00 00 60 13 67 1b 00`
   (write only, **no read**).
3. Send `03 0b 08` and read 8. Non-zero width/height confirms the block.
4. If it stalls or returns zero, vary one field at a time (source 0/1,
   mode 0/1, paper 0/2) with a power-cycle between attempts.
5. Then run the full sequence above and probe `0x84` vs `0x85` for image data.

**Do not resend the old `03 0c 0d …` payload.**

---

## Resolution (Round 14): working userspace scan

The earlier stalled probes were caused by two protocol mistakes, not by the
USB endpoint choice.

### Corrected start path

`03 0a` is **not** a start command. In `fcn.10012f20` the call to
`0x1001dcd0` (`03 0a`) is on the `eax == -1` error path only; the normal
path is `0x1001e000` (params → geometry → init → set-length) and then the
read loop. Sending `03 0a` after set-length aborts the scan.

`03 08 04 00 00 00 <len4> 01` is the command that starts the scan. The
trailing `01` is the start flag.

### Corrected data path

Both the 5-byte data header and the payload arrive on bulk IN **0x85**, not
0x84. The 206 opens two `usbscan` pipes on Windows; both small responses and
image data are read from the second pipe, which is 0x85 on this unit.

A full A4 mono scan at 300 dpi:

```
status     03 0d 0a                    -> ff 00 00 00 00 00 00 00 00 00
params     03 0c 0d 00 00 00 01 00 05 02 00 00 00 00 60 13 67 1b 00
geometry   03 0b 08                    -> 00 10 b3 0d b0 09 b3 0d
                                          line=4096 height=3507 window=2480x3507
init       03 09 01                    -> 00
set length 03 08 04 00 00 00 00 66 1b 00 01   (starts scan)
read chunk 03 0e 04 00 00 00 00 fe 00 00
            -> header 00 00 fe 00 00 (status 0, 65024 bytes)
            -> 65024 bytes on 0x85
... 27 full chunks ...
last chunk 03 0e 04 00 00 00 9c 00 00 00
            -> header 00 00 9c 00 00 (39936 bytes)
            -> 39936 bytes on 0x85
```

Total: `512 × 3507 = 1,795,584` bytes. No close command is sent.

### Do not send `03 11 01`

`03 11 01` is only used by the DS's TWAIN UI/session-close handlers, not
by the normal scan path. On this unit it resets the USB session: the device
re-enumerates, control transfers still work, but all bulk endpoints
(0x03/0x84/0x85/0x87) time out. `clear_halt`, `SET_INTERFACE`, and
`set_configuration` do not recover it; only a power-cycle does. With the
command omitted, two back-to-back scans succeeded without a power-cycle.

### Raw image layout

* 3507 rows, 512 bytes per row (4096-pixel line buffer, mono).
* The requested A4 window is the first 2480 pixels (310 bytes) of each row;
  the remaining 1616 pixels are padding/background.
* Bits are MSB-first, **1 = black**, 0 = white.
* The test page was placed with its long side along the scan direction, so
  the raw image is the page rotated 90° counter-clockwise. A 90° clockwise
  rotation produced upright text.
* Output: 3507×2480 grayscale PNG/PDF, A4 landscape.

### Working tools

* `tools/ar206_scan.py` — production CLI:
  `python3 tools/ar206_scan.py --paper a4 --dpi 300 --rotate 90 --out scan.png --pdf scan.pdf`
  Options: `--paper a4|a3`, `--dpi 150|300|600`, `--source flatbed|adf`,
  `--rotate 0|90|180|270`, `--raw`, `--close` (diagnostics only).
* `tools/konica206-scan` — desktop wrapper; writes to `~/Scans` and opens
  the PDF. Symlinked as `~/.local/bin/konica206-scan`.
* JWM: "PDF and Scanning" → "Konica 206 Scan (A4 mono)".

### Verified artifacts

* `probe/reuse-scan1.png`, `probe/reuse-scan2.png` — two consecutive scans.
* `probe/pdf-scan-fixed.pdf` — upright A4 PDF (pdfinfo: 1 page, 841.68×595.2 pts).
* `probe/round13-scan-full.bin` — raw 1,795,584-byte capture.

### Remaining

* ADF: set parameter byte 12 to 2 and verify the status byte
  `[0x1006f2a1] & 1` indicates paper present. Not yet tested.
* A3: paper code 0, window 7015×9921. Not yet tested.
* Simple Scan/SANE: the 206 is not visible to SANE. A `sane-ar206` backend
  would be needed for Simple Scan integration; the current tool is standalone.
