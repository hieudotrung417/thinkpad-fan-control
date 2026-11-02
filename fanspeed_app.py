#!/usr/bin/python3
"""Native GTK application and tray menu for controlling ThinkPad fan speed."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

MODERN_INDICATOR = False
try:
    # GNOME's AppIndicator extension consumes com.canonical.dbusmenu, which is
    # exported by the GTK binding. Prefer it over the newer GLib-only binding,
    # whose org.gtk.Menus export currently produces a display-only indicator.
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
except (ImportError, ValueError):
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator  # type: ignore  # noqa: E402
    except (ImportError, ValueError):
        try:
            gi.require_version("AyatanaAppIndicatorGlib", "2.0")
            from gi.repository import AyatanaAppIndicatorGlib as AppIndicator  # type: ignore  # noqa: E402

            MODERN_INDICATOR = True
        except (ImportError, ValueError):
            AppIndicator = None  # type: ignore


APP_ID = "io.github.fanspeed.FanSpeed"
HELPER = Path("/usr/local/libexec/fanspeed-helper")
PKEXEC = "/usr/bin/pkexec"
PROC_FAN = Path("/proc/acpi/ibm/fan")
HWMON_ROOT = Path("/sys/class/hwmon")


def add_css_class(widget: Gtk.Widget, class_name: str) -> None:
    widget.get_style_context().add_class(class_name)


def privileged_helper_command(*arguments: str) -> list[str]:
    """Build the pkexec command for an installed app or a standalone AppImage."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return [PKEXEC, str(Path(appimage).resolve()), "--fan-helper", *arguments]
    return [PKEXEC, str(HELPER), *arguments]


def configure_appimage_icon_path(indicator: object) -> None:
    """Let the desktop shell resolve an icon stored inside the AppImage."""
    appdir = os.environ.get("APPDIR")
    if appdir:
        icon_path = Path(appdir) / "usr/share/icons/hicolor/scalable/apps"
        indicator.set_icon_theme_path(str(icon_path))


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


def tray_status(state: dict[str, object]) -> tuple[str, str, str | None]:
    """Return the panel label, menu status text, and selected menu mode."""
    mode = str(state.get("mode", "Unavailable"))
    selected_mode = None
    short_mode = "?"
    if mode == "Automatic":
        selected_mode = "auto"
        short_mode = "A"
    elif mode == "Full speed":
        selected_mode = "full-speed"
        short_mode = "MAX"
    elif mode.startswith("Manual level "):
        level = mode.removeprefix("Manual level ")
        if level in {str(number) for number in range(1, 8)}:
            selected_mode = level
            short_mode = level

    details = [mode]
    rpms = state.get("rpm", [])
    if isinstance(rpms, list) and rpms:
        details.append(" / ".join(f"{rpm:,} RPM" for rpm in rpms))

    temperatures = []
    for name, key in (("CPU", "cpu_temp"), ("GPU", "gpu_temp")):
        temperature = state.get(key)
        if isinstance(temperature, float):
            temperatures.append(f"{name} {temperature:.1f}°C")
    if temperatures:
        details.append(" / ".join(temperatures))
    return short_mode, "  •  ".join(details), selected_mode


class FanSessionError(RuntimeError):
    pass


