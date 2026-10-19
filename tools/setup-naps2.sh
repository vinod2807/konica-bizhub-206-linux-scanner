#!/bin/sh
#
# setup-naps2.sh - expose the sane-ar206 backend to the NAPS2 flatpak.
#
# NAPS2 ships its own glibc SANE stack (/app/lib/libsane.so + backends) and
# cannot dlopen the host's musl libsane-ar206.so.  Instead we run the host
# backend behind saned on localhost and point NAPS2's bundled SANE "net"
# backend at it.  The host's own backends (epsonds for the Epson) are left
# untouched.
#
# Re-runnable; safe to execute again after a NAPS2 flatpak update.

set -eu

APP_ID=com.naps2.Naps2
SANE_CONF_DIR="$HOME/.var/app/$APP_ID/config/sane"

# 1. Host packages: saned server + the client-side net backend (for testing).
if ! command -v saned >/dev/null 2>&1; then
    sudo apk add sane-saned sane-backend-net
fi

# 2. saned runs as the unprivileged "saned" user; the USB node is root:lp.
if ! id -nG saned 2>/dev/null | grep -qw lp; then
    sudo adduser saned lp
fi

# 3. Allow local clients only.
if ! grep -qE '^[[:space:]]*127\.0\.0\.1[[:space:]]*$' /etc/sane.d/saned.conf; then
    printf '\n# Allow local clients only\nlocalhost\n127.0.0.1\n' \
        | sudo tee -a /etc/sane.d/saned.conf >/dev/null
fi

# 4. Start saned now and at boot.
sudo rc-update add saned default >/dev/null 2>&1 || true
if rc-service saned status >/dev/null 2>&1; then
    sudo rc-service saned restart
else
    sudo rc-service saned start
fi

# 5. Copy NAPS2's bundled SANE config into a writable dir and enable
#    "localhost" in net.conf so its net backend finds the host saned.
APP_FILES="$(flatpak info --show-location "$APP_ID" 2>/dev/null)/files"
if [ ! -d "$APP_FILES/etc/sane.d" ]; then
    echo "error: $APP_ID SANE config not found under $APP_FILES" >&2
    exit 1
fi
mkdir -p "$SANE_CONF_DIR"
cp -a "$APP_FILES/etc/sane.d/." "$SANE_CONF_DIR/"
sed -i 's/^# *localhost$/localhost/' "$SANE_CONF_DIR/net.conf"

# 6. Point NAPS2's SANE at that config dir.
flatpak override --user --env=SANE_CONFIG_DIR="$SANE_CONF_DIR" "$APP_ID"

cat <<EOF
Done.

NAPS2 will now list the scanner as "bizhub 206 (net)".
Create a profile: Profile Settings -> Choose device -> bizhub 206 (net),
then pick Grayscale + 150/300/600 dpi (100 dpi and color are unsupported
by the backend).
EOF
