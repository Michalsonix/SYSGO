#!/usr/bin/env python3
"""SYSGO entry point. Installed as /usr/local/bin/sysgo (via autorun.py)."""
import os
import sys

# Allow running directly from source dir during development.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from sysgo import config, intro, menu, i18n  # noqa: E402


def require_root():
    if os.geteuid() != 0:
        # Use saved language if available, otherwise English.
        cfg = config.load()
        code = cfg.get("lang", "en")
        msg = i18n.tr(code, "need_sudo")
        sys.stderr.write("\n\033[1;31m" + msg + "\033[0m\n\n")
        sys.exit(1)


def main():
    require_root()
    if config.is_first_run():
        try:
            intro.play_intro_and_setup()
        except KeyboardInterrupt:
            sys.exit(130)
    menu.launch()


if __name__ == "__main__":
    main()
