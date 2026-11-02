#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with: sudo ./install.sh" >&2
    exit 1
fi

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

NEEDS_GUI_PACKAGES=0
if ! /usr/bin/python3 -c \
    'import gi; gi.require_version("Gtk", "3.0")' 2>/dev/null; then
    NEEDS_GUI_PACKAGES=1
fi
if ! /usr/bin/python3 -c \
    'import gi; gi.require_version("AyatanaAppIndicator3", "0.1")' 2>/dev/null && \
   ! /usr/bin/python3 -c \
    'import gi; gi.require_version("AppIndicator3", "0.1")' 2>/dev/null; then
    NEEDS_GUI_PACKAGES=1
fi

if [ "$NEEDS_GUI_PACKAGES" -eq 1 ]; then
    if command -v apt-get >/dev/null 2>&1; then
        echo "Installing the Linux status-bar integration..."
        apt-get install -y gir1.2-ayatanaappindicator3-0.1 gir1.2-gtk-3.0 python3-gi
    else
        echo "AyatanaAppIndicator3 is required for the status-bar menu." >&2
        echo "Install its GTK 3 GObject-introspection package, then run this installer again." >&2
        exit 1
    fi
fi

# Stop an installed copy so the next launch cannot keep using old Python code.
if command -v pkill >/dev/null 2>&1; then
    pkill -TERM -f \
        '^/usr/bin/python3 /usr/local/lib/fanspeed/fanspeed_app.py([[:space:]]|$)' \
        2>/dev/null || true
fi

install -d -m 755 /usr/local/lib/fanspeed
install -d -m 755 /usr/local/libexec
install -d -m 755 /usr/local/bin
install -d -m 755 /usr/local/sbin
install -d -m 755 /usr/local/share/applications
install -d -m 755 /usr/local/share/icons/hicolor/scalable/apps
install -d -m 755 /usr/share/polkit-1/actions

install -m 644 "$SOURCE_DIR/fanspeed_app.py" /usr/local/lib/fanspeed/fanspeed_app.py
install -m 755 "$SOURCE_DIR/fanspeed_helper.py" /usr/local/libexec/fanspeed-helper
install -m 755 "$SOURCE_DIR/fanspeed" /usr/local/bin/fanspeed
install -m 755 "$SOURCE_DIR/uninstall.sh" /usr/local/sbin/fanspeed-uninstall
install -m 644 "$SOURCE_DIR/io.github.fanspeed.FanSpeed.desktop" \
    /usr/local/share/applications/io.github.fanspeed.FanSpeed.desktop
install -m 644 "$SOURCE_DIR/io.github.fanspeed.FanSpeed.svg" \
    /usr/local/share/icons/hicolor/scalable/apps/io.github.fanspeed.FanSpeed.svg
install -m 644 "$SOURCE_DIR/io.github.fanspeed.policy" \
    /usr/share/polkit-1/actions/io.github.fanspeed.policy

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/local/share/applications >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/local/share/icons/hicolor \
        >/dev/null 2>&1 || true
fi

echo "ThinkPad Fan Control installed. Open it from the app launcher or run: fanspeed"
echo "Close the window to keep it in the status bar; use the tray menu to quit."
echo "To remove it later, run: sudo fanspeed-uninstall"
