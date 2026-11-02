#!/usr/bin/python3
"""Narrow root helper for the ThinkPad fan control application."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


PROC_FAN = Path("/proc/acpi/ibm/fan")
FAN_CONTROL = Path("/sys/module/thinkpad_acpi/parameters/fan_control")
MODPROBE = "/usr/sbin/modprobe"
VALID_MODES = {"auto", "full-speed", *(str(level) for level in range(1, 8))}


class ControlError(RuntimeError):
    pass


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def fan_control_enabled() -> bool:
    return read_text(FAN_CONTROL) in {"Y", "1"}


def run_modprobe(*arguments: str) -> None:
    try:
        result = subprocess.run(
            [MODPROBE, *arguments], capture_output=True, text=True, check=False
        )
    except OSError as error:
        raise ControlError(f"Could not run modprobe: {error}") from error
    if result.returncode != 0:
        raise ControlError(result.stderr.strip() or "Could not reload thinkpad_acpi.")


def enable_manual_control() -> None:
    if fan_control_enabled():
        return
    run_modprobe("-r", "thinkpad_acpi")
    try:
        run_modprobe("thinkpad_acpi", "fan_control=1")
    except ControlError:
        # Restore the normal driver if loading with manual control fails.
        run_modprobe("thinkpad_acpi")
        raise
    for _attempt in range(20):
        if PROC_FAN.exists() and fan_control_enabled():
            return
        time.sleep(0.05)
    raise ControlError("thinkpad_acpi reloaded, but manual fan control is unavailable.")


def write_mode(mode: str) -> str:
    if mode not in VALID_MODES:
        raise ControlError("Invalid fan mode.")

    if mode == "auto" and not fan_control_enabled():
        return "Automatic firmware control is already active."

    if mode != "auto":
        enable_manual_control()

    if not PROC_FAN.exists():
        raise ControlError("This device does not expose the ThinkPad fan interface.")

    command = f"level {mode}\n"
    try:
        with PROC_FAN.open("w") as fan:
            fan.write(command)
    except OSError as error:
        raise ControlError(f"Could not set fan mode: {error}") from error

    if mode == "auto":
        return "Automatic fan control restored."
    if mode == "full-speed":
        return "Full-speed cooling enabled."
    return f"Manual fan level {mode} enabled."


def serve(input_stream: object = sys.stdin, output_stream: object = sys.stdout) -> int:
    """Serve validated mode changes over private inherited standard-I/O pipes."""
    print(json.dumps({"ready": True}), file=output_stream, flush=True)
    for line in input_stream:
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) != {"mode"}:
                raise ControlError("Invalid helper request.")
            mode = request["mode"]
            if not isinstance(mode, str):
                raise ControlError("Invalid fan mode.")
            message = write_mode(mode)
            response = {"ok": True, "message": message}
        except (ControlError, json.JSONDecodeError) as error:
            response = {"ok": False, "error": str(error)}
        print(json.dumps(response), file=output_stream, flush=True)
    return 0


def main(arguments: list[str]) -> int:
    if os.geteuid() != 0:
        print("This helper must be run through pkexec.", file=sys.stderr)
        return 1
    if arguments == ["serve"]:
        return serve()
    if len(arguments) != 2 or arguments[0] != "set":
        print(
            "Usage: fanspeed-helper {serve|set {auto|1..7|full-speed}}",
            file=sys.stderr,
        )
        return 2
    try:
        message = write_mode(arguments[1])
    except ControlError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "message": message}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
