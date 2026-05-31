"""Main SYSGO dashboard (curses).

Left panel: hostname, user, up to 3 interfaces, services.
Right panel: live process list (btop-like).
Bottom: 2 rows of 4 action buttons each.

Navigation:
  arrows  - move between buttons
  TAB     - toggle focus to process list
  ENTER   - activate button / focus action
  ESC     - back / exit confirm
  In process list: F=filter, T=terminate, K=kill, arrows scroll.
"""
from __future__ import annotations
import curses
import time
from typing import List, Dict

from . import config, i18n
from . import system_info as si
from .ascii_art import render_big


# Status colors for services
COL_DEFAULT = 1
COL_TITLE = 2
COL_OK = 3       # green - running fine
COL_WARN = 4     # yellow - running with warning
COL_ERR = 5      # red - down
COL_HALF = 6     # mixed (we'll print two halves)
COL_FOCUS = 7
COL_BTN = 8
COL_BTN_SEL = 9
COL_HINT = 10


def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COL_DEFAULT, curses.COLOR_WHITE, -1)
    curses.init_pair(COL_TITLE, curses.COLOR_CYAN, -1)
    curses.init_pair(COL_OK, curses.COLOR_GREEN, -1)
    curses.init_pair(COL_WARN, curses.COLOR_YELLOW, -1)
    curses.init_pair(COL_ERR, curses.COLOR_RED, -1)
    curses.init_pair(COL_HALF, curses.COLOR_YELLOW, -1)
    curses.init_pair(COL_FOCUS, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(COL_BTN, curses.COLOR_WHITE, -1)
    curses.init_pair(COL_BTN_SEL, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(COL_HINT, curses.COLOR_MAGENTA, -1)


def _safe_addstr(win, y, x, s, attr=0):
    try:
        win.addnstr(y, x, s, max(0, win.getmaxyx()[1] - x - 1), attr)
    except curses.error:
        pass


def _draw_box(win, y, x, h, w, title: str = ""):
    try:
        for i in range(w):
            win.addch(y, x + i, curses.ACS_HLINE)
            win.addch(y + h - 1, x + i, curses.ACS_HLINE)
        for i in range(h):
            win.addch(y + i, x, curses.ACS_VLINE)
            win.addch(y + i, x + w - 1, curses.ACS_VLINE)
        win.addch(y, x, curses.ACS_ULCORNER)
        win.addch(y, x + w - 1, curses.ACS_URCORNER)
        win.addch(y + h - 1, x, curses.ACS_LLCORNER)
        win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        if title:
            _safe_addstr(win, y, x + 2, f" {title} ", curses.color_pair(COL_TITLE) | curses.A_BOLD)
    except curses.error:
        pass


# --------- service color rendering ----------

def _service_attrs(status: str):
    """Return list of (text, attr) segments for a service label."""
    if status == "active":
        return [("", curses.color_pair(COL_OK) | curses.A_BOLD)]
    if status == "failed":
        return [("half_err_warn", 0)]  # split coloring
    if status == "inactive":
        return [("", curses.color_pair(COL_ERR) | curses.A_BOLD)]
    return [("", curses.color_pair(COL_WARN))]


def _draw_service(win, y, x, name: str, status: str, max_w: int):
    name = name[:max_w]
    half = max(1, len(name) // 2)
    if status == "active":
        _safe_addstr(win, y, x, name, curses.color_pair(COL_OK) | curses.A_BOLD)
    elif status == "failed":
        # half red / half orange-ish (yellow)
        _safe_addstr(win, y, x, name[:half], curses.color_pair(COL_WARN) | curses.A_BOLD)
        _safe_addstr(win, y, x + half, name[half:], curses.color_pair(COL_ERR) | curses.A_BOLD)
    elif status == "inactive":
        _safe_addstr(win, y, x, name, curses.color_pair(COL_ERR) | curses.A_BOLD)
    else:
        # unknown / partial -> half green / half yellow
        _safe_addstr(win, y, x, name[:half], curses.color_pair(COL_WARN))
        _safe_addstr(win, y, x + half, name[half:], curses.color_pair(COL_OK))


# --------- buttons ---------

BUTTONS = [
    ["btn_interfaces", "btn_settings", "btn_services", "btn_system"],
    ["btn_tools",      "btn_fix",      "btn_reset",    "btn_exit"],
]


def _btn_label(code: str, key: str, size: str) -> str:
    text = i18n.tr(code, key)
    pad = {"small": 2, "medium": 4, "large": 8}.get(size, 4)
    return " " * pad + text + " " * pad


def _draw_buttons(win, y_start, w, code, size, focus_row, focus_col, focused: bool):
    labels = [[_btn_label(code, k, size) for k in row] for row in BUTTONS]
    rows = 2
    for r in range(rows):
        row_labels = labels[r]
        widths = [len(lbl) + 2 for lbl in row_labels]
        gap = max(2, (w - sum(widths)) // (len(row_labels) + 1))
        x = gap
        # row layout: 4 lines per button (top border, label, bot border) with one blank between rows
        y = y_start + r * 5
        for c, lbl in enumerate(row_labels):
            bw = widths[c]
            sel = focused and (r == focus_row and c == focus_col)
            attr = curses.color_pair(COL_BTN_SEL) | curses.A_BOLD if sel else curses.color_pair(COL_BTN)
            top = " " + "_" * (bw - 2) + " "
            mid = "|" + lbl.center(bw - 2) + "|"
            bot = "|" + "_" * (bw - 2) + "|"
            _safe_addstr(win, y,     x, top, attr)
            _safe_addstr(win, y + 1, x, mid, attr)
            _safe_addstr(win, y + 2, x, bot, attr)
            x += bw + gap


# --------- left panel ----------

def _draw_left(win, x, y, w, h, code):
    # Title
    big = render_big("SYSGO")
    for i, ln in enumerate(big[:6]):
        _safe_addstr(win, y + i, x + 2, ln[:w - 4], curses.color_pair(COL_TITLE) | curses.A_BOLD)
    cur = y + 7
    _safe_addstr(win, cur, x + 2, f"{i18n.tr(code,'computer_name')}: {si.hostname()}", curses.A_BOLD)
    cur += 1
    _safe_addstr(win, cur, x + 2, f"{i18n.tr(code,'user_name')}: {si.username()}", curses.A_BOLD)
    cur += 2
    _safe_addstr(win, cur, x + 2, f"{i18n.tr(code,'interfaces')}:", curses.color_pair(COL_TITLE) | curses.A_BOLD)
    cur += 1

    ifaces = si.list_interfaces()[:3]
    for it in ifaces:
        if cur + 6 > y + h - 2:
            break
        name = it["name"]
        up = it["up"]
        st_attr = curses.color_pair(COL_OK if up else COL_ERR) | curses.A_BOLD
        _safe_addstr(win, cur, x + 2, f"{name}:", curses.A_BOLD); cur += 1
        _safe_addstr(win, cur, x + 4, f"{i18n.tr(code,'state')}: ", 0)
        _safe_addstr(win, cur, x + 4 + len(i18n.tr(code,'state')) + 2,
                     i18n.tr(code, "on" if up else "off"), st_attr)
        cur += 1
        _safe_addstr(win, cur, x + 4, f"{i18n.tr(code,'ip')}: {it.get('ip') or '-'}"); cur += 1
        mask = it.get("mask") or "-"
        cidr = it.get("cidr")
        cidr_s = f" /{cidr}" if cidr is not None else ""
        _safe_addstr(win, cur, x + 4, f"{i18n.tr(code,'mask')}: {mask}{cidr_s}"); cur += 1
        _safe_addstr(win, cur, x + 4, f"{i18n.tr(code,'gw')}: {it.get('gw') or '-'}"); cur += 1
        _safe_addstr(win, cur, x + 4, f"DNS1: {it.get('dns1') or '-'}"); cur += 1
        _safe_addstr(win, cur, x + 4, f"DNS2: {it.get('dns2') or '-'}"); cur += 2

    # Services
    if cur + 2 < y + h - 1:
        _safe_addstr(win, cur, x + 2, f"{i18n.tr(code,'services')}:", curses.color_pair(COL_TITLE) | curses.A_BOLD)
        cur += 1
        services = si.list_services()
        if not services:
            _safe_addstr(win, cur, x + 4, "-", curses.color_pair(COL_WARN))
        else:
            col_x = x + 4
            for svc in services:
                if cur >= y + h - 2:
                    break
                _draw_service(win, cur, col_x, svc["name"], svc["status"], w - 6)
                cur += 1


# --------- right panel: processes ----------

class ProcView:
    def __init__(self):
        self.scroll = 0       # top visible line
        self.cursor = 0       # selected process index (absolute)
        self.filter = ""
        self.last = []
        self.last_ts = 0.0
        self.visible = 0

    def fetch(self):
        now = time.time()
        if now - self.last_ts > 1.0:
            self.last = si.list_processes(self.filter)
            self.last_ts = now
        return self.last

    def draw(self, win, x, y, w, h, focused: bool):
        title = "PROCESSES" + (f"  [filter: {self.filter}]" if self.filter else "")
        _draw_box(win, y, x, h, w, title)
        if focused:
            _safe_addstr(win, y, x + w - 12, " [FOCUS] ", curses.color_pair(COL_FOCUS) | curses.A_BOLD)

        hdr = f"{'PID':>7}  {'USER':<12} {'CPU%':>6} {'MEM%':>6}  NAME"
        _safe_addstr(win, y + 1, x + 2, hdr[: w - 4], curses.A_BOLD | curses.color_pair(COL_TITLE))
        procs = self.fetch()
        visible = h - 4
        self.visible = visible
        # clamp cursor & scroll
        if procs:
            if self.cursor >= len(procs):
                self.cursor = len(procs) - 1
            if self.cursor < 0:
                self.cursor = 0
            if self.cursor < self.scroll:
                self.scroll = self.cursor
            if self.cursor >= self.scroll + visible:
                self.scroll = self.cursor - visible + 1
        if self.scroll > max(0, len(procs) - visible):
            self.scroll = max(0, len(procs) - visible)
        for i in range(visible):
            idx = self.scroll + i
            if idx >= len(procs):
                break
            p = procs[idx]
            line = f"{p['pid']:>7}  {p['user']:<12} {p['cpu']:>6.1f} {p['mem']:>6.1f}  {p['name']}"
            if idx == self.cursor:
                attr = curses.color_pair(COL_BTN_SEL) | curses.A_BOLD
            else:
                attr = curses.color_pair(COL_OK) if focused else 0
            # pad line to panel width so highlight bar spans the row
            row = line[: w - 4].ljust(w - 4)
            _safe_addstr(win, y + 2 + i, x + 2, row, attr)

    def key(self, ch, stdscr) -> str | None:
        procs = self.fetch()
        n = len(procs)
        if ch == curses.KEY_DOWN:
            if n: self.cursor = min(n - 1, self.cursor + 1)
        elif ch == curses.KEY_UP:
            self.cursor = max(0, self.cursor - 1)
        elif ch == curses.KEY_NPAGE:
            step = max(1, self.visible - 1)
            self.cursor = min(n - 1, self.cursor + step) if n else 0
        elif ch == curses.KEY_PPAGE:
            step = max(1, self.visible - 1)
            self.cursor = max(0, self.cursor - step)
        elif ch in (curses.KEY_HOME,):
            self.cursor = 0
        elif ch in (curses.KEY_END,):
            self.cursor = max(0, n - 1)
        elif ch in (ord("f"), ord("F")):
            self.filter = _prompt(stdscr, "Filter: ", self.filter)
            self.cursor = 0
            self.scroll = 0
            self.last_ts = 0
        elif ch in (ord("t"), ord("T"), ord("k"), ord("K")):
            if 0 <= self.cursor < n:
                pid = procs[self.cursor]["pid"]
                hard = ch in (ord("k"), ord("K"))
                si.kill_pid(pid, hard=hard)
                self.last_ts = 0
        return None


# --------- helpers ----------

def _prompt(stdscr, label: str, initial: str = "") -> str:
    h, w = stdscr.getmaxyx()
    y = h - 2
    curses.echo()
    curses.curs_set(1)
    try:
        _safe_addstr(stdscr, y, 2, " " * (w - 4))
        _safe_addstr(stdscr, y, 2, label, curses.A_BOLD)
        stdscr.move(y, 2 + len(label))
        s = stdscr.getstr(y, 2 + len(label), 40)
        return s.decode("utf-8", "ignore") if isinstance(s, bytes) else str(s)
    except Exception:
        return initial
    finally:
        curses.noecho()
        curses.curs_set(0)


def _confirm(stdscr, message: str, yes_key: str, no_key: str) -> bool:
    h, w = stdscr.getmaxyx()
    y = h - 2
    _safe_addstr(stdscr, y, 2, " " * (w - 4))
    _safe_addstr(stdscr, y, 2, message, curses.A_BOLD | curses.color_pair(COL_WARN))
    stdscr.refresh()
    while True:
        ch = stdscr.getch()
        if ch == -1:
            continue
        c = chr(ch).upper() if 0 <= ch < 256 else ""
        if c == yes_key.upper():
            return True
        if c == no_key.upper() or ch in (27,):
            return False


def _info(stdscr, text: str, press_any: str):
    h, w = stdscr.getmaxyx()
    box_w = min(w - 4, max(40, len(text) + 8))
    box_h = 6
    y = (h - box_h) // 2
    x = (w - box_w) // 2
    _draw_box(stdscr, y, x, box_h, box_w, "INFO")
    _safe_addstr(stdscr, y + 2, x + 3, text, curses.A_BOLD)
    _safe_addstr(stdscr, y + 4, x + 3, press_any, curses.color_pair(COL_HINT))
    stdscr.refresh()
    stdscr.nodelay(False)
    stdscr.getch()
    stdscr.nodelay(True)


# --------- main loop ----------

def run(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(500)
    _init_colors()

    cfg = config.load()
    code = cfg.get("lang", "en")

    focus_row, focus_col = 0, 0
    proc_focus = False
    procview = ProcView()

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 24 or w < 100:
            _safe_addstr(stdscr, 0, 0, "Terminal too small (min 100x24). Resize.", curses.color_pair(COL_ERR) | curses.A_BOLD)
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (27,):
                return
            continue

        left_w = w // 2
        right_x = left_w
        right_w = w - left_w
        top_h = h - 12  # leave 12 for buttons + hint

        # left panel box
        _draw_box(stdscr, 0, 0, top_h, left_w, "SYSGO")
        _draw_left(stdscr, 0, 0, left_w, top_h, code)

        # right panel processes
        procview.draw(stdscr, right_x, 0, right_w, top_h, proc_focus)

        # buttons
        _draw_buttons(stdscr, top_h + 1, w, code, cfg.get("size", "medium"),
                      focus_row, focus_col, focused=not proc_focus)

        # hint
        _safe_addstr(stdscr, h - 1, 2, i18n.tr(code, "tab_hint"),
                     curses.color_pair(COL_HINT) | curses.A_BOLD)

        stdscr.refresh()
        ch = stdscr.getch()
        if ch == -1:
            continue

        if ch == 9:  # TAB
            proc_focus = not proc_focus
            continue
        if ch in (27,):  # ESC
            if proc_focus:
                proc_focus = False
                continue
            if _confirm(stdscr, i18n.tr(code, "confirm_exit"),
                        i18n.tr(code, "yes_key"), i18n.tr(code, "no_key")):
                return
            continue

        if proc_focus:
            procview.key(ch, stdscr)
            continue

        # button navigation
        if ch == curses.KEY_LEFT:
            focus_col = (focus_col - 1) % 4
        elif ch == curses.KEY_RIGHT:
            focus_col = (focus_col + 1) % 4
        elif ch == curses.KEY_UP:
            focus_row = (focus_row - 1) % 2
        elif ch == curses.KEY_DOWN:
            focus_row = (focus_row + 1) % 2
        elif ch in (10, 13, curses.KEY_ENTER):
            key = BUTTONS[focus_row][focus_col]
            if key == "btn_exit":
                if _confirm(stdscr, i18n.tr(code, "confirm_exit"),
                            i18n.tr(code, "yes_key"), i18n.tr(code, "no_key")):
                    return
            elif key == "btn_reset":
                if _confirm(stdscr, i18n.tr(code, "confirm_reset"),
                            i18n.tr(code, "yes_key"), i18n.tr(code, "no_key")):
                    config.reset_first_run()
                    _info(stdscr, "OK", i18n.tr(code, "press_any"))
                    return
            elif key == "btn_interfaces":
                from . import interfaces as _ifaces
                _ifaces.launch(stdscr)
            elif key == "btn_settings":
                from . import computer as _comp
                _comp.launch(stdscr)
            else:
                _info(stdscr, i18n.tr(code, "not_implemented"),
                      i18n.tr(code, "press_any"))


def launch():
    curses.wrapper(run)
