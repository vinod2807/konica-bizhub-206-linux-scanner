# sane-ar206

Minimal SANE backend for the Konica Minolta bizhub 206 USB scanner.

The backend speaks the AR206.DS command set directly on interface 0
(`0x03` command OUT, `0x85` response/image IN).  It buffers one complete
page in `sane_start()`, converts the 1-bit data to 8-bit grayscale,
rotates it, and serves it to the frontend from `sane_read()`.

## Build

The backend is plain C using only SANE + libusb, so it builds on any
distro.  It was developed on Alpine (musl); Debian/Ubuntu (glibc) work
too.

Alpine:

```sh
sudo apk add sane-dev libusb-dev build-base
make
```

Debian / Ubuntu:

```sh
sudo apt install libsane-dev libusb-1.0-0-dev build-essential
make
```

## Install

```sh
sudo make install
```

This installs:

* `libsane-ar206.so*` into the SANE backend dir
* `/etc/sane.d/ar206.conf`
* `/etc/sane.d/dll.d/ar206`

The Makefile auto-detects the backend directory: `/usr/lib/sane` on
Alpine, `/usr/lib/<triplet>/sane` (e.g. `/usr/lib/x86_64-linux-gnu/sane`)
on Debian/Ubuntu.  Override with `make SANE_LIBDIR=/path/to/sane` if
needed; `DESTDIR` is honoured for packaging.

The existing `epsonds` (Epson L3260) entry is left alone; both backends
are loaded by SANE.

### Debian / Ubuntu: USB permissions

Unlike Alpine (where the `lp` group owns the node), Debian/Ubuntu use
udev.  Install the bundled rule and add yourself to the `scanner` group:

```sh
sudo make install-udev            # /etc/udev/rules.d/60-ar206.rules
sudo udevadm control --reload && sudo udevadm trigger
sudo adduser "$USER" scanner
```

Replug the scanner (or reboot) so the node is re-tagged, then
`scanimage -L` should list `ar206:ar206:usb:132b:232b`.

## Use

```sh
scanimage -L
scanimage -d ar206:ar206:usb:132b:232b \
    --resolution 300 --source Flatbed --paper A4 --rotation 90 \
    -o flatbed.png
scanimage -d ar206:ar206:usb:132b:232b \
    --resolution 300 --source ADF --paper A4 --rotation 270 \
    -o adf.png
```

Simple Scan lists the device as **KONICA MINOLTA bizhub 206**.

## NAPS2 (Flatpak)

The NAPS2 flatpak bundles its own glibc SANE stack
(`/app/lib/libsane.so.1.4.0` plus backends under `/app/lib/sane`), so it
cannot load the host's musl `libsane-ar206.so` directly.  Instead the
host backend is served over the SANE network protocol:

```
NAPS2 -> bundled libsane -> net backend -> localhost:6566
      -> saned (host) -> ar206 backend -> libusb -> USB 206
```

Run `tools/setup-naps2.sh` to configure this.  It detects the distro
(Alpine/OpenRC + `apk`, or Debian/Ubuntu/systemd + `apt`) and:

* installs saned and the net backend (`sane-saned` + `sane-backend-net`
  on Alpine; `sane-utils` on Debian/Ubuntu);
* grants the unprivileged `saned` user USB access (adds it to `lp` on
  Alpine, or installs the udev rule and adds it to `scanner` on
  Debian/Ubuntu);
* allows only `localhost`/`127.0.0.1` in `/etc/sane.d/saned.conf`;
* enables and starts saned (`rc-service` on Alpine, `saned.socket` on
  Debian/Ubuntu);
* copies NAPS2's bundled `sane.d` to
  `~/.var/app/com.naps2.Naps2/config/sane` and uncomments `localhost`
  in its `net.conf`;
* sets `SANE_CONFIG_DIR` for the app via
  `flatpak override --user`.

If NAPS2 is installed **natively** (the `.deb`/AppImage from naps2.com)
rather than as a flatpak, no bridge is needed at all: it links against
the system SANE and sees `ar206:ar206:usb:132b:232b` directly.  The
script prints a note and exits in that case.

In NAPS2 the scanner appears in **Profile Settings -> Choose device** as
**bizhub 206 (net)** (device id `net:localhost:ar206:ar206:usb:132b:232b`).
Use `Grayscale` (or `Black and White`) and a 150/300/600 dpi resolution;
the backend does not support 100 dpi or color.

## Options

| Option | Values | Default |
|---|---|---|
| `--resolution` | `150`, `300`, `600` | `300` |
| `--mode` | `Gray`, `Lineart` | `Gray` |
| `--source` | `Flatbed`, `ADF` | `Flatbed` |
| `--paper` | `A4`, `A3` | `A4` |
| `--rotation` | `0`, `90`, `180`, `270` (clockwise) | `90` flatbed / `270` ADF |
| `--preview` | `yes`, `no` | `no` (currently ignored) |

## Notes

* The 206 is monochrome; `Gray` and `Lineart` both produce 8-bit gray
  (0 = black, 255 = white).
* ADF with no paper returns `SANE_STATUS_NO_DOCS`, based on byte 1 of the
  status response.
* Only interface 0 is opened.  Interface 1 (`usblp`, the print side) is
  never touched.
* `03 0a` (abort) and `03 11 01` (session close) are never sent; the
  latter wedges the bulk endpoints on this unit.
* One page is scanned per `sane_start()`.  Multi-page ADF looping is not
  implemented yet.
