"""SYSGO COMPUTER SETTINGS screen + sub-screens (users, system, perms)."""
from __future__ import annotations
import curses

from . import system_info as si
from . import i18n
from . import config as cfg_module
from .widgets import (
    init_colors, safe_addstr, draw_box, draw_header, draw_shortcuts,
    prompt_text, prompt_password, confirm, info_box, menu_choice, paginated_list,
    CP_OK, CP_ERR, CP_WARN, CP_TITLE, CP_HINT, CP_BTN_SEL, CP_BTN,
)


# =========================================================
# helpers
# =========================================================

def _draw_cs_info(stdscr, x, y, w, h, code):
    """Right panel of computer settings root."""
    safe_addstr(stdscr, y, x + 2,
                f"{i18n.tr(code,'cs_uid')}: ",
                curses.color_pair(CP_TITLE) | curses.A_BOLD)
    safe_addstr(stdscr, y, x + 8, str(__import__("os").getuid()))
    safe_addstr(stdscr, y + 1, x + 2,
                f"{i18n.tr(code,'cs_hostname')}: {si.hostname()}")
    user = si.username()
    safe_addstr(stdscr, y + 2, x + 2,
                f"{i18n.tr(code,'cs_curuser')}: {user}")
    info = next((u for u in si.list_users() if u["name"] == user), None)
    if info:
        priv = "SUDO" if info["is_sudo"] else "USER"
        attr = curses.color_pair(CP_OK if info["is_sudo"] else CP_WARN) | curses.A_BOLD
        safe_addstr(stdscr, y + 3, x + 2,
                    f"{i18n.tr(code,'cs_priv')}: ", 0)
        safe_addstr(stdscr, y + 3, x + 2 + len(i18n.tr(code, "cs_priv")) + 2,
                    priv, attr)
        groups = ", ".join((info.get("groups") or [])[:10])
        safe_addstr(stdscr, y + 4, x + 2,
                    f"{i18n.tr(code,'cs_group')}: {groups}"[: w - 3])
        safe_addstr(stdscr, y + 5, x + 2,
                    f"{i18n.tr(code,'cs_home')}: {info.get('home')}"[: w - 3])


