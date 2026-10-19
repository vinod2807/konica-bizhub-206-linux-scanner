#!/bin/sh
#
# setup-naps2.sh - expose the sane-ar206 backend to the NAPS2 flatpak.
#
# NAPS2 ships its own glibc SANE stack (/app/lib/libsane.so + backends) and
# cannot dlopen the host's backend when the host libc differs (musl on
# Alpine).  Instead we run the host backend behind saned on localhost and
# point NAPS2's bundled SANE "net" backend at it.  The host's own backends
# (epsonds for the Epson) are left untouched.
#
# Works on Alpine (OpenRC / apk) and Debian/Ubuntu (systemd / apt).
# Re-runnable; safe to execute again after a NAPS2 flatpak update.
#
# If NAPS2 is installed natively (deb/AppImage) rather than as a flatpak,
# no bridge is needed at all: it uses the system SANE and sees the backend
# directly.  This script only handles the flatpak case.

set -eu

APP_ID=com.naps2.Naps2
SANE_CONF_DIR="$HOME/.var/app/$APP_ID/config/sane"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RULES_SRC="$SCRIPT_DIR/../sane/60-ar206.rules"

have() { command -v "$1" >/dev/null 2>&1; }

# ---- 1. host packages -------------------------------------------------
if ! have saned; then
    if have apk; then
        sudo apk add sane-saned sane-backend-net
    elif have apt-get; then
        # sane-utils provides saned; the net backend lives in libsane1.
        sudo apt-get update
        sudo apt-get install -y sane-utils
    else
        echo "error: neither apk nor apt-get found" >&2
        exit 1
    fi
fi

# ---- 2. USB access for the unprivileged saned user --------------------
# The node is root:lp by default (usblp owns interface 1).
if id saned >/dev/null 2>&1; then
    if have apk; then
        id -nG saned | grep -qw lp || sudo adduser saned lp
    else
        # Debian/Ubuntu: hand the node to the scanner group via udev.
        if [ -f "$RULES_SRC" ]; then
            sudo install -m 644 "$RULES_SRC" /etc/udev/rules.d/60-ar206.rules
            if have udevadm; then
                sudo udevadm control --reload
                sudo udevadm trigger
            fi
        fi
        id -nG saned | grep -qw scanner || sudo adduser saned scanner
    fi
fi

# ---- 3. allow local clients only -------------------------------------
if ! grep -qE '^[[:space:]]*127\.0\.0\.1[[:space:]]*$' /etc/sane.d/saned.conf; then
    printf '\n# Allow local clients only\nlocalhost\n127.0.0.1\n' \
        | sudo tee -a /etc/sane.d/saned.conf >/dev/null
fi

# ---- 4. start saned now and at boot ----------------------------------
if have rc-service; then
    sudo rc-update add saned default >/dev/null 2>&1 || true
    if rc-service saned status >/dev/null 2>&1; then
        sudo rc-service saned restart
    else
        sudo rc-service saned start
    fi
elif have systemctl; then
    # Debian/Ubuntu ship socket-activated saned (saned.socket).
    if systemctl list-unit-files 2>/dev/null | grep -q '^saned\.socket'; then
        sudo systemctl enable --now saned.socket
        sudo systemctl restart saned.socket
    else
        sudo systemctl enable --now saned 2>/dev/null || true
    fi
fi

# ---- 5. NAPS2 flatpak SANE config ------------------------------------
if ! have flatpak || ! flatpak info "$APP_ID" >/dev/null 2>&1; then
    echo "note: NAPS2 flatpak ($APP_ID) not found."
    echo "      Native NAPS2 uses system SANE and needs no bridge."
    exit 0
fi

APP_FILES="$(flatpak info --show-location "$APP_ID" 2>/dev/null)/files"
if [ ! -d "$APP_FILES/etc/sane.d" ]; then
    echo "error: $APP_ID SANE config not found under $APP_FILES" >&2
    exit 1
fi
mkdir -p "$SANE_CONF_DIR"
cp -a "$APP_FILES/etc/sane.d/." "$SANE_CONF_DIR/"
sed -i 's/^# *localhost$/localhost/' "$SANE_CONF_DIR/net.conf"

# ---- 6. point NAPS2's SANE at that config dir ------------------------
flatpak override --user --env=SANE_CONFIG_DIR="$SANE_CONF_DIR" "$APP_ID"

cat <<EOF
Done.

NAPS2 will now list the scanner as "bizhub 206 (net)".
Create a profile: Profile Settings -> Choose device -> bizhub 206 (net),
then pick Grayscale + 150/300/600 dpi (100 dpi and color are unsupported
by the backend).
EOF
