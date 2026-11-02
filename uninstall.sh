#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this uninstaller with: sudo ./uninstall.sh" >&2
    exit 1
fi

if [ "$#" -ne 0 ]; then
    echo "Usage: sudo ./uninstall.sh" >&2
    exit 2
fi

HELPER=/usr/local/libexec/fanspeed-helper

# The launcher replaces itself with exactly this command. The anchored pattern
# avoids stopping unrelated Python programs or development copies of the app.
if command -v pkill >/dev/null 2>&1; then
    pkill -TERM -f \
        '^/usr/bin/python3 /usr/local/lib/fanspeed/fanspeed_app.py([[:space:]]|$)' \
        2>/dev/null || true
fi

# Do not leave a manually selected fan level active after removing the UI.
if [ -x "$HELPER" ]; then
    if "$HELPER" set auto >/dev/null 2>&1; then
        echo "Restored automatic firmware fan control."
    else
        echo "Warning: automatic fan control could not be confirmed." >&2
        echo "Reboot to ensure the firmware regains fan control." >&2
    fi
fi

rm -f /usr/local/bin/fanspeed
rm -f /usr/local/libexec/fanspeed-helper
rm -f /usr/local/share/applications/io.github.fanspeed.FanSpeed.desktop
rm -f /usr/local/share/icons/hicolor/scalable/apps/io.github.fanspeed.FanSpeed.svg
rm -f /usr/share/polkit-1/actions/io.github.fanspeed.policy
rm -f /usr/local/sbin/fanspeed-uninstall
rm -rf /usr/local/lib/fanspeed

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/local/share/applications >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/local/share/icons/hicolor \
        >/dev/null 2>&1 || true
fi

echo "ThinkPad Fan Control has been completely removed."
echo "Shared GTK and AppIndicator system packages were kept for other applications."
