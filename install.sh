#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with: sudo ./install.sh" >&2
    exit 1
fi

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

install -d -m 755 /usr/local/lib/fanspeed
install -d -m 755 /usr/local/libexec
install -d -m 755 /usr/local/bin
install -d -m 755 /usr/local/share/applications
install -d -m 755 /usr/local/share/icons/hicolor/scalable/apps
install -d -m 755 /usr/share/polkit-1/actions

install -m 644 "$SOURCE_DIR/fanspeed_app.py" /usr/local/lib/fanspeed/fanspeed_app.py
install -m 755 "$SOURCE_DIR/fanspeed_helper.py" /usr/local/libexec/fanspeed-helper
install -m 755 "$SOURCE_DIR/fanspeed" /usr/local/bin/fanspeed
install -m 644 "$SOURCE_DIR/io.github.fanspeed.FanSpeed.desktop" \
    /usr/local/share/applications/io.github.fanspeed.FanSpeed.desktop
install -m 644 "$SOURCE_DIR/io.github.fanspeed.FanSpeed.svg" \
    /usr/local/share/icons/hicolor/scalable/apps/io.github.fanspeed.FanSpeed.svg
install -m 644 "$SOURCE_DIR/io.github.fanspeed.policy" \
    /usr/share/polkit-1/actions/io.github.fanspeed.policy

echo "ThinkPad Fan Control installed. Open it from the app launcher or run: fanspeed"