def _draw_grid_buttons(stdscr, y, w, labels, cols, sel):
    """Render labels in grid, clipped strictly to the left panel width."""
    if not labels:
        return 0
    gap = 1
    max_bw = max(6, (w - (cols + 1) * gap) // cols)
    bw = min(max(len(l) for l in labels) + 6, max_bw)
    rows = (len(labels) + cols - 1) // cols
    total = cols * bw + (cols + 1) * gap
    x_start = max(gap, (w - total) // 2)
    for i, lbl in enumerate(labels):
        r = i // cols
        c = i % cols
        x = x_start + gap + c * (bw + gap)
        yy = y + r * 4
        sel_here = (i == sel)
        attr = curses.color_pair(CP_BTN_SEL) | curses.A_BOLD if sel_here \
            else curses.color_pair(CP_BTN)
        text = lbl[:bw - 2].center(bw - 2)
        top = " " + "_" * (bw - 2) + " "
        mid = "|" + text + "|"
        bot = "|" + "_" * (bw - 2) + "|"
        safe_addstr(stdscr, yy, x, top, attr)
        safe_addstr(stdscr, yy + 1, x, mid, attr)
        safe_addstr(stdscr, yy + 2, x, bot, attr)
    return rows


def _grid_nav(ch, sel, n, cols):
    if ch == curses.KEY_LEFT:
        return (sel - 1) % n
    if ch == curses.KEY_RIGHT:
        return (sel + 1) % n
    if ch == curses.KEY_UP:
        t = sel - cols
        return t if t >= 0 else sel
    if ch == curses.KEY_DOWN:
        t = sel + cols
        return t if t < n else sel
    return sel


# =========================================================
# Users
# =========================================================

def _user_info_panel(stdscr, user_name, x, y, w, h, code):
    info = next((u for u in si.list_users() if u["name"] == user_name), None)
    if not info:
        safe_addstr(stdscr, y, x + 2, "?"); return
    safe_addstr(stdscr, y, x + 2, info["name"],
                curses.color_pair(CP_TITLE) | curses.A_BOLD)
    safe_addstr(stdscr, y + 1, x + 2, f"UID: {info['uid']}")
    priv = "SUDO" if info["is_sudo"] else "USER"
    attr = curses.color_pair(CP_OK if info["is_sudo"] else CP_WARN) | curses.A_BOLD
    safe_addstr(stdscr, y + 2, x + 2, "Priv: ", 0)
    safe_addstr(stdscr, y + 2, x + 8, priv, attr)
    lock = "LOCKED" if info["locked"] else "UNLOCKED"
    safe_addstr(stdscr, y + 3, x + 2, f"State: {lock}",
                curses.color_pair(CP_ERR if info["locked"] else CP_OK))
    login = str(info.get("login_state") or "unlogged")
    safe_addstr(stdscr, y + 4, x + 2, f"Login: {login}",
                curses.color_pair(CP_OK if login != "unlogged" else CP_WARN))
    safe_addstr(stdscr, y + 5, x + 2, f"Home: {info['home']}"[: w - 3])
    safe_addstr(stdscr, y + 6, x + 2, f"Shell: {info['shell']}"[: w - 3])
    groups = ", ".join((info.get("groups") or [])[:20])
    safe_addstr(stdscr, y + 8, x + 2, "Groups:",
                curses.color_pair(CP_TITLE))
    safe_addstr(stdscr, y + 9, x + 2, groups[: w - 3])


def _users_add(stdscr, code):
    name = prompt_text(stdscr, i18n.tr(code, "u_enter_name")).strip()
    if not name:
        return
    if si.user_exists(name):
        info_box(stdscr, i18n.tr(code, "u_exists")); return
    uid_s = prompt_text(stdscr, i18n.tr(code, "u_enter_uid")).strip()
    uid = int(uid_s) if uid_s.isdigit() else None
    while True:
        pw = prompt_password(stdscr, i18n.tr(code, "u_enter_pass"))
        if not pw:
            pw = None
            break
        # weak check (very basic)
        if len(pw) < 6:
            info_box(stdscr, i18n.tr(code, "u_pass_weak"))
            continue
        break
    pick = menu_choice(stdscr, i18n.tr(code, "u_choose_priv"),
                       [i18n.tr(code, "u_priv_user"),
                        i18n.tr(code, "u_priv_sudo")])
    sudo = pick == 1
    ok, e = si.add_user(name, uid, pw, sudo)
    info_box(stdscr, i18n.tr(code, "u_created") if ok
             else i18n.tr(code, "error") + e)


def _users_del(stdscr, code):
    users = [u for u in si.list_users() if u["name"] != "root"]
    labels = [f"{u['name']} <UID {u['uid']}>" for u in users]
    if not labels:
        info_box(stdscr, "-"); return
    idx = paginated_list(stdscr, i18n.tr(code, "u_del"), labels)
    if idx is None:
        return
    target = users[idx]["name"]
    if target == "root":
        info_box(stdscr, i18n.tr(code, "u_cannot_root")); return
    if confirm(stdscr,
               i18n.tr(code, "u_confirm_del").format(u=target),
               i18n.tr(code, "yes_key"), i18n.tr(code, "no_key")):
        ok, e = si.del_user(target)
        info_box(stdscr, i18n.tr(code, "u_deleted") if ok
                 else i18n.tr(code, "error") + e)


def _user_edit_actions(stdscr, name, code):
    """Per-user actions screen."""
    actions = [
        ("ue_toggle_priv", lambda: si.toggle_sudo(name)),
        ("ue_login_logs", None),
        ("ue_lock", None),
        ("ue_force_pw", lambda: si.force_password_change(name)),
        ("ue_motd", None),
        ("ue_rename", None),
        ("ue_change_uid", None),
        ("ue_change_pw", None),
        ("ue_add_group", None),
        ("ue_rem_group", None),
    ]
    sel = 0
    stdscr.nodelay(True); stdscr.timeout(500)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr)
        safe_addstr(stdscr, 0, w - 40, f"EDIT: {name}",
                    curses.color_pair(CP_TITLE) | curses.A_BOLD)

        left_w = (w * 6) // 10
        labels = [i18n.tr(code, k) for k, _ in actions]
        _draw_grid_buttons(stdscr, 8, left_w, labels, 3, sel)

        right_x = left_w + 1
        right_w = w - right_x - 1
        draw_box(stdscr, 7, right_x, h - 9, right_w, " USER ")
        _user_info_panel(stdscr, name, right_x, 8, right_w, h - 9, code)

        draw_shortcuts(stdscr, "ARROWS=move ENTER=apply ESC=back")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == -1:
            continue
        if ch == 27:
            return
        new_sel = _grid_nav(ch, sel, len(actions), 3)
        if new_sel != sel:
            sel = new_sel; continue
        if ch in (10, 13, curses.KEY_ENTER):
            key, fn = actions[sel]
            if key == "ue_toggle_priv":
                ok, e = si.toggle_sudo(name)
                info_box(stdscr, i18n.tr(code, "saved") if ok
                         else i18n.tr(code, "error") + e)
            elif key == "ue_login_logs":
                lines = si.user_login_logs(name)
                info_box(stdscr, "\n".join(lines[:20]) or "-")
            elif key == "ue_lock":
                info = next((u for u in si.list_users()
                             if u["name"] == name), None)
                if info:
                    ok, e = si.lock_user(name, not info["locked"])
                    info_box(stdscr, i18n.tr(code, "saved") if ok
                             else i18n.tr(code, "error") + e)
            elif key == "ue_force_pw":
                ok, e = si.force_password_change(name)
                info_box(stdscr, i18n.tr(code, "saved") if ok
                         else i18n.tr(code, "error") + e)
            elif key == "ue_motd":
                msg = prompt_text(stdscr, "MOTD: ")
                if msg:
                    ok, e = si.set_login_notice(name, msg)
                    info_box(stdscr, i18n.tr(code, "saved") if ok
                             else i18n.tr(code, "error") + e)
            elif key == "ue_rename":
                new = prompt_text(stdscr, "New name: ").strip()
                if new:
                    ok, e = si.rename_user(name, new)
                    info_box(stdscr, i18n.tr(code, "saved") if ok
                             else i18n.tr(code, "error") + e)
                    if ok:
                        return
            elif key == "ue_change_uid":
                s = prompt_text(stdscr, "New UID: ").strip()
                if s.isdigit():
                    ok, e = si.change_uid(name, int(s))
                    info_box(stdscr, i18n.tr(code, "saved") if ok
                             else i18n.tr(code, "error") + e)
            elif key == "ue_change_pw":
                pw = prompt_password(stdscr, "New password: ")
                if pw:
                    ok, e = si.set_user_password(name, pw)
                    info_box(stdscr, i18n.tr(code, "saved") if ok
                             else i18n.tr(code, "error") + e)
            elif key == "ue_add_group":
                groups = si.list_groups()
                idx = paginated_list(stdscr, "Group", groups)
                if idx is not None:
                    ok, e = si.add_to_group(name, groups[idx])
                    info_box(stdscr, i18n.tr(code, "saved") if ok
                             else i18n.tr(code, "error") + e)
            elif key == "ue_rem_group":
                info = next((u for u in si.list_users()
                             if u["name"] == name), None)
                groups = (info.get("groups") if info else []) or []
                if not groups:
                    info_box(stdscr, "-"); continue
                idx = paginated_list(stdscr, "Group", groups)
                if idx is not None:
                    ok, e = si.remove_from_group(name, groups[idx])
                    info_box(stdscr, i18n.tr(code, "saved") if ok
                             else i18n.tr(code, "error") + e)


def _users_edit(stdscr, code):
    users = si.list_users()
    labels = [f"{u['name']} <UID {u['uid']}>" for u in users]

    def panel(idx, x, y, w, h):
        _user_info_panel(stdscr, users[idx]["name"], x, y, w, h, code)

    idx = paginated_list(stdscr, i18n.tr(code, "u_edit"), labels,
                         right_panel=panel)
    if idx is None:
        return
    _user_edit_actions(stdscr, users[idx]["name"], code)


def _users_root(stdscr, code):
    actions = [("u_add", _users_add),
               ("u_del", _users_del),
               ("u_edit", _users_edit)]
    sel = 0
    stdscr.nodelay(True); stdscr.timeout(500)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr)
        safe_addstr(stdscr, 0, w - 30, i18n.tr(code, "cs_users"),
                    curses.color_pair(CP_TITLE) | curses.A_BOLD)
        left_w = (w * 6) // 10
        labels = [i18n.tr(code, k) for k, _ in actions]
        _draw_grid_buttons(stdscr, 8, left_w, labels, 1, sel)
        right_x = left_w + 1
        right_w = w - right_x - 1
        draw_box(stdscr, 7, right_x, h - 9, right_w, " INFO ")
        _draw_cs_info(stdscr, right_x, 8, right_w, h - 9, code)
        draw_shortcuts(stdscr, "ARROWS=move ENTER=open ESC=back")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == -1: continue
        if ch == 27: return
        new_sel = _grid_nav(ch, sel, len(actions), 1)
        if new_sel != sel:
            sel = new_sel; continue
        if ch in (10, 13, curses.KEY_ENTER):
            actions[sel][1](stdscr, code)


