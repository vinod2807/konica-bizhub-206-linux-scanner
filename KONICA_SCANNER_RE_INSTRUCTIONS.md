# Konica Minolta bizhub 206 — Linux scanning instructions

How to scan from a **Konica Minolta bizhub 206** over USB on Linux, using a
userspace driver reverse-engineered from the vendor's `AR206.DS`.  Two ways
to use it:

1. **Standalone Python CLI** — no SANE, no daemon, talks libusb directly.
2. **SANE backend (`sane-ar206`)** — integrates with Simple Scan,
   `scanimage`, and NAPS2 (native), and via a `saned` bridge with the NAPS2
   flatpak.

The full reverse-engineering write-up is in
[`KONICA_SCANNER_RE_INVESTIGATION.md`](KONICA_SCANNER_RE_INVESTIGATION.md);
this file is the operator guide.

---

## 1. Requirements

| Item | Detail |
|---|---|
| Scanner | Konica Minolta bizhub 206, USB ID `132b:232b` |
| Capability | Monochrome, flatbed + ADF, A4 and A3 |
| Interface 0 | vendor-specific (`ff/ff/ff`): EP `0x03` OUT, `0x85` bulk IN, `0x87` interrupt IN |
| Interface 1 | printer class, owned by `usblp` — **must not be disturbed** |
| Host | any Linux with libusb; developed on Alpine, also supports Debian/Ubuntu |

The 206 shares one USB device node between the scanner (interface 0) and the
printer (interface 1).  This driver only ever opens interface 0, so printing
(`usb://…interface=1`, e.g. the `KONICA206_ALPINE` queue) keeps working.

---

## 2. Quick start (standalone CLI)

No SANE or daemon needed — this is the fastest way to confirm the hardware.

```sh
# Alpine
sudo apk add python3 py3-usb
# Debian/Ubuntu
sudo apt install python3 python3-usb

cd konica-scanner-re
python3 tools/ar206_scan.py --source flatbed --paper a4 --dpi 300 --rotate 90 --out page.png
```

If your user cannot open the USB device, see the permissions section for
your distro (§4.3 / §4.4).  The CLI claims interface 0 and refuses to run if
a kernel driver is bound to it.

### CLI options (`tools/ar206_scan.py`)

| Option | Values | Default | Notes |
|---|---|---|---|
| `--paper` | `a4`, `a3` | `a4` | |
| `--dpi` | `150`, `300`, `600` | `300` | |
| `--source` | `flatbed`, `adf` | `flatbed` | |
| `--rotate` | `0`, `90`, `180`, `270` | `0` | clockwise |
| `--out` | path | `scan-<stamp>.png` | PNG output |
| `--pdf` | path | — | optional PDF as well |
| `--raw` | path | — | optional raw mono dump |
| `--close` | flag | off | sends `03 11 01`; **diagnostics only** (see §8) |

For an upright page: flatbed `--rotate 90`, ADF `--rotate 270`.

### Desktop wrapper

`tools/konica206-scan [flatbed|adf] [0|90|180|270]` scans A4 at 300 dpi into
`~/Scans/`, writes PNG + PDF, and opens the PDF.  It contains a hard-coded
path to `ar206_scan.py`; edit that line if you clone the repo elsewhere.

---

## 3. SANE backend (`sane-ar206`)

This is what makes the 206 appear in **Simple Scan**, `scanimage`, and
native NAPS2.  Source lives in [`sane/`](sane/).

### 3.1 Build and install

**Alpine:**

```sh
sudo apk add sane-dev libusb-dev build-base
make -C sane
sudo make -C sane install
```

**Debian / Ubuntu:**

```sh
sudo apt install libsane-dev libusb-1.0-0-dev build-essential
make -C sane
sudo make -C sane install
```

`make install` places:

* `libsane-ar206.so*` in the SANE backend dir (auto-detected:
  `/usr/lib/sane` on Alpine, `/usr/lib/<triplet>/sane` on Debian/Ubuntu;
  override with `make SANE_LIBDIR=…`, `DESTDIR` is honoured),
* `/etc/sane.d/ar206.conf`,
* `/etc/sane.d/dll.d/ar206`.

The Epson `epsonds` entry is untouched; both backends load together.

### 3.2 USB permissions

**Alpine:** the node is `root:lp`.  Add yourself to `lp`:

```sh
sudo adduser "$USER" lp   # then log out/in
```

**Debian / Ubuntu:** install the bundled udev rule and join `scanner`:

```sh
sudo make -C sane install-udev          # /etc/udev/rules.d/60-ar206.rules
sudo udevadm control --reload && sudo udevadm trigger
sudo adduser "$USER" scanner            # then log out/in
```

Replug the scanner (or reboot) so the node is re-tagged.

### 3.3 Verify

```sh
scanimage -L
# device `ar206:ar206:usb:132b:232b' is a KONICA MINOLTA bizhub 206 flatbed scanner
```

Scan directly:

```sh
scanimage -d ar206:ar206:usb:132b:232b \
    --resolution 300 --mode Gray --source Flatbed --paper A4 --rotation 90 \
    -o flatbed.png

scanimage -d ar206:ar206:usb:132b:232b \
    --resolution 300 --mode Gray --source ADF --paper A4 --rotation 270 \
    -o adf.png
