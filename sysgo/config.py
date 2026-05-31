"""Persistent config (system-wide)."""
import json
from pathlib import Path

CONFIG_DIR = Path("/etc/sysgo")
CONFIG_FILE = CONFIG_DIR / "config.json"
FIRST_RUN = CONFIG_DIR / "first_run_done"

DEFAULTS = {
    "lang": "en",       # pl | en | no
    "size": "medium",   # small | medium | large
}


def load() -> dict:
    if not CONFIG_FILE.exists():
        return dict(DEFAULTS)
    try:
        d = json.loads(CONFIG_FILE.read_text())
        return {**DEFAULTS, **d}
    except Exception:
        return dict(DEFAULTS)


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def mark_first_run_done() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FIRST_RUN.write_text("ok\n")


def is_first_run() -> bool:
    return not FIRST_RUN.exists()


def reset_first_run() -> None:
    if FIRST_RUN.exists():
        FIRST_RUN.unlink()