# =========================================================
# System
# =========================================================

def _system_info_panel(stdscr, x, y, w, h, code):
    import time as _t
    safe_addstr(stdscr, y, x + 2, f"Host: {si.hostname()}",
                curses.color_pair(CP_TITLE) | curses.A_BOLD)
    safe_addstr(stdscr, y + 1, x + 2, f"TZ:   {si.timezone_get()}")
    safe_addstr(stdscr, y + 2, x + 2,
                f"Time: {_t.strftime('%Y-%m-%d %H:%M:%S')}")
    safe_addstr(stdscr, y + 3, x + 2, f"Lang: {si.locale_get()}"[: w - 3])
    safe_addstr(stdscr, y + 4, x + 2, f"Kbd:  {si.keyboard_get()}"[: w - 3])
    sched = si.scheduled_shutdown()
    safe_addstr(stdscr, y + 5, x + 2,
                f"Shutdown: {sched if sched else 'NIE'}"[: w - 3],
                curses.color_pair(CP_WARN if sched else CP_OK))
    safe_addstr(stdscr, y + 6, x + 2, f"OS: {si.os_pretty()}"[: w - 3])


def _system_screen(stdscr, code):
    actions = [
        ("sys_hostname", lambda: _sys_hostname(stdscr, code)),
        ("sys_fqdn", lambda: _sys_fqdn(stdscr, code)),
        ("sys_info", lambda: _sys_info(stdscr, code)),
        ("sys_power", lambda: _sys_power(stdscr, code)),
        ("sys_update", lambda: _sys_update(stdscr, code)),
        ("sys_time", lambda: _sys_set_time(stdscr, code)),
        ("sys_date", lambda: _sys_set_date(stdscr, code)),
        ("sys_tz", lambda: _sys_tz(stdscr, code)),
        ("sys_ntp", lambda: _sys_ntp(stdscr, code)),
        ("sys_tstatus", lambda: info_box(stdscr, si.time_status())),
        ("sys_lang", lambda: _sys_lang(stdscr, code)),
        ("sys_kbd_add", lambda: _sys_kbd(stdscr, code, "add")),
        ("sys_kbd_del", lambda: _sys_kbd(stdscr, code, "del")),
        ("sys_kbd_def", lambda: _sys_kbd(stdscr, code, "def")),
        ("sys_factory", lambda: _sys_factory(stdscr, code)),
        ("sys_schedule_off", lambda: _sys_schedule(stdscr, code)),
    ]
    sel = 0
    stdscr.nodelay(True); stdscr.timeout(500)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr)
        safe_addstr(stdscr, 0, w - 30, i18n.tr(code, "cs_system"),
                    curses.color_pair(CP_TITLE) | curses.A_BOLD)
        left_w = (w * 6) // 10
        labels = [i18n.tr(code, k) for k, _ in actions]
        _draw_grid_buttons(stdscr, 8, left_w, labels, 4, sel)
        right_x = left_w + 1
        right_w = w - right_x - 1
        draw_box(stdscr, 7, right_x, h - 9, right_w, " SYSTEM ")
        _system_info_panel(stdscr, right_x, 8, right_w, h - 9, code)
        draw_shortcuts(stdscr, "ARROWS=move ENTER=apply ESC=back")
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == -1: continue
        if ch == 27: return
        new_sel = _grid_nav(ch, sel, len(actions), 4)
        if new_sel != sel:
            sel = new_sel; continue
        if ch in (10, 13, curses.KEY_ENTER):
            try:
                actions[sel][1]()
            except Exception as e:
                info_box(stdscr, i18n.tr(code, "error") + str(e))


