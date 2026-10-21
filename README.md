# Konica Minolta bizhub 206 — Linux scanner driver

A reverse-engineered Linux driver for the **scanner** built into the Konica
Minolta bizhub 206 multifunction printer. The vendor ships no Linux driver,
and no existing SANE backend speaks its protocol, so this repository contains
one written from scratch against the vendor's own `AR206.DS` command set.

USB ID `132b:232b`. The scanner lives on **interface 0**; interface 1 is the
printer (`usblp`) and is never touched, so printing keeps working alongside
scanning.

| | |
|---|---|
| **Scan sources** | flatbed, ADF (document feeder) |
| **Paper** | A4, A3 |
| **Resolution** | 150 / 300 / 600 dpi |
| **Colour** | ✗ the scan unit is monochrome — output is 8-bit grayscale |
| **Output** | PNG, PDF (CLI) · any SANE frontend (`scanimage`, Simple Scan, NAPS2) |
| **Tested on** | Alpine Linux (musl), Debian/Ubuntu (glibc) |

Two ways to use it, both from this repository:

1. **SANE backend (`sane-ar206`)** — the scanner then appears in `scanimage`,
   Simple Scan and NAPS2 like any other scanner.
2. **Standalone Python CLI** — talks to the device over libusb with no SANE
   and no daemon; useful as a first check that the hardware works.

---

## Quick start (SANE backend)

### Alpine

```sh
sudo apk add sane-dev libusb-dev build-base
make -C sane
sudo make -C sane install
sudo adduser "$USER" lp          # the USB node is owned by root:lp
```

### Debian / Ubuntu

```sh
sudo apt install libsane-dev libusb-1.0-0-dev build-essential
make -C sane
sudo make -C sane install
sudo make -C sane install-udev  # /etc/udev/rules.d/60-ar206.rules
sudo udevadm control --reload && sudo udevadm trigger
sudo adduser "$USER" scanner
```

Replug the scanner (or log out and back in) so the new group membership
takes effect, then:

```sh
$ scanimage -L
device `ar206:ar206:usb:132b:232b' is a KONICA MINOLTA bizhub 206 flatbed scanner

$ scanimage -d ar206:ar206:usb:132b:232b \
      --resolution 300 --mode Gray --source Flatbed --paper A4 -o page.png
```

The Makefile auto-detects where SANE keeps its backends (`/usr/lib/sane` on
Alpine, `/usr/lib/<triplet>/sane` on Debian/Ubuntu); override it with
`make SANE_LIBDIR=/path/to/sane`. `DESTDIR` is honoured for packaging.

To remove it again:

```sh
sudo make -C sane uninstall
sudo make -C sane uninstall-udev    # Debian/Ubuntu
```

---

## Quick start (standalone CLI)

No SANE, no daemon — the fastest way to confirm the hardware is alive.

```sh
sudo apk add python3 py3-usb          # Alpine
sudo apt install python3 python3-usb  # Debian/Ubuntu

python3 tools/ar206_scan.py --source flatbed --paper a4 --dpi 300 --out page.png
```

| Option | Values | Default |
|---|---|---|
| `--paper` | `a4`, `a3` | `a4` |
| `--dpi` | `150`, `300`, `600` | `300` |
| `--source` | `flatbed`, `adf` | `flatbed` |
| `--rotate` | `0`, `90`, `180`, `270` (clockwise) | `0` |
| `--out` / `--pdf` / `--raw` | paths | — |
| `--close` | flag | off — **diagnostics only**, see [Safety rules](#safety-rules) |

`tools/konica206-scan [flatbed|adf] [rotation]` is a desktop wrapper: it
scans A4 at 300 dpi into `~/Scans/`, writes PNG + PDF and opens the PDF.

---

## NAPS2

**Native NAPS2** (deb / AppImage) links against the system SANE, so once the
backend is installed the device simply appears under **Profile Settings →
Choose device** as `ar206:ar206:usb:132b:232b`. Nothing else to do.

**The NAPS2 flatpak** bundles its own SANE stack, and on a musl host it cannot
load a host-built backend. The backend is therefore served over SANE's network
protocol:

```
NAPS2 → bundled libsane → net backend → localhost:6566
      → saned (host) → ar206 backend → libusb → USB 206
```

One script does the wiring (works on OpenRC and systemd):

```sh
sh tools/setup-naps2.sh
```

The device then appears as **bizhub 206 (net)**. Create a profile with
**Grayscale** and **150/300/600 dpi** — the backend supports neither 100 dpi
nor colour.

---

## Orientation — read this before scanning

The flatbed's scan window is **portrait** (210 mm across × 297 mm deep), so a
sheet lying flat on the glass comes out upright with **no rotation**
(`--rotation 0`). The ADF feeds the sheet turned on its side, so it needs
**270**.

| Source | Rotation | Result |
|---|---|---|
| Flatbed | `0` | upright, portrait |
| Flatbed | `90` | only if you deliberately lay the sheet **sideways** on the glass (it then gets cropped) |
| ADF | `270` | upright |

Output size for A4 at 300 dpi is **2480 × 3507** (flatbed, unrotated) or
**3507 × 2480** (ADF).

---

## Safety rules

These come from reverse engineering and hard-won testing — please follow them:

* **Never send `03 11 01`** (session close). On this unit it resets the USB
  session and wedges the bulk endpoints until the scanner is **power-cycled**.
  The backend never sends it; `ar206_scan.py --close` does, for diagnostics only.
* **`03 0a`** aborts a scan. The backend never sends it.
* **Only interface 0 is opened.** Interface 1 (`usblp`) is never detached, so
  printing is unaffected.
* If the scanner stops responding, **power-cycle it**. A USB reset does not
  recover a stalled endpoint.

---

## Limitations

* Monochrome only — the unit has no colour scan head.
* **ADF multi-page looping is not implemented**: one page per `sane_start()`.
* No duplex (the ADF has no simplex/duplex switch support exposed).
* 100 dpi is not supported.
* The `--preview` option is accepted but ignored.

---

## Repository layout

| Path | Contents |
|---|---|
| `sane/` | The SANE backend: `ar206.c`, `Makefile`, `ar206.conf`, udev rule |
| `tools/` | `ar206_scan.py` (CLI), `konica206-scan` (wrapper), `setup-naps2.sh`, plus low-level USB testers |
| `probe/` | Scans and raw captures from development |
| `recon/` | USB / SANE / environment recon snapshots |
| `vendor/` | Konica's own Windows driver packages — the protocol source of truth, kept for reference |
| `KONICA_SCANNER_RE_INSTRUCTIONS.md` | **Operator guide** — full install and usage instructions |
| `KONICA_SCANNER_RE_INVESTIGATION.md` | **Reverse-engineering log** — the protocol, command map and test rounds |

### Low-level tools (advanced)

* `tools/usb_probe.py` — one-shot write/read probe of interface 0.
* `tools/usb_session.py` — scripted command sequences.
* `tools/ar206_test.py` — staged protocol tester (`--stage status|geometry|full`).

All of them claim interface 0 only, never detach `usblp`, and never reset the
device.

---

## Notes

* The code in this repository is provided as-is. The binaries under `vendor/`
  are Konica Minolta's and remain their copyright — they are included for
  protocol reference only.
* **Please do not commit scans of personal documents.** The development test
  sheets were an Aadhaar letter; those files were purged from this
  repository's history on 2026-10-21. Use a blank sheet or a synthetic test
  page for test captures.
