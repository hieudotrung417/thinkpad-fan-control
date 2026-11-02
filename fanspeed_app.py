#!/usr/bin/python3
"""Native GTK application for controlling ThinkPad fan speed."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


APP_ID = "io.github.fanspeed.FanSpeed"
HELPER = Path("/usr/local/libexec/fanspeed-helper")
PKEXEC = "/usr/bin/pkexec"
PROC_FAN = Path("/proc/acpi/ibm/fan")
HWMON_ROOT = Path("/sys/class/hwmon")


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return None


def find_hwmon(name: str) -> Path | None:
    try:
        devices = HWMON_ROOT.glob("hwmon*")
    except OSError:
        return None
    for device in devices:
        if read_text(device / "name") == name:
            return device
    return None


def read_millidegrees(path: Path) -> float | None:
    value = read_text(path)
    try:
        return int(value) / 1000 if value is not None else None
    except ValueError:
        return None


def read_fan_state() -> dict[str, object]:
    state: dict[str, object] = {"mode": "Unavailable", "rpm": []}
    proc_state = read_text(PROC_FAN)
    if proc_state:
        fields = {}
        for line in proc_state.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        level = fields.get("level")
        if level == "auto":
            state["mode"] = "Automatic"
        elif level in {"full-speed", "disengaged"}:
            state["mode"] = "Full speed"
        elif level:
            state["mode"] = f"Manual level {level}"

    thinkpad = find_hwmon("thinkpad")
    if thinkpad:
        rpms = []
        for filename in ("fan1_input", "fan2_input"):
            value = read_text(thinkpad / filename)
            try:
                if value is not None:
                    rpms.append(int(value))
            except ValueError:
                pass
        state["rpm"] = rpms

    cpu = find_hwmon("k10temp")
    state["cpu_temp"] = read_millidegrees(cpu / "temp1_input") if cpu else None
    gpu = find_hwmon("amdgpu")
    state["gpu_temp"] = read_millidegrees(gpu / "temp1_input") if gpu else None
    return state


class FanSpeedWindow(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application, title="ThinkPad Fan Control")
        self.set_default_size(520, 480)
        self.set_resizable(False)

        header = Gtk.HeaderBar()
        title = Gtk.Label(label="ThinkPad Fan Control")
        title.add_css_class("title")
        header.set_title_widget(title)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        root.set_margin_top(24)
        root.set_margin_bottom(24)
        root.set_margin_start(24)
        root.set_margin_end(24)
        self.set_child(root)

        status_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        status_card.add_css_class("card")
        root.append(status_card)

        self.mode_label = Gtk.Label(label="Reading fan status…", xalign=0)
        self.mode_label.add_css_class("status-title")
        status_card.append(self.mode_label)

        self.rpm_label = Gtk.Label(label="Fan speed: —", xalign=0)
        status_card.append(self.rpm_label)

        self.temperature_label = Gtk.Label(label="Temperature: —", xalign=0)
        status_card.append(self.temperature_label)

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        controls.add_css_class("card")
        root.append(controls)

        heading = Gtk.Label(label="Cooling mode", xalign=0)
        heading.add_css_class("section-title")
        controls.append(heading)

        self.auto_button = Gtk.Button(label="Automatic (recommended)")
        self.auto_button.add_css_class("suggested-action")
        self.auto_button.connect("clicked", lambda _button: self.apply_mode("auto"))
        controls.append(self.auto_button)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls.append(row)
        self.level_dropdown = Gtk.DropDown.new_from_strings(
            [f"Manual level {level}" for level in range(1, 8)]
        )
        self.level_dropdown.set_selected(6)
        self.level_dropdown.set_hexpand(True)
        row.append(self.level_dropdown)

        self.apply_button = Gtk.Button(label="Apply")
        self.apply_button.connect("clicked", self.on_apply_level)
        row.append(self.apply_button)

        self.full_button = Gtk.Button(label="Full speed (maximum cooling)")
        self.full_button.connect("clicked", lambda _button: self.apply_mode("full-speed"))
        controls.append(self.full_button)

        self.message_label = Gtk.Label(xalign=0, wrap=True)
        self.message_label.add_css_class("dim-label")
        root.append(self.message_label)

        warning = Gtk.Label(
            label=(
                "Manual control remains active until you select Automatic or reboot. "
                "The app never offers fan-off mode."
            ),
            xalign=0,
            wrap=True,
        )
        warning.add_css_class("warning")
        root.append(warning)

        self.busy = False
        self.refresh_status()
        GLib.timeout_add_seconds(2, self.refresh_status)

    def on_apply_level(self, _button: Gtk.Button) -> None:
        level = self.level_dropdown.get_selected() + 1
        self.apply_mode(str(level))

    def set_controls_sensitive(self, sensitive: bool) -> None:
        self.auto_button.set_sensitive(sensitive)
        self.apply_button.set_sensitive(sensitive)
        self.full_button.set_sensitive(sensitive)
        self.level_dropdown.set_sensitive(sensitive)

    def apply_mode(self, mode: str) -> None:
        if self.busy:
            return
        if not HELPER.exists():
            self.show_error(
                "The privileged helper is not installed.",
                "Run sudo ./install.sh from the project directory, then reopen the app.",
            )
            return

        self.busy = True
        self.set_controls_sensitive(False)
        self.message_label.set_text("Waiting for authorization…")
        thread = threading.Thread(target=self.run_helper, args=(mode,), daemon=True)
        thread.start()

    def run_helper(self, mode: str) -> None:
        try:
            result = subprocess.run(
                [PKEXEC, str(HELPER), "set", mode],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0:
                try:
                    payload = json.loads(result.stdout)
                    message = payload.get("message", "Fan mode changed.")
                except json.JSONDecodeError:
                    message = "Fan mode changed."
                GLib.idle_add(self.finish_apply, True, message)
            else:
                detail = result.stderr.strip() or result.stdout.strip()
                if result.returncode in (126, 127):
                    detail = "Authorization was cancelled or denied."
                GLib.idle_add(self.finish_apply, False, detail or "The helper failed.")
        except subprocess.TimeoutExpired:
            GLib.idle_add(self.finish_apply, False, "Authorization timed out.")
        except OSError as error:
            GLib.idle_add(self.finish_apply, False, str(error))

    def finish_apply(self, succeeded: bool, message: str) -> bool:
        self.busy = False
        self.set_controls_sensitive(True)
        self.message_label.set_text(message if succeeded else "")
        if not succeeded:
            self.show_error("Could not change fan mode", message)
        self.refresh_status()
        return GLib.SOURCE_REMOVE

    def refresh_status(self) -> bool:
        state = read_fan_state()
        self.mode_label.set_text(str(state["mode"]))

        rpms = state.get("rpm", [])
        if rpms:
            rpm_text = " / ".join(f"{rpm:,} RPM" for rpm in rpms)
            self.rpm_label.set_text(f"Fans: {rpm_text}")
        else:
            self.rpm_label.set_text("Fan speed: unavailable")

        temperatures = []
        cpu_temp = state.get("cpu_temp")
        gpu_temp = state.get("gpu_temp")
        if isinstance(cpu_temp, float):
            temperatures.append(f"CPU {cpu_temp:.1f}°C")
        if isinstance(gpu_temp, float):
            temperatures.append(f"GPU {gpu_temp:.1f}°C")
        self.temperature_label.set_text(
            "Temperatures: " + ("  •  ".join(temperatures) if temperatures else "unavailable")
        )
        return GLib.SOURCE_CONTINUE

    def show_error(self, title: str, detail: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        dialog.format_secondary_text(detail)
        dialog.connect("response", lambda current, _response: current.destroy())
        dialog.present()


class FanSpeedApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"""
            .card {
                background: alpha(@theme_fg_color, 0.06);
                border-radius: 12px;
                padding: 18px;
            }
            .status-title { font-size: 20px; font-weight: 700; }
            .section-title { font-size: 16px; font-weight: 700; }
            .warning { color: #c47f00; }
            """
        )
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def do_activate(self) -> None:
        window = self.props.active_window
        if not window:
            window = FanSpeedWindow(self)
        window.present()


if __name__ == "__main__":
    raise SystemExit(FanSpeedApplication().run())