def _sys_hostname(stdscr, code):
    s = prompt_text(stdscr, "Hostname: ").strip()
    if s:
        ok, e = si.set_hostname(s)
        info_box(stdscr, i18n.tr(code, "saved") if ok
                 else i18n.tr(code, "error") + e)


def _sys_fqdn(stdscr, code):
    s = prompt_text(stdscr, "FQDN: ").strip()
    if s:
        try:
            host = si.hostname()
            lines = []
            for line in open("/etc/hosts"):
                if "127.0.1.1" in line:
                    line = f"127.0.1.1\t{s}\t{host}\n"
                lines.append(line)
            open("/etc/hosts", "w").writelines(lines)
            info_box(stdscr, i18n.tr(code, "saved"))
        except Exception as e:
            info_box(stdscr, i18n.tr(code, "error") + str(e))


def _sys_info(stdscr, code):
    import platform
    info = [
        f"OS:     {si.os_pretty()}",
        f"Kernel: {platform.release()}",
        f"Arch:   {platform.machine()}",
        f"Host:   {si.hostname()}",
    ]
    info_box(stdscr, "\n".join(info))


def _sys_power(stdscr, code):
    pick = menu_choice(stdscr, "Power",
                       ["Shutdown", "Reboot", "Suspend", "Cancel scheduled"])
    if pick == 0:
        si.run(["shutdown", "now"])
    elif pick == 1:
        si.run(["reboot"])
    elif pick == 2:
        si.run(["systemctl", "suspend"])
    elif pick == 3:
        ok, e = si.cancel_shutdown()
        info_box(stdscr, i18n.tr(code, "saved") if ok else e)


