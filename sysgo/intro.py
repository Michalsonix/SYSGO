"""First-run animation: driving car, dots, welcome, language + size selection.

Pure stdout/ANSI before the curses menu kicks in.
"""
import sys
import time
import shutil
from . import config
from . import i18n
from .ascii_art import render_big

CAR = [
    ".-'--`-._",
    "'-O---O--'",
]

CLEAR = "\033[2J\033[H"
BOLD = "\033[1m"
CYAN = "\033[1;36m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RESET = "\033[0m"


def _term():
    s = shutil.get_terminal_size((100, 30))
    return s.columns, s.lines


def _print_center(lines, top_offset=2):
    cols, rows = _term()
    sys.stdout.write(CLEAR)
    pad_top = max(1, rows // 2 - len(lines) // 2 - top_offset)
    sys.stdout.write("\n" * pad_top)
    for ln in lines:
        sys.stdout.write(ln.center(cols) + "\n")
    sys.stdout.flush()


def _draw_car(x: int):
    cols, rows = _term()
    sys.stdout.write(CLEAR)
    pad_top = max(1, rows // 2 - 1)
    sys.stdout.write("\n" * pad_top)
    for line in CAR:
        sys.stdout.write(" " * x + CYAN + line + RESET + "\n")
    sys.stdout.flush()


def _car_anim():
    cols, _ = _term()
    end = max(10, cols - 14)
    x = 0
    step = max(2, cols // 40)
    while x < end:
        _draw_car(x)
        time.sleep(0.04)
        x += step


def _dots_anim():
    cols, rows = _term()
    sys.stdout.write(CLEAR)
    pad_top = max(1, rows // 2)
    sys.stdout.write("\n" * pad_top)
    line_pos = pad_top + 1  # not strictly needed
    msg = ""
    for _ in range(3):
        msg += "."
        sys.stdout.write(CLEAR)
        sys.stdout.write("\n" * pad_top)
        sys.stdout.write(msg.center(cols) + "\n")
        sys.stdout.flush()
        time.sleep(1.0)


def _read_arrow_choice(n: int, default: int = 0) -> int:
    """Use simple stdin arrow keys; works in raw mode via tty."""
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        idx = default
        while True:
            return_idx = None
            # render is responsibility of caller; we just read.
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[D":  # left
                    idx = (idx - 1) % n
                elif seq == "[C":  # right
                    idx = (idx + 1) % n
                yield idx
            elif ch in ("\r", "\n"):
                yield -1
                return
            else:
                continue
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _choose_horizontal(title: str, options: list[str]) -> int:
    """Render N boxed options horizontally, navigate with left/right, pick with Enter."""
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sel = 0

    REVERSE = "\033[7m"

    def render():
        cols, rows = _term()
        # In raw mode '\n' is LF only (no CR) -> use '\r\n' to avoid stair-stepping.
        NL = "\r\n"
        sys.stdout.write(CLEAR)
        pad_top = max(2, rows // 2 - 5)
        sys.stdout.write(NL * pad_top)
        sys.stdout.write(BOLD + title.center(cols) + RESET + NL + NL)
        widths = [max(10, len(o) + 6) for o in options]
        gap = "   "
        total = sum(widths) + len(gap) * (len(options) - 1)
        left = max(0, (cols - total) // 2)

        top = " " * left
        mid = " " * left
        bot = " " * left
        for i, o in enumerate(options):
            w = widths[i]
            label = ("\u25b6 " + o + " \u25c0") if i == sel else o
            line_top = " " + "_" * (w - 2) + " "
            line_mid = "|" + label.center(w - 2) + "|"
            line_bot = "|" + "_" * (w - 2) + "|"
            if i == sel:
                line_top = BOLD + GREEN + line_top + RESET
                line_mid = BOLD + GREEN + REVERSE + line_mid + RESET
                line_bot = BOLD + GREEN + line_bot + RESET
            top += line_top + gap
            mid += line_mid + gap
            bot += line_bot + gap
        sys.stdout.write(top + NL + mid + NL + bot + NL)
        hint = "< \u2190  /  \u2192 >    ENTER"
        sys.stdout.write(NL + hint.center(cols) + NL)
        sys.stdout.flush()

    try:
        tty.setraw(fd)
        render()
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[D":
                    sel = (sel - 1) % len(options)
                    render()
                elif seq == "[C":
                    sel = (sel + 1) % len(options)
                    render()
            elif ch in ("\r", "\n"):
                return sel
            elif ch == "\x03":
                raise KeyboardInterrupt
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def play_intro_and_setup() -> dict:
    """Run the first-run animation. Returns final config dict."""
    cfg = config.load()

    # 1. car
    _car_anim()
    # 2. dots
    _dots_anim()
    time.sleep(2.0)

    # 3. welcome banner
    big = render_big("SYSGO")
    cols, rows = _term()
    sys.stdout.write(CLEAR)
    pad_top = max(2, rows // 2 - 8)
    sys.stdout.write("\n" * pad_top)
    for ln in big:
        sys.stdout.write(CYAN + ln.center(cols) + RESET + "\n")
    sys.stdout.write("\n")
    sys.stdout.write(BOLD + "Welcome to the SYSGO!".center(cols) + RESET + "\n")
    sys.stdout.write("Get started".center(cols) + "\n")
    sys.stdout.flush()
    time.sleep(1.5)

    # 4. language pick
    sel = _choose_horizontal("Language:", i18n.LANGS)
    lang_name = i18n.LANGS[sel]
    cfg["lang"] = i18n.LANG_CODES[lang_name]

    # 5. size pick (in chosen language)
    code = cfg["lang"]
    options = [i18n.tr(code, "small"), i18n.tr(code, "medium"), i18n.tr(code, "large")]
    sel = _choose_horizontal(i18n.tr(code, "menu_size"), options)
    cfg["size"] = ["small", "medium", "large"][sel]

    # 6. countdown
    for txt in [i18n.tr(code, "ready"), i18n.tr(code, "go"), i18n.tr(code, "sysgo")]:
        cols, rows = _term()
        sys.stdout.write(CLEAR)
        pad_top = max(2, rows // 2 - 3)
        sys.stdout.write("\n" * pad_top)
        big = render_big(txt.rstrip("!").rstrip("?"))
        for ln in big:
            sys.stdout.write(GREEN + ln.center(cols) + RESET + "\n")
        sys.stdout.flush()
        time.sleep(1.0 if txt != i18n.tr(code, "sysgo") else 2.0)

    config.save(cfg)
    config.mark_first_run_done()
    return cfg
