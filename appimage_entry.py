#!/usr/bin/python3
"""Entry point that keeps the privileged AppImage path narrow."""

from __future__ import annotations

import sys


def main(arguments: list[str]) -> int:
    if arguments[:1] == ["--fan-helper"]:
        from fanspeed_helper import main as helper_main

        return helper_main(arguments[1:])

    from fanspeed_app import FanSpeedApplication

    return FanSpeedApplication().run([sys.argv[0], *arguments])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