def _sys_update(stdscr, code):
    info_box(stdscr, "Uruchamiam aktualizacje w tle...")
    # detect manager
    import shutil
    if shutil.which("apt-get"):
        cmd = ["apt-get", "update"]
    elif shutil.which("dnf"):
        cmd = ["dnf", "check-update"]
    elif shutil.which("zypper"):
        cmd = ["zypper", "refresh"]
    elif shutil.which("pacman"):
        cmd = ["pacman", "-Sy"]
    else:
        info_box(stdscr, i18n.tr(code, "not_implemented")); return
    rc, out, e = si.run(cmd, timeout=120)
    info_box(stdscr, (i18n.tr(code, "saved") if rc == 0
                      else i18n.tr(code, "error") + e)[:1000])


def _sys_set_time(stdscr, code):
    s = prompt_text(stdscr, "HH:MM:SS ").strip()
    if s:
        ok, e = si.time_set(s)
        info_box(stdscr, i18n.tr(code, "saved") if ok
                 else i18n.tr(code, "error") + e)


def _sys_set_date(stdscr, code):
    s = prompt_text(stdscr, "YYYY-MM-DD: ").strip()
    if s:
        ok, e = si.time_set(s)
        info_box(stdscr, i18n.tr(code, "saved") if ok
                 else i18n.tr(code, "error") + e)


def _sys_tz(stdscr, code):
    zones = si.timezone_list()
    if not zones:
        info_box(stdscr, "-"); return
    idx = paginated_list(stdscr, "Timezone", zones)
    if idx is not None:
        ok, e = si.timezone_set(zones[idx])
        info_box(stdscr, i18n.tr(code, "saved") if ok
                 else i18n.tr(code, "error") + e)


def _sys_ntp(stdscr, code):
    pick = menu_choice(stdscr, "NTP", ["Enable", "Disable"])
    if pick is not None:
        ok, e = si.ntp_set(pick == 0)
        info_box(stdscr, i18n.tr(code, "saved") if ok
                 else i18n.tr(code, "error") + e)


def _sys_lang(stdscr, code):
    common = ["pl_PL.UTF-8", "en_US.UTF-8", "en_GB.UTF-8",
              "de_DE.UTF-8", "nb_NO.UTF-8", "fr_FR.UTF-8", "es_ES.UTF-8"]
    idx = paginated_list(stdscr, "Locale", common)
    if idx is not None:
        ok, e = si.locale_set(common[idx])
        info_box(stdscr, i18n.tr(code, "saved") if ok
                 else i18n.tr(code, "error") + e)


def _sys_kbd(stdscr, code, mode: str):
    rc, out, _ = si.run(["localectl", "list-keymaps"])
    keys = out.splitlines() if rc == 0 else ["us", "pl", "de", "fr", "no"]
    if mode == "del":
        info_box(stdscr, "Aktualny: " + si.keyboard_get()); return
    idx = paginated_list(stdscr, "Keymap", keys)
    if idx is not None:
        ok, e = si.keyboard_set(keys[idx])
        info_box(stdscr, i18n.tr(code, "saved") if ok
                 else i18n.tr(code, "error") + e)


def _sys_factory(stdscr, code):
    if confirm(stdscr, "Reset SYSGO config? (T/N)",
               i18n.tr(code, "yes_key"), i18n.tr(code, "no_key")):
        cfg_module.reset_first_run()
        info_box(stdscr, i18n.tr(code, "saved"))