```

Simple Scan lists it as **KONICA MINOLTA bizhub 206**.

### 3.4 Backend options

| Option | Values | Default |
|---|---|---|
| `--resolution` | `150`, `300`, `600` | `300` |
| `--mode` | `Gray`, `Lineart` | `Gray` |
| `--source` | `Flatbed`, `ADF` | `Flatbed` |
| `--paper` | `A4`, `A3` | `A4` |
| `--rotation` | `0`, `90`, `180`, `270` (clockwise) | `90` flatbed / `270` ADF |
| `--preview` | `yes`, `no` | `no` (currently ignored) |

Both `Gray` and `Lineart` produce 8-bit grayscale (the unit is monochrome).
ADF with an empty feeder returns `SANE_STATUS_NO_DOCS`.  One page is scanned
per `sane_start()`; multi-page ADF looping is **not** implemented.

### 3.5 Uninstall

```sh
sudo make -C sane uninstall          # remove the backend + config
sudo make -C sane uninstall-udev     # Debian/Ubuntu, remove the udev rule
```

---

## 4. NAPS2

### 4.1 Native NAPS2 (deb / AppImage)

If NAPS2 is installed natively it links against the **system** SANE, so once
§3 is done the 206 simply appears in **Profile Settings → Choose device** as
`ar206:ar206:usb:132b:232b`.  No bridge needed.

### 4.2 NAPS2 flatpak

The flatpak bundles its **own** SANE stack (`/app/lib/libsane.so` + backends
under `/app/lib/sane`).  If the host libc differs (musl on Alpine) it cannot
load the host backend, so the backend is served over SANE's network protocol:

```
NAPS2 → bundled libsane → net backend → localhost:6566
      → saned (host) → ar206 backend → libusb → USB 206
```

Configure it with the bundled script (works on Alpine/OpenRC and
Debian/Ubuntu/systemd):

```sh
sh tools/setup-naps2.sh
```

It installs saned + the net backend, grants the `saned` user USB access
(`lp` on Alpine, the udev rule + `scanner` on Debian/Ubuntu), restricts
`/etc/sane.d/saned.conf` to `localhost`, starts saned, then copies NAPS2's
`sane.d` into `~/.var/app/com.naps2.Naps2/config/sane` and points the app at
it with `flatpak override --user --env=SANE_CONFIG_DIR=…`.

In NAPS2, **Profile Settings → Choose device** will list **bizhub 206
(net)** (id `net:localhost:ar206:ar206:usb:132b:232b`).  Create a profile
with **Grayscale** (or **Black and White**) and a **150/300/600 dpi**
resolution — the backend does not support 100 dpi or color.

---

## 5. Safety rules (important)

These come from reverse engineering and hard-won testing:

* **Never send `03 11 01`** (session close).  On this unit it resets the USB
  session and wedges the bulk endpoints until the scanner is power-cycled.
  The backend and CLI never send it; `ar206_scan.py --close` does, and is
  for diagnostics only.
* **`03 0a`** aborts the scan.  The backend never sends it.
* Only interface 0 is opened.  Interface 1 (`usblp`) is never detached, so
  printing is unaffected.
* If the scanner stops responding, **power-cycle it** (recover a stalled
  endpoint that way, not with a USB reset).

---

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `device 132b:232b not found` | scanner off/unplugged, or a VM/USB filter missing |
| `kernel driver active on interface 0` | another process holds interface 0; close it, or check `lsusb -t` |
| `scanimage -L` doesn't show it | backend not installed / wrong `SANE_LIBDIR`; check `/etc/sane.d/dll.d/ar206` |
| Permission denied opening USB | join `lp` (Alpine) or `scanner` + udev rule (Debian/Ubuntu); log out/in |
| ADF returns `NO_DOCS` | feeder empty — status byte 1 is the paper-present bit |
| Image sideways | wrong `--rotate`/`--rotation` (flatbed 90, ADF 270) |
| NAPS2 flatpak doesn't list it | `saned` not running, or `SANE_CONFIG_DIR` override missing — rerun `tools/setup-naps2.sh` |
| Everything hangs after an experiment | power-cycle the scanner (see §5) |

---

## 7. Repository layout

| Path | Contents |
|---|---|
| `sane/` | SANE backend (`ar206.c`), `Makefile`, `ar206.conf`, udev rule, README |
| `tools/` | `ar206_scan.py` (CLI), `konica206-scan` (wrapper), staged testers, `setup-naps2.sh` |
| `probe/` | raw captures and rendered artifacts from development |
| `recon/` | environment/USB/SANE recon snapshots |
| `vendor/` | vendor driver packages (incl. `AR206.DS`, the protocol source of truth) |
| `KONICA_SCANNER_RE_INVESTIGATION.md` | full reverse-engineering log (protocol, command map, rounds) |
| `KONICA_SCANNER_RE_INSTRUCTIONS.md` | this file |

### Low-level tools (advanced)

* `tools/usb_probe.py` — one-shot write/read probe of interface 0.
* `tools/usb_session.py` — scripted command sequences.
* `tools/ar206_test.py` — staged protocol tester (`--stage status|geometry|full`).

All of them claim interface 0 only, never detach `usblp`, and never reset the
device.