class PrivilegedFanSession:
    """One authenticated helper process, private to this application instance."""

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _open_locked(self) -> None:
        if self.ready:
            return
        self.close_locked()
        try:
            process = subprocess.Popen(
                privileged_helper_command("serve"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            raise FanSessionError(str(error)) from error
        self.process = process
        assert process.stdout is not None
        ready_line = process.stdout.readline()
        if not ready_line:
            returncode = process.wait()
            detail = process.stderr.read().strip() if process.stderr else ""
            self.process = None
            if returncode in (126, 127):
                detail = "Authorization was cancelled or denied."
            raise FanSessionError(detail or "The privileged helper did not start.")
        try:
            response = json.loads(ready_line)
        except json.JSONDecodeError as error:
            self.close_locked()
            raise FanSessionError("The privileged helper returned invalid data.") from error
        if response != {"ready": True}:
            self.close_locked()
            raise FanSessionError("The privileged helper did not become ready.")

    def open(self) -> None:
        with self.lock:
            self._open_locked()

    def set_mode(self, mode: str) -> str:
        with self.lock:
            self._open_locked()
            process = self.process
            assert process is not None and process.stdin is not None
            assert process.stdout is not None
            try:
                process.stdin.write(json.dumps({"mode": mode}) + "\n")
                process.stdin.flush()
                response_line = process.stdout.readline()
            except (BrokenPipeError, OSError) as error:
                self.close_locked()
                raise FanSessionError("The privileged helper session ended.") from error
            if not response_line:
                self.close_locked()
                raise FanSessionError("The privileged helper session ended.")
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as error:
                raise FanSessionError("The privileged helper returned invalid data.") from error
            if not response.get("ok"):
                raise FanSessionError(response.get("error", "The helper failed."))
            return response.get("message", "Fan mode changed.")

    def close_locked(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()

    def close(self) -> None:
        # If startup authentication is still pending, wake the thread blocked
        # on the helper's first response before waiting for its lock.
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        with self.lock:
            self.close_locked()


class FanSpeedWindow(Gtk.ApplicationWindow):
    def __init__(self, application: "FanSpeedApplication") -> None:
        super().__init__(application=application, title="ThinkPad Fan Control")
        self.set_default_size(520, 480)
        self.set_resizable(False)
        self.connect("delete-event", self.on_delete_event)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        title = Gtk.Label(label="ThinkPad Fan Control")
        add_css_class(title, "title")
        header.set_custom_title(title)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        root.set_margin_top(24)
        root.set_margin_bottom(24)
        root.set_margin_start(24)
        root.set_margin_end(24)
        self.add(root)

        status_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        add_css_class(status_card, "card")
        root.pack_start(status_card, False, False, 0)

        self.mode_label = Gtk.Label(label="Reading fan status…", xalign=0)
        add_css_class(self.mode_label, "status-title")
        status_card.pack_start(self.mode_label, False, False, 0)

        self.rpm_label = Gtk.Label(label="Fan speed: —", xalign=0)
        status_card.pack_start(self.rpm_label, False, False, 0)

        self.temperature_label = Gtk.Label(label="Temperature: —", xalign=0)
        status_card.pack_start(self.temperature_label, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        add_css_class(controls, "card")
        root.pack_start(controls, False, False, 0)

        heading = Gtk.Label(label="Cooling mode", xalign=0)
        add_css_class(heading, "section-title")
        controls.pack_start(heading, False, False, 0)

        self.auto_button = Gtk.Button(label="Automatic (recommended)")
        add_css_class(self.auto_button, "suggested-action")
        self.auto_button.connect("clicked", lambda _button: self.apply_mode("auto"))
        controls.pack_start(self.auto_button, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls.pack_start(row, False, False, 0)
        self.level_dropdown = Gtk.ComboBoxText()
        for level in range(1, 8):
            self.level_dropdown.append_text(f"Manual level {level}")
        self.level_dropdown.set_active(6)
        self.level_dropdown.set_hexpand(True)
        row.pack_start(self.level_dropdown, True, True, 0)

        self.apply_button = Gtk.Button(label="Apply")
        self.apply_button.connect("clicked", self.on_apply_level)
        row.pack_start(self.apply_button, False, False, 0)

        self.full_button = Gtk.Button(label="Full speed (maximum cooling)")
        self.full_button.connect("clicked", lambda _button: self.apply_mode("full-speed"))
        controls.pack_start(self.full_button, False, False, 0)

        self.message_label = Gtk.Label(xalign=0, wrap=True)
        add_css_class(self.message_label, "dim-label")
        root.pack_start(self.message_label, False, False, 0)

        warning = Gtk.Label(
            label=(
                "Manual control remains active until you select Automatic or reboot. "
                "The app never offers fan-off mode."
            ),
            xalign=0,
            wrap=True,
        )
        add_css_class(warning, "warning")
        root.pack_start(warning, False, False, 0)

        self.busy = False
        self.refresh_status()
        GLib.timeout_add_seconds(2, self.refresh_status)
        if os.environ.get("APPIMAGE") or HELPER.exists():
            self.begin_authorization()

    def on_apply_level(self, _button: Gtk.Button) -> None:
        level = self.level_dropdown.get_active() + 1
        self.apply_mode(str(level))

    def on_delete_event(self, _window: Gtk.Window, _event: Gdk.Event) -> bool:
        self.hide()
        self.message_label.set_text("Still running in the status bar.")
        return True

    def set_controls_sensitive(self, sensitive: bool) -> None:
        self.auto_button.set_sensitive(sensitive)
        self.apply_button.set_sensitive(sensitive)
        self.full_button.set_sensitive(sensitive)
        self.level_dropdown.set_sensitive(sensitive)
        self.get_application().set_tray_controls_sensitive(sensitive)

    def apply_mode(self, mode: str) -> None:
        if self.busy:
            return
        if not os.environ.get("APPIMAGE") and not HELPER.exists():
            self.show_error(
                "The privileged helper is not installed.",
                "Run sudo ./install.sh from the project directory, then reopen the app.",
            )
            return

        self.busy = True
        self.set_controls_sensitive(False)
        self.message_label.set_text(
            "Changing fan mode…"
            if self.get_application().fan_session.ready
            else "Waiting for authorization…"
        )
        thread = threading.Thread(target=self.run_helper, args=(mode,), daemon=True)
        thread.start()

    def begin_authorization(self) -> None:
        if self.busy or self.get_application().fan_session.ready:
            return
        self.busy = True
        self.set_controls_sensitive(False)
        self.message_label.set_text("Authorize once to unlock fan control for this session…")
        threading.Thread(target=self.run_authorization, daemon=True).start()

    def run_authorization(self) -> None:
        try:
            self.get_application().fan_session.open()
            GLib.idle_add(self.finish_authorization, True, "Fan control unlocked.")
        except FanSessionError as error:
            GLib.idle_add(self.finish_authorization, False, str(error))

    def finish_authorization(self, succeeded: bool, message: str) -> bool:
        self.busy = False
        self.set_controls_sensitive(True)
        self.message_label.set_text(
            message if succeeded else "Fan control is locked. Select a mode to retry."
        )
        return GLib.SOURCE_REMOVE

    def run_helper(self, mode: str) -> None:
        try:
            message = self.get_application().fan_session.set_mode(mode)
            GLib.idle_add(self.finish_apply, True, message)
        except FanSessionError as error:
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
        self.get_application().update_tray(state)
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
        dialog.show()


class FanSpeedApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.indicator = None
        self.status_icon = None
        self.tray_menu: Gtk.Menu | None = None
        self.status_item: Gtk.MenuItem | None = None
        self.quit_item: Gtk.MenuItem | None = None
        self.mode_items: dict[str, Gtk.RadioMenuItem] = {}
        self.gio_status_menu: Gio.Menu | None = None
        self.gio_mode_action: Gio.SimpleAction | None = None
        self.gio_quit_action: Gio.SimpleAction | None = None
        self.updating_tray = False
        self.fan_session = PrivilegedFanSession()

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.hold()
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
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        self.create_tray()

    def create_tray(self) -> None:
        if MODERN_INDICATOR:
            self.create_modern_tray()
        else:
            self.create_legacy_tray()

    def create_modern_tray(self) -> None:
        actions = Gio.SimpleActionGroup.new()

        status_action = Gio.SimpleAction.new("status", None)
        status_action.set_enabled(False)
        actions.add_action(status_action)

        self.gio_mode_action = Gio.SimpleAction.new_stateful(
            "mode",
            GLib.VariantType.new("s"),
            GLib.Variant.new_string(""),
        )
        self.gio_mode_action.connect("activate", self.on_gio_mode_activate)
        actions.add_action(self.gio_mode_action)

        show_action = Gio.SimpleAction.new("show", None)
        show_action.connect("activate", lambda _action, _value: self.activate())
        actions.add_action(show_action)

        self.gio_quit_action = Gio.SimpleAction.new("quit", None)
        self.gio_quit_action.connect("activate", lambda _action, _value: self.on_quit(None))
        actions.add_action(self.gio_quit_action)

        menu = Gio.Menu.new()
        self.gio_status_menu = Gio.Menu.new()
        self.set_gio_status_label("Reading fan status…")
        menu.append_section(None, self.gio_status_menu)

        modes = Gio.Menu.new()
        choices = [
            ("auto", "Automatic (recommended)"),
            *((str(level), f"Manual level {level}") for level in range(1, 8)),
            ("full-speed", "Full speed (maximum cooling)"),
        ]
        for mode, label in choices:
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(
                "indicator.mode", GLib.Variant.new_string(mode)
            )
            modes.append_item(item)
        menu.append_section(None, modes)

        application = Gio.Menu.new()
        application.append("Open Fan Control", "indicator.show")
        application.append("Quit", "indicator.quit")
        menu.append_section(None, application)

        self.indicator = AppIndicator.Indicator.new(
            APP_ID,
            APP_ID,
            AppIndicator.IndicatorCategory.HARDWARE,
        )
        configure_appimage_icon_path(self.indicator)
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("ThinkPad Fan Control")
        self.indicator.set_menu(menu)
        self.indicator.set_actions(actions)

    def set_gio_status_label(self, label: str) -> None:
        if self.gio_status_menu is None:
            return
        self.gio_status_menu.remove_all()
        self.gio_status_menu.append(label, "indicator.status")

    def on_gio_mode_activate(
        self, _action: Gio.SimpleAction, value: GLib.Variant | None
    ) -> None:
        if value is not None:
            self.get_fan_window().apply_mode(value.get_string())

    def create_legacy_tray(self) -> None:
        menu = Gtk.Menu()
        self.tray_menu = menu

        self.status_item = Gtk.MenuItem(label="Reading fan status…")
        self.status_item.set_sensitive(False)
        menu.append(self.status_item)
        menu.append(Gtk.SeparatorMenuItem())

        choices = [
            ("auto", "Automatic (recommended)"),
            *((str(level), f"Manual level {level}") for level in range(1, 8)),
            ("full-speed", "Full speed (maximum cooling)"),
        ]
        self.updating_tray = True
        first_item = None
        for mode, label in choices:
            if first_item is None:
                item = Gtk.RadioMenuItem.new_with_label(None, label)
                first_item = item
            else:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(first_item, label)
            item.connect("toggled", self.on_tray_mode_toggled, mode)
            menu.append(item)
            self.mode_items[mode] = item
        self.updating_tray = False

        menu.append(Gtk.SeparatorMenuItem())
        show_item = Gtk.MenuItem(label="Open Fan Control")
        show_item.connect("activate", lambda _item: self.activate())
        menu.append(show_item)

        self.quit_item = Gtk.MenuItem(label="Quit")
        self.quit_item.connect("activate", self.on_quit)
        menu.append(self.quit_item)
        menu.show_all()

        if AppIndicator is not None:
            self.indicator = AppIndicator.Indicator.new(
                APP_ID,
                APP_ID,
                AppIndicator.IndicatorCategory.HARDWARE,
            )
            configure_appimage_icon_path(self.indicator)
            self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
            self.indicator.set_title("ThinkPad Fan Control")
            self.indicator.set_menu(menu)
        else:
            # Useful on Xfce/MATE and other panels which still support XEmbed.
            self.status_icon = Gtk.StatusIcon.new_from_icon_name(APP_ID)
            self.status_icon.set_title("ThinkPad Fan Control")
            self.status_icon.set_tooltip_text("ThinkPad Fan Control")
            self.status_icon.connect("activate", lambda _icon: self.activate())
            self.status_icon.connect("popup-menu", self.on_status_icon_popup)
            self.status_icon.set_visible(True)

    def on_status_icon_popup(
        self, icon: Gtk.StatusIcon, button: int, activate_time: int
    ) -> None:
        if self.tray_menu is not None:
            self.tray_menu.popup(
                None,
                None,
                Gtk.StatusIcon.position_menu,
                icon,
                button,
                activate_time,
            )

    def on_tray_mode_toggled(self, item: Gtk.RadioMenuItem, mode: str) -> None:
        if self.updating_tray or not item.get_active():
            return
        window = self.get_fan_window()
        window.apply_mode(mode)

    def set_tray_controls_sensitive(self, sensitive: bool) -> None:
        if self.gio_mode_action is not None:
            self.gio_mode_action.set_enabled(sensitive)
        if self.gio_quit_action is not None:
            self.gio_quit_action.set_enabled(sensitive)
        for item in self.mode_items.values():
            item.set_sensitive(sensitive)
        if self.quit_item is not None:
            self.quit_item.set_sensitive(sensitive)
        if not sensitive and self.status_item is not None:
            self.status_item.set_label("Changing fan mode…")
        if not sensitive:
            self.set_gio_status_label("Changing fan mode…")

    def update_tray(self, state: dict[str, object]) -> None:
        short_mode, details, selected_mode = tray_status(state)
        if self.status_item is not None:
            self.status_item.set_label(details)
        self.set_gio_status_label(details)

        tooltip = f"ThinkPad Fan Control — {details}"
        if self.indicator is not None:
            self.indicator.set_label(short_mode, "MAX")
            self.indicator.set_title(tooltip)
            if MODERN_INDICATOR:
                self.indicator.set_tooltip(APP_ID, "ThinkPad Fan Control", details)
        elif self.status_icon is not None:
            self.status_icon.set_tooltip_text(tooltip)

        if selected_mode is not None and self.gio_mode_action is not None:
            self.gio_mode_action.set_state(GLib.Variant.new_string(selected_mode))
        if selected_mode in self.mode_items:
            self.updating_tray = True
            self.mode_items[selected_mode].set_active(True)
            self.updating_tray = False

    def get_fan_window(self) -> FanSpeedWindow:
        for window in self.get_windows():
            if isinstance(window, FanSpeedWindow):
                return window
        return FanSpeedWindow(self)

    def on_quit(self, _item: Gtk.MenuItem | None) -> None:
        for window in self.get_windows():
            window.destroy()
        self.quit()

    def do_activate(self) -> None:
        window = self.get_fan_window()
        window.show_all()
        window.present()

    def do_shutdown(self) -> None:
        self.fan_session.close()
        Gtk.Application.do_shutdown(self)


if __name__ == "__main__":
    raise SystemExit(FanSpeedApplication().run())