def _sys_schedule(stdscr, code):
    s = prompt_text(stdscr, "Sekundy do zamkniecia (0=anuluj): ").strip()
    if s.isdigit():
        n = int(s)
        if n == 0:
            ok, e = si.cancel_shutdown()
        else:
            ok, e = si.schedule_shutdown(n)
        info_box(stdscr, i18n.tr(code, "saved") if ok
                 else i18n.tr(code, "error") + e)


# =========================================================
# Permissions (simple)
# =========================================================

def _perms_simple(stdscr, code):
    while True:
        users = si.list_users()
        labels = [f"{u['name']:<16} [{'SUDO' if u['is_sudo'] else 'USER'}]"
                  for u in users]

        def panel(idx, x, y, w, h):
            u = users[idx]
            safe_addstr(stdscr, y, x + 2, u["name"],
                        curses.color_pair(CP_TITLE) | curses.A_BOLD)
            big = ("SUDO/WHEEL" if u["is_sudo"] else "USER")
            attr = curses.color_pair(CP_OK if u["is_sudo"] else CP_WARN) | curses.A_BOLD
            safe_addstr(stdscr, y + 2, x + 2, "    " + big + "    ", attr)
            safe_addstr(stdscr, y + 4, x + 2, f"UID: {u['uid']}")
            safe_addstr(stdscr, y + 5, x + 2,
                        f"Groups: {', '.join((u.get('groups') or [])[:10])}"[: w - 3])

        idx = paginated_list(stdscr, i18n.tr(code, "cs_perms"), labels,
                             right_panel=panel)
        if idx is None:
            return
        target = users[idx]["name"]
        if target == "root":
            info_box(stdscr, i18n.tr(code, "u_cannot_root")); continue
        ok, e = si.toggle_sudo(target)
        info_box(stdscr, i18n.tr(code, "saved") if ok
                 else i18n.tr(code, "error") + e)


# =========================================================
# Computer Settings root
# =========================================================

def _draw_logs(stdscr, journal, x, y, w, h):
    draw_box(stdscr, y, x, h, w, " LOGS ")
    lines = journal.lines[-(h - 2):]
    for i, ln in enumerate(lines):
        safe_addstr(stdscr, y + 1 + i, x + 2, ln[: w - 3])


def launch(stdscr):
    code = cfg_module.load().get("lang", "en")
    init_colors()
    stdscr.nodelay(True); stdscr.timeout(500)
    journal = si.JournalTail()
    journal.start()
    actions = [
        ("cs_users", lambda: _users_root(stdscr, code)),
        ("cs_system", lambda: _system_screen(stdscr, code)),
        ("cs_perms", lambda: _perms_simple(stdscr, code)),
        ("cs_perms_adv", lambda: info_box(stdscr, i18n.tr(code, "not_implemented"))),
        ("cs_groups", lambda: info_box(stdscr, i18n.tr(code, "not_implemented"))),
        ("cs_disks", lambda: info_box(stdscr, i18n.tr(code, "not_implemented"))),
        ("cs_logs", lambda: info_box(stdscr, i18n.tr(code, "not_implemented"))),
        ("cs_back", None),
    ]
    sel = 0
    try:
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            draw_header(stdscr)
            safe_addstr(stdscr, 0, w - 30, i18n.tr(code, "cs_title"),
                        curses.color_pair(CP_TITLE) | curses.A_BOLD)

            left_w = (w * 6) // 10
            log_h = 10
            labels = [i18n.tr(code, k) for k, _ in actions]
            _draw_grid_buttons(stdscr, 8, left_w, labels, 4, sel)

            right_x = left_w + 1
            right_w = w - right_x - 1
            draw_box(stdscr, 7, right_x, h - 9 - log_h, right_w, " INFO ")
            _draw_cs_info(stdscr, right_x, 8, right_w, h - 9 - log_h, code)

            _draw_logs(stdscr, journal, 2, h - 2 - log_h, w - 4, log_h)
            draw_shortcuts(stdscr, "ARROWS=move ENTER=open ESC=back")
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == -1: continue
            if ch == 27: return
            new_sel = _grid_nav(ch, sel, len(actions), 4)
            if new_sel != sel:
                sel = new_sel; continue
            if ch in (10, 13, curses.KEY_ENTER):
                if actions[sel][0] == "cs_back":
                    return
                actions[sel][1]()
    finally:
        journal.stop()
