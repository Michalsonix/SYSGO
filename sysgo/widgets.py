"""Common curses widgets used across SYSGO screens."""
from __future__ import annotations
import curses
from typing import List, Tuple, Optional, Callable

from .ascii_art import render_big

# Color pair IDs (keep distinct from menu.py to avoid clash when both inited)
CP_DEFAULT = 1
CP_TITLE = 2
CP_OK = 3
CP_WARN = 4
CP_ERR = 5
CP_HALF = 6
CP_FOCUS = 7
CP_BTN = 8
CP_BTN_SEL = 9
CP_HINT = 10


def init_colors():
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(CP_DEFAULT, curses.COLOR_WHITE, -1)
        curses.init_pair(CP_TITLE, curses.COLOR_CYAN, -1)
        curses.init_pair(CP_OK, curses.COLOR_GREEN, -1)
        curses.init_pair(CP_WARN, curses.COLOR_YELLOW, -1)
        curses.init_pair(CP_ERR, curses.COLOR_RED, -1)
        curses.init_pair(CP_HALF, curses.COLOR_YELLOW, -1)
        curses.init_pair(CP_FOCUS, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(CP_BTN, curses.COLOR_WHITE, -1)
        curses.init_pair(CP_BTN_SEL, curses.COLOR_BLACK, curses.COLOR_GREEN)
        curses.init_pair(CP_HINT, curses.COLOR_MAGENTA, -1)
    except curses.error:
        pass


def safe_addstr(win, y, x, s, attr=0):
    if y < 0 or x < 0:
        return
    try:
        maxy, maxx = win.getmaxyx()
        if y >= maxy:
            return
        win.addnstr(y, x, s, max(0, maxx - x - 1), attr)
    except curses.error:
        pass


def draw_box(win, y, x, h, w, title: str = ""):
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
            safe_addstr(win, y, x + 2, f" {title} ",
                        curses.color_pair(CP_TITLE) | curses.A_BOLD)
    except curses.error:
        pass


def draw_header(stdscr, title: str = "SYSGO"):
    """Draw SYSGO ASCII at top. Returns y-offset after header."""
    big = render_big(title)
    for i, ln in enumerate(big):
        safe_addstr(stdscr, i, 2, ln,
                    curses.color_pair(CP_TITLE) | curses.A_BOLD)
    return len(big) + 1


def draw_shortcuts(stdscr, hints: str):
    h, _w = stdscr.getmaxyx()
    safe_addstr(stdscr, h - 1, 2, hints,
                curses.color_pair(CP_HINT) | curses.A_BOLD)


def draw_button(stdscr, y, x, label: str, selected: bool, disabled: bool = False):
    """Draw a 3-line button shape. Returns width."""
    inner = f"  {label}  "
    bw = len(inner) + 2
    if disabled:
        attr = curses.color_pair(CP_WARN)
    elif selected:
        attr = curses.color_pair(CP_BTN_SEL) | curses.A_BOLD
    else:
        attr = curses.color_pair(CP_BTN)
    top = " " + "_" * (bw - 2) + " "
    mid = "|" + inner.center(bw - 2) + "|"
    bot = "|" + "_" * (bw - 2) + "|"
    safe_addstr(stdscr, y, x, top, attr)
    safe_addstr(stdscr, y + 1, x, mid, attr)
    safe_addstr(stdscr, y + 2, x, bot, attr)
    return bw


def layout_grid(labels: List[str], total_w: int, cols: int = 4,
                gap: int = 2) -> List[Tuple[int, int, str]]:
    """Return list of (col_idx, x_offset, label) for each label, packed in `cols` columns."""
    # equalize width
    maxlbl = max((len(l) for l in labels), default=0)
    bw = maxlbl + 6
    total = cols * bw + (cols + 1) * gap
    left_pad = max(gap, (total_w - total) // 2)
    placements = []
    for i, lbl in enumerate(labels):
        c = i % cols
        x = left_pad + c * (bw + gap)
        placements.append((c, x, lbl))
    return placements, bw


def prompt_text(stdscr, label: str, initial: str = "", max_len: int = 80) -> str:
    h, w = stdscr.getmaxyx()
    y = h - 2
    # CRITICAL: disable non-blocking + timeout so input does not auto-cancel.
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    curses.echo()
    curses.curs_set(1)
    try:
        safe_addstr(stdscr, y, 2, " " * (w - 4))
        safe_addstr(stdscr, y, 2, label, curses.A_BOLD)
        stdscr.move(y, 2 + len(label))
        if initial:
            stdscr.addstr(initial)
        s = stdscr.getstr(y, 2 + len(label), max_len)
        return s.decode("utf-8", "ignore") if isinstance(s, bytes) else str(s)
    except Exception:
        return initial
    finally:
        curses.noecho()
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(500)


def prompt_password(stdscr, label: str) -> str:
    h, w = stdscr.getmaxyx()
    y = h - 2
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    curses.noecho()
    curses.curs_set(1)
    try:
        safe_addstr(stdscr, y, 2, " " * (w - 4))
        safe_addstr(stdscr, y, 2, label, curses.A_BOLD)
        stdscr.move(y, 2 + len(label))
        s = ""
        while True:
            ch = stdscr.getch()
            if ch in (10, 13, curses.KEY_ENTER):
                break
            if ch == 27:
                s = ""
                break
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                s = s[:-1]
            elif 32 <= ch < 127:
                s += chr(ch)
            safe_addstr(stdscr, y, 2 + len(label), "*" * len(s) + "    ")
        return s
    finally:
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(500)


def confirm(stdscr, message: str, yes_key: str = "Y", no_key: str = "N") -> bool:
    h, w = stdscr.getmaxyx()
    y = h - 2
    safe_addstr(stdscr, y, 2, " " * (w - 4))
    safe_addstr(stdscr, y, 2, message,
                curses.A_BOLD | curses.color_pair(CP_WARN))
    stdscr.refresh()
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    try:
        while True:
            ch = stdscr.getch()
            if ch == -1:
                continue
            if 0 <= ch < 256:
                c = chr(ch).upper()
                if c == yes_key.upper():
                    return True
                if c == no_key.upper() or ch == 27:
                    return False
            if ch == 27:
                return False
    finally:
        stdscr.nodelay(True)
        stdscr.timeout(500)


def info_box(stdscr, text: str, press_any: str = "Press any key..."):
    h, w = stdscr.getmaxyx()
    lines = text.split("\n")
    box_w = min(w - 4, max(40, max(len(l) for l in lines) + 8))
    box_h = len(lines) + 5
    y = (h - box_h) // 2
    x = (w - box_w) // 2
    for i in range(box_h):
        safe_addstr(stdscr, y + i, x, " " * box_w)
    draw_box(stdscr, y, x, box_h, box_w, "INFO")
    for i, ln in enumerate(lines):
        safe_addstr(stdscr, y + 2 + i, x + 3, ln, curses.A_BOLD)
    safe_addstr(stdscr, y + box_h - 2, x + 3, press_any,
                curses.color_pair(CP_HINT))
    stdscr.refresh()
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    try:
        stdscr.getch()
    finally:
        stdscr.nodelay(True)
        stdscr.timeout(500)


def menu_choice(stdscr, title: str, options: List[str]) -> Optional[int]:
    """Modal centered menu. Returns index or None on ESC."""
    h, w = stdscr.getmaxyx()
    box_w = min(w - 4, max(40, max(len(o) for o in options) + 12, len(title) + 8))
    box_h = len(options) + 6
    y = (h - box_h) // 2
    x = (w - box_w) // 2
    sel = 0
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    try:
        while True:
            for i in range(box_h):
                safe_addstr(stdscr, y + i, x, " " * box_w)
            draw_box(stdscr, y, x, box_h, box_w, title)
            for i, opt in enumerate(options):
                attr = curses.color_pair(CP_BTN_SEL) | curses.A_BOLD if i == sel \
                    else curses.color_pair(CP_BTN)
                mark = " > " if i == sel else "   "
                safe_addstr(stdscr, y + 2 + i, x + 3,
                            (mark + opt).ljust(box_w - 6), attr)
            safe_addstr(stdscr, y + box_h - 2, x + 3,
                        "ENTER=ok  ESC=cancel",
                        curses.color_pair(CP_HINT))
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == curses.KEY_UP:
                sel = (sel - 1) % len(options)
            elif ch == curses.KEY_DOWN:
                sel = (sel + 1) % len(options)
            elif ch in (10, 13, curses.KEY_ENTER):
                return sel
            elif ch == 27:
                return None
    finally:
        stdscr.nodelay(True)
        stdscr.timeout(500)


def paginated_list(stdscr, title: str, items: List[str],
                   on_hover: Optional[Callable[[int], None]] = None,
                   right_panel: Optional[Callable[[int, int, int, int, int], None]] = None
                   ) -> Optional[int]:
    """Paginated list with optional right-side detail callback.

    right_panel(idx, x, y, w, h) draws live info for hovered item.
    Returns the chosen index or None on ESC.
    """
    sel = 0
    page = 0
    stdscr.nodelay(True)
    stdscr.timeout(500)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        header_y = draw_header(stdscr)
        safe_addstr(stdscr, header_y, 2, title,
                    curses.color_pair(CP_TITLE) | curses.A_BOLD)
        list_x = 2
        list_y = header_y + 2
        list_h = h - list_y - 2
        list_w = (w // 2) - 4 if right_panel else (w - 4)
        per_page = max(1, list_h - 2)
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        if page >= total_pages:
            page = total_pages - 1
        start = page * per_page
        end = min(len(items), start + per_page)
        # adjust sel
        if sel < start:
            sel = start
        if sel >= end:
            sel = end - 1 if end > start else start

        draw_box(stdscr, list_y, list_x, list_h, list_w,
                 f"  page {page+1}/{total_pages}  ")
        for i, idx in enumerate(range(start, end)):
            attr = curses.color_pair(CP_BTN_SEL) | curses.A_BOLD if idx == sel \
                else curses.color_pair(CP_BTN)
            mark = " > " if idx == sel else "   "
            safe_addstr(stdscr, list_y + 1 + i, list_x + 2,
                        (mark + items[idx])[: list_w - 4], attr)

        # paging buttons hints
        if page > 0:
            safe_addstr(stdscr, list_y, list_x + 4, " [B]ACK ",
                        curses.color_pair(CP_HINT) | curses.A_BOLD)
        if page < total_pages - 1:
            safe_addstr(stdscr, list_y + list_h - 1, list_x + list_w - 12,
                        " [N]EXT ", curses.color_pair(CP_HINT) | curses.A_BOLD)

        if right_panel:
            rx = w // 2
            rw = w - rx - 2
            draw_box(stdscr, list_y, rx, list_h, rw, " INFO ")
            try:
                right_panel(sel, rx + 1, list_y + 1, rw - 2, list_h - 2)
            except Exception as e:
                safe_addstr(stdscr, list_y + 1, rx + 2,
                            f"err: {e}"[: rw - 3],
                            curses.color_pair(CP_ERR))

        draw_shortcuts(stdscr,
                       "ARROWS=move  ENTER=select  N=next page  B=back page  ESC=back")
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1:
            continue
        if ch == 27:
            return None
        if ch in (curses.KEY_UP,):
            if sel > 0:
                sel -= 1
                if sel < start:
                    page = max(0, page - 1)
        elif ch == curses.KEY_DOWN:
            if sel < len(items) - 1:
                sel += 1
                if sel >= end:
                    page = min(total_pages - 1, page + 1)
        elif ch in (curses.KEY_NPAGE, ord("n"), ord("N")):
            if page < total_pages - 1:
                page += 1
                sel = page * per_page
        elif ch in (curses.KEY_PPAGE, ord("b"), ord("B")):
            if page > 0:
                page -= 1
                sel = page * per_page
        elif ch in (10, 13, curses.KEY_ENTER):
            return sel
        if on_hover:
            try:
                on_hover(sel)
            except Exception:
                pass
