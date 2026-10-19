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
