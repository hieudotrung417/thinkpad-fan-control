import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import gi

import fanspeed_app
import fanspeed_helper
import appimage_entry


try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    LEGACY_INDICATOR_AVAILABLE = True
except ValueError:
    LEGACY_INDICATOR_AVAILABLE = False


class FanSpeedAppTests(unittest.TestCase):
    def test_appimage_uses_itself_as_the_privileged_helper(self):
        with patch.dict(
            "os.environ", {"APPIMAGE": "/tmp/ThinkPad Fan Control.AppImage"}, clear=False
        ):
            self.assertEqual(
                fanspeed_app.privileged_helper_command("serve"),
                [
                    "/usr/bin/pkexec",
                    "/tmp/ThinkPad Fan Control.AppImage",
                    "--fan-helper",
                    "serve",
                ],
            )

    def test_privileged_session_reuses_one_helper_for_multiple_changes(self):
        responses = io.StringIO(
            "\n".join(
                (
                    json.dumps({"ready": True}),
                    json.dumps({"ok": True, "message": "Level 3"}),
                    json.dumps({"ok": True, "message": "Automatic"}),
                    "",
                )
            )
        )
        process = Mock(
            stdin=io.StringIO(),
            stdout=responses,
            stderr=io.StringIO(),
        )
        process.poll.return_value = None
        session = fanspeed_app.PrivilegedFanSession()
        with patch.object(fanspeed_app.subprocess, "Popen", return_value=process) as popen:
            self.assertEqual(session.set_mode("3"), "Level 3")
            self.assertEqual(session.set_mode("auto"), "Automatic")
        popen.assert_called_once()
        self.assertEqual(
            process.stdin.getvalue().splitlines(),
            [json.dumps({"mode": "3"}), json.dumps({"mode": "auto"})],
        )

    def test_helper_server_validates_every_request(self):
        input_stream = io.StringIO(
            json.dumps({"mode": "4"}) + "\n" + json.dumps({"mode": "0"}) + "\n"
        )
        output_stream = io.StringIO()

        def validate(mode: str) -> str:
            if mode == "0":
                raise fanspeed_helper.ControlError("Invalid fan mode.")
            return "Level 4"

        with patch.object(fanspeed_helper, "write_mode", side_effect=validate) as write:
            self.assertEqual(fanspeed_helper.serve(input_stream, output_stream), 0)
        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual(responses[0], {"ready": True})
        self.assertEqual(responses[1], {"ok": True, "message": "Level 4"})
        self.assertEqual(responses[2], {"ok": False, "error": "Invalid fan mode."})
        self.assertEqual(write.call_count, 2)

    def test_appimage_helper_entrypoint_delegates_only_helper_arguments(self):
        with patch.object(fanspeed_helper, "main", return_value=17) as helper_main:
            self.assertEqual(appimage_entry.main(["--fan-helper", "set", "5"]), 17)
        helper_main.assert_called_once_with(["set", "5"])

    def test_appimage_exposes_its_bundled_icon_to_the_tray_host(self):
        indicator = Mock()
        with patch.dict("os.environ", {"APPDIR": "/tmp/fanspeed.AppDir"}, clear=False):
            fanspeed_app.configure_appimage_icon_path(indicator)
        indicator.set_icon_theme_path.assert_called_once_with(
            "/tmp/fanspeed.AppDir/usr/share/icons/hicolor/scalable/apps"
        )

    @unittest.skipUnless(
        LEGACY_INDICATOR_AVAILABLE,
        "The DBusMenu-compatible AppIndicator binding is not installed.",
    )
    def test_prefers_dbusmenu_backend_for_interactive_gnome_menu(self):
        self.assertFalse(fanspeed_app.MODERN_INDICATOR)

    def test_formats_automatic_tray_status(self):
        state = {
            "mode": "Automatic",
            "rpm": [2400, 2300],
            "cpu_temp": 57.5,
            "gpu_temp": None,
        }
        short_mode, details, selected_mode = fanspeed_app.tray_status(state)
        self.assertEqual(short_mode, "A")
        self.assertEqual(selected_mode, "auto")
        self.assertIn("2,400 RPM / 2,300 RPM", details)
        self.assertIn("CPU 57.5°C", details)

    def test_formats_manual_and_full_speed_tray_modes(self):
        self.assertEqual(
            fanspeed_app.tray_status({"mode": "Manual level 4", "rpm": []}),
            ("4", "Manual level 4", "4"),
        )
        self.assertEqual(
            fanspeed_app.tray_status({"mode": "Full speed", "rpm": []}),
            ("MAX", "Full speed", "full-speed"),
        )

    def test_reads_hwmon_temperature(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / "hwmon0"
            device.mkdir()
            (device / "name").write_text("k10temp\n")
            (device / "temp1_input").write_text("57500\n")
            with patch.object(fanspeed_app, "HWMON_ROOT", root):
                found = fanspeed_app.find_hwmon("k10temp")
                self.assertEqual(found, device)
                self.assertEqual(fanspeed_app.read_millidegrees(found / "temp1_input"), 57.5)

    def test_helper_rejects_unsafe_modes(self):
        with self.assertRaises(fanspeed_helper.ControlError):
            fanspeed_helper.write_mode("0")
        with self.assertRaises(fanspeed_helper.ControlError):
            fanspeed_helper.write_mode("99")

    def test_auto_does_not_reload_module_when_control_is_disabled(self):
        with patch.object(fanspeed_helper, "fan_control_enabled", return_value=False):
            self.assertEqual(
                fanspeed_helper.write_mode("auto"),
                "Automatic firmware control is already active.",
            )

    def test_manual_level_writes_validated_kernel_command(self):
        with tempfile.TemporaryDirectory() as directory:
            interface = Path(directory) / "fan"
            interface.touch()
            with (
                patch.object(fanspeed_helper, "PROC_FAN", interface),
                patch.object(fanspeed_helper, "enable_manual_control"),
            ):
                message = fanspeed_helper.write_mode("7")
            self.assertEqual(interface.read_text(), "level 7\n")
            self.assertEqual(message, "Manual fan level 7 enabled.")

    def test_auto_writes_restore_command_when_manual_control_is_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            interface = Path(directory) / "fan"
            interface.touch()
            with (
                patch.object(fanspeed_helper, "PROC_FAN", interface),
                patch.object(fanspeed_helper, "fan_control_enabled", return_value=True),
            ):
                message = fanspeed_helper.write_mode("auto")
            self.assertEqual(interface.read_text(), "level auto\n")
            self.assertEqual(message, "Automatic fan control restored.")


if __name__ == "__main__":
    unittest.main()
