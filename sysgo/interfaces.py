"""SYSGO INTERFACES screen.

List of network interfaces + per-interface edit view with live info panel.
"""
from __future__ import annotations
import curses
import time
import subprocess
import os

from . import system_info as si
from . import i18n
from .widgets import (
    init_colors, safe_addstr, draw_box, draw_header, draw_shortcuts,
    draw_button, prompt_text, confirm, info_box, menu_choice,
    CP_OK, CP_ERR, CP_WARN, CP_TITLE, CP_HINT, CP_BTN_SEL, CP_BTN,
)


def _draw_iface_info(stdscr, x, y, w, h, iface_name: str, arp: si.ArpScanner, code: str):
    """Live info for one interface."""
    info = si.interface_by_name(iface_name)
    if not info:
        safe_addstr(stdscr, y + 1, x + 2,
                    f"{iface_name}: ?", curses.color_pair(CP_ERR))
        return
    cy = y + 1
    safe_addstr(stdscr, cy, x + 2,
                f"Interfejs: {info['name']}",
                curses.color_pair(CP_TITLE) | curses.A_BOLD); cy += 1
    state_attr = curses.color_pair(CP_OK if info["up"] else CP_ERR) | curses.A_BOLD
    safe_addstr(stdscr, cy, x + 2, "State: ", 0)
    safe_addstr(stdscr, cy, x + 9,
                i18n.tr(code, "on" if info["up"] else "off"), state_attr); cy += 1
    safe_addstr(stdscr, cy, x + 2, f"IP:   {info.get('ip') or '-'}"); cy += 1
    mask = info.get("mask") or "-"
    cidr = info.get("cidr")
    cidr_s = f"  /{cidr}" if cidr is not None else ""
    safe_addstr(stdscr, cy, x + 2, f"M:    {mask}{cidr_s}"); cy += 1
    safe_addstr(stdscr, cy, x + 2, f"B:    {info.get('gw') or '-'}"); cy += 1
    safe_addstr(stdscr, cy, x + 2, f"DNS:  {info.get('dns1') or '-'}"); cy += 1
    safe_addstr(stdscr, cy, x + 2, f"DNS2: {info.get('dns2') or '-'}"); cy += 1
    more = info.get("more_dns") or []
    safe_addstr(stdscr, cy, x + 2,
                f"MORE: {', '.join(more) if more else '-'}"[: w - 3]); cy += 2

    # network calc
    if info.get("ip") and cidr is not None:
        nc = si.network_calc(info["ip"], cidr)  # type: ignore
        safe_addstr(stdscr, cy, x + 2,
                    f"{i18n.tr(code,'iface_net_addr')}: {nc['network']}/{nc['prefix']}"); cy += 1
        safe_addstr(stdscr, cy, x + 2,
                    f"{i18n.tr(code,'iface_broadcast')}: {nc['broadcast']}"); cy += 1
        safe_addstr(stdscr, cy, x + 2,
                    f"{i18n.tr(code,'iface_hosts_range')}: {nc['hosts']}"); cy += 2
    else:
        cy += 1

    # dhcp
    dhcp = si.dhcp_status(info["name"])
    if dhcp == "dhcp_ok":
        safe_addstr(stdscr, cy, x + 2, i18n.tr(code, "iface_dhcp_working"),
                    curses.color_pair(CP_OK) | curses.A_BOLD)
    elif dhcp == "dhcp_fail":
        safe_addstr(stdscr, cy, x + 2, i18n.tr(code, "iface_dhcp_not_working"),
                    curses.color_pair(CP_ERR) | curses.A_BOLD)
    else:
        safe_addstr(stdscr, cy, x + 2, i18n.tr(code, "iface_static"),
                    curses.color_pair(CP_WARN) | curses.A_BOLD)
    cy += 2

    # arp scan
    safe_addstr(stdscr, cy, x + 2, i18n.tr(code, "iface_arp_title"),
                curses.color_pair(CP_TITLE) | curses.A_BOLD); cy += 1
    network = None
    if info.get("ip") and cidr is not None:
        network = f"{info['ip']}/{cidr}"
    arp.start(info["name"], network)
    ips = arp.get(info["name"])
    if ips:
        # wrap into lines fitting w-4
        line = ""
        for ip in ips:
            piece = (ip + ", ")
            if len(line) + len(piece) > w - 4:
                if cy >= y + h - 1:
                    break
                safe_addstr(stdscr, cy, x + 2, line.rstrip(", "))
                cy += 1
                line = piece
            else:
                line += piece
        if line and cy < y + h - 1:
            safe_addstr(stdscr, cy, x + 2, line.rstrip(", "))
    else:
        safe_addstr(stdscr, cy, x + 2, "scanning...",
                    curses.color_pair(CP_HINT))


# --------------- Edit view ---------------

EDIT_BUTTONS_ROW1 = ["iface_change_ip", "iface_change_mask", "iface_change_gw",
                     "iface_static_dhcp", "iface_reset_svc", "iface_rename",
                     "iface_nano"]
EDIT_BUTTONS_ROW2 = ["iface_dns1", "iface_dns2", "iface_add_dns",
                     "iface_del_dns", "iface_onoff", "iface_back"]


def _draw_edit_buttons(stdscr, y, w, code, sel_r, sel_c, dhcp_mode: str, iface_up: bool):
    """Draw 2 rows of buttons strictly inside width `w` (must NOT overflow into right INFO panel)."""
    rows = [EDIT_BUTTONS_ROW1, EDIT_BUTTONS_ROW2]
    for r, row in enumerate(rows):
        labels = []
        for key in row:
            lbl = i18n.tr(code, key)
            if key == "iface_static_dhcp":
                tag = "DHCP" if dhcp_mode == "dhcp_ok" else ("DHCP?" if dhcp_mode == "dhcp_fail" else "STATIC")
                lbl = "MODE: " + tag
            if key == "iface_onoff":
                lbl = ("OFF" if iface_up else "ON ") + " IFACE"
            if dhcp_mode == "dhcp_ok" and key in ("iface_change_ip", "iface_change_mask", "iface_change_gw"):
                lbl = i18n.tr(code, "iface_blocked_dhcp")
            labels.append((key, lbl))

        n = len(row)
        gap = 1
        # bw fits inside w: n*bw + (n+1)*gap <= w  =>  bw <= (w - (n+1)*gap) // n
        max_bw = max(6, (w - (n + 1) * gap) // n)
        # natural width from labels (with small padding) but capped to max_bw
        nat_bw = max(len(l) for _, l in labels) + 4
        bw = min(nat_bw, max_bw)
        total = n * bw + (n + 1) * gap
        x_start = max(gap, (w - total) // 2)

        for c, (key, lbl) in enumerate(labels):
            disabled = (dhcp_mode == "dhcp_ok"
                        and key in ("iface_change_ip", "iface_change_mask", "iface_change_gw"))
            sel = (r == sel_r and c == sel_c)
            label = lbl[:bw - 2].center(bw - 2)
            top = " " + "_" * (bw - 2) + " "
            mid = "|" + label + "|"
            bot = "|" + "_" * (bw - 2) + "|"
            if disabled:
                attr = curses.color_pair(CP_WARN)
            elif sel:
                attr = curses.color_pair(CP_BTN_SEL) | curses.A_BOLD
            else:
                attr = curses.color_pair(CP_BTN)
            xx = x_start + c * (bw + gap)
            yy = y + r * 4
            safe_addstr(stdscr, yy, xx, top, attr)
            safe_addstr(stdscr, yy + 1, xx, mid, attr)
            safe_addstr(stdscr, yy + 2, xx, bot, attr)


def _edit_action(stdscr, iface_name: str, key: str, code: str) -> bool:
    """Returns True to go back to list."""
    info = si.interface_by_name(iface_name)
    if not info:
        return True
    if key == "iface_back":
        return True
    if key == "iface_change_ip":
        s = prompt_text(stdscr, i18n.tr(code, "iface_enter_ip"))
        if s:
            cidr = info.get("cidr") or 24
            ok, e = si.iface_set_ip(iface_name, s.strip(), int(cidr))
            info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                     else i18n.tr(code, "iface_failed") + e)
    elif key == "iface_change_mask":
        s = prompt_text(stdscr, i18n.tr(code, "iface_enter_mask"))
        if s:
            cidr = si.parse_cidr(s)
            if cidr is None:
                info_box(stdscr, i18n.tr(code, "iface_failed") + "bad mask")
            elif not info.get("ip"):
                info_box(stdscr, "no current IP")
            else:
                ok, e = si.iface_set_ip(iface_name, str(info["ip"]), cidr)
                mask_txt = f" /{cidr} = {si.cidr_to_netmask(cidr)}"
                info_box(stdscr, (i18n.tr(code, "iface_applied") + mask_txt) if ok
                         else i18n.tr(code, "iface_failed") + e)
    elif key == "iface_change_gw":
        s = prompt_text(stdscr, i18n.tr(code, "iface_enter_gw"))
        if s:
            ok, e = si.iface_set_gw(iface_name, s.strip())
            info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                     else i18n.tr(code, "iface_failed") + e)
    elif key == "iface_static_dhcp":
        cur = si.dhcp_status(iface_name)
        enable = cur == "static"
        ok, e = si.iface_set_dhcp(iface_name, enable)
        info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                 else i18n.tr(code, "iface_failed") + e)
    elif key == "iface_reset_svc":
        ok, e = si.restart_network()
        info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                 else i18n.tr(code, "iface_failed") + e)
    elif key == "iface_rename":
        s = prompt_text(stdscr, i18n.tr(code, "iface_enter_name"))
        if s:
            ok, e = si.iface_rename(iface_name, s.strip())
            info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                     else i18n.tr(code, "iface_failed") + e)
            return True  # back to list, name changed
    elif key == "iface_nano":
        # find config file
        candidates = [
            f"/etc/NetworkManager/system-connections/{iface_name}.nmconnection",
            f"/etc/netplan/01-{iface_name}.yaml",
            "/etc/network/interfaces",
            f"/etc/sysconfig/network-scripts/ifcfg-{iface_name}",
        ]
        target = next((c for c in candidates if os.path.exists(c)),
                      "/etc/network/interfaces")
        curses.endwin()
        try:
            subprocess.call(["nano", target])
        except FileNotFoundError:
            pass
        stdscr.clear()
        stdscr.refresh()
    elif key == "iface_dns1":
        s = prompt_text(stdscr, i18n.tr(code, "iface_enter_dns"))
        if s:
            dns = list(info.get("dns") or [])
            if dns:
                dns[0] = s.strip()
            else:
                dns = [s.strip()]
            ok, e = si.dns_set(dns)
            info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                     else i18n.tr(code, "iface_failed") + e)
    elif key == "iface_dns2":
        s = prompt_text(stdscr, i18n.tr(code, "iface_enter_dns"))
        if s:
            dns = list(info.get("dns") or [])
            if len(dns) >= 2:
                dns[1] = s.strip()
            elif len(dns) == 1:
                dns.append(s.strip())
            else:
                dns = ["", s.strip()]
            ok, e = si.dns_set([d for d in dns if d])
            info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                     else i18n.tr(code, "iface_failed") + e)
    elif key == "iface_add_dns":
        s = prompt_text(stdscr, i18n.tr(code, "iface_enter_dns"))
        if s:
            dns = list(info.get("dns") or [])
            dns.append(s.strip())
            ok, e = si.dns_set(dns)
            info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                     else i18n.tr(code, "iface_failed") + e)
    elif key == "iface_del_dns":
        more = info.get("more_dns") or []
        if not more:
            info_box(stdscr, "-")
        else:
            idx = menu_choice(stdscr, i18n.tr(code, "iface_more_dns"), more)
            if idx is not None:
                dns = list(info.get("dns") or [])
                victim = more[idx]
                dns = [d for d in dns if d != victim]
                ok, e = si.dns_set(dns)
                info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                         else i18n.tr(code, "iface_failed") + e)
    elif key == "iface_onoff":
        ok, e = si.iface_up_down(iface_name, not info["up"])
        info_box(stdscr, i18n.tr(code, "iface_applied") if ok
                 else i18n.tr(code, "iface_failed") + e)
    return False


def _edit_view(stdscr, iface_name: str, arp: si.ArpScanner, code: str):
    sel_r, sel_c = 0, 0
    stdscr.nodelay(True)
    stdscr.timeout(500)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        draw_header(stdscr)
        safe_addstr(stdscr, 0, w - 40,
                    f"{i18n.tr(code,'iface_edit_title')}: {iface_name}",
                    curses.color_pair(CP_TITLE) | curses.A_BOLD)

        # split: left = buttons, right = info
        left_w = (w * 6) // 10
        right_x = left_w + 1
        right_w = w - right_x - 1
        btn_y = 8
        info = si.interface_by_name(iface_name)
        dhcp_mode = si.dhcp_status(iface_name)
        iface_up = bool(info["up"]) if info else False
        _draw_edit_buttons(stdscr, btn_y, left_w, code, sel_r, sel_c,
                           dhcp_mode, iface_up)

        draw_box(stdscr, 7, right_x, h - 9, right_w, " INFO ")
        _draw_iface_info(stdscr, right_x, 7, right_w, h - 9,
                         iface_name, arp, code)

        draw_shortcuts(stdscr,
                       "ARROWS=move  ENTER=apply  ESC=back to list")
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == -1:
            continue
        if ch == 27:
            return
        if ch == curses.KEY_LEFT:
            sel_c = (sel_c - 1) % len(EDIT_BUTTONS_ROW1)
        elif ch == curses.KEY_RIGHT:
            sel_c = (sel_c + 1) % len(EDIT_BUTTONS_ROW1)
        elif ch == curses.KEY_UP:
            sel_r = 0
            sel_c = min(sel_c, len(EDIT_BUTTONS_ROW1) - 1)
        elif ch == curses.KEY_DOWN:
            sel_r = 1
            sel_c = min(sel_c, len(EDIT_BUTTONS_ROW2) - 1)
        elif ch in (10, 13, curses.KEY_ENTER):
            rows = [EDIT_BUTTONS_ROW1, EDIT_BUTTONS_ROW2]
            key = rows[sel_r][sel_c]
            back = _edit_action(stdscr, iface_name, key, code)
            if back:
                return


# --------------- List view ---------------

def _draw_list_buttons(stdscr, y, w, names, sel, page, per_page, has_prev, has_next):
    """Draws interface tile buttons in a 4-col grid; reserves slots for BACK/NEXT."""
    start = page * per_page
    end = min(len(names), start + per_page)
    page_names = names[start:end]
    # Build the slot list (display labels), with BACK at slot 0 if has_prev,
    # NEXT at last slot if has_next.
    cols = 4
    rows = max(1, (per_page + cols - 1) // cols)
    slot_labels = [None] * (rows * cols)
    idx = 0
    for i, n in enumerate(page_names):
        slot_labels[idx] = ("iface", start + i, n)
        idx += 1
        # skip slots reserved
    # place BACK/NEXT
    if has_prev:
        slot_labels[0] = ("back", -1, "<< BACK")
    if has_next:
        slot_labels[-1] = ("next", -1, "NEXT >>")

    # equal sizing
    bw = 16
    gap = max(2, (w - bw * cols) // (cols + 1))
    for s_idx, slot in enumerate(slot_labels):
        if slot is None:
            continue
        r = s_idx // cols
        c = s_idx % cols
        x = gap + c * (bw + gap)
        yy = y + r * 4
        sel_here = (s_idx == sel)
        attr = curses.color_pair(CP_BTN_SEL) | curses.A_BOLD if sel_here \
            else curses.color_pair(CP_BTN)
        top = " " + "_" * (bw - 2) + " "
        mid = "|" + slot[2].center(bw - 2) + "|"
        bot = "|" + "_" * (bw - 2) + "|"
        safe_addstr(stdscr, yy, x, top, attr)
        safe_addstr(stdscr, yy + 1, x, mid, attr)
        safe_addstr(stdscr, yy + 2, x, bot, attr)


def launch(stdscr):
    from . import config
    code = config.load().get("lang", "en")
    init_colors()
    stdscr.nodelay(True)
    stdscr.timeout(500)
    arp = si.ArpScanner()
    sel = 0
    page = 0
    try:
        while True:
            ifaces = [it["name"] for it in si.list_interfaces()]
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            draw_header(stdscr)
            safe_addstr(stdscr, 0, w - 30, i18n.tr(code, "iface_title"),
                        curses.color_pair(CP_TITLE) | curses.A_BOLD)

            left_w = (w * 6) // 10
            right_x = left_w + 1
            right_w = w - right_x - 1
            btn_y = 8

            # pagination
            cols = 4
            row_capacity = 4  # rows
            per_page = cols * row_capacity
            total_pages = max(1, (len(ifaces) + per_page - 1) // per_page)
            page = min(page, total_pages - 1)
            has_prev = page > 0
            has_next = page < total_pages - 1
            start = page * per_page
            end = min(len(ifaces), start + per_page)
            visible_names = ifaces[start:end]

            # build slot mapping
            slots = [None] * per_page
            i = 0
            for n in visible_names:
                slots[i] = n
                i += 1
            if has_prev:
                slots[0] = "__BACK__"
            if has_next:
                slots[-1] = "__NEXT__"
            # constrain sel
            valid = [k for k, v in enumerate(slots) if v is not None]
            if not valid:
                valid = [0]
            if sel not in valid:
                sel = valid[0]

            # draw buttons — bw must fit strictly within left_w
            gap = 1
            bw = max(8, (left_w - (cols + 1) * gap) // cols)
            x_start = max(gap, (left_w - (bw * cols + (cols + 1) * gap)) // 2 + gap)
            for s_idx, slot in enumerate(slots):
                if slot is None:
                    continue
                r = s_idx // cols
                c = s_idx % cols
                x = x_start + c * (bw + gap)
                yy = btn_y + r * 4
                if slot == "__BACK__":
                    lbl = "<< BACK"
                elif slot == "__NEXT__":
                    lbl = "NEXT >>"
                else:
                    lbl = slot
                sel_here = (s_idx == sel)
                attr = curses.color_pair(CP_BTN_SEL) | curses.A_BOLD if sel_here \
                    else curses.color_pair(CP_BTN)
                label = lbl[:bw - 2].center(bw - 2)
                top = " " + "_" * (bw - 2) + " "
                mid = "|" + label + "|"
                bot = "|" + "_" * (bw - 2) + "|"
                safe_addstr(stdscr, yy, x, top, attr)
                safe_addstr(stdscr, yy + 1, x, mid, attr)
                safe_addstr(stdscr, yy + 2, x, bot, attr)

            # right info
            draw_box(stdscr, 7, right_x, h - 9, right_w, " INFO ")
            cur = slots[sel] if 0 <= sel < len(slots) else None
            if cur and cur not in ("__BACK__", "__NEXT__"):
                _draw_iface_info(stdscr, right_x, 7, right_w, h - 9,
                                 cur, arp, code)
            else:
                safe_addstr(stdscr, 9, right_x + 2,
                            "Najedz na interfejs", curses.color_pair(CP_HINT))

            draw_shortcuts(stdscr,
                           f"ARROWS=move  ENTER=open/page  ESC=back  page {page+1}/{total_pages}")
            stdscr.refresh()

            ch = stdscr.getch()
            if ch == -1:
                continue
            if ch == 27:
                return
            if ch == curses.KEY_LEFT:
                # find prev valid
                for k in range(sel - 1, -1, -1):
                    if slots[k] is not None:
                        sel = k; break
            elif ch == curses.KEY_RIGHT:
                for k in range(sel + 1, len(slots)):
                    if slots[k] is not None:
                        sel = k; break
            elif ch == curses.KEY_UP:
                target = sel - cols
                if target >= 0 and slots[target] is not None:
                    sel = target
            elif ch == curses.KEY_DOWN:
                target = sel + cols
                if target < len(slots) and slots[target] is not None:
                    sel = target
            elif ch in (ord("n"), ord("N"), curses.KEY_NPAGE):
                if has_next:
                    page += 1; sel = 0
            elif ch in (ord("b"), ord("B"), curses.KEY_PPAGE):
                if has_prev:
                    page -= 1; sel = 0
            elif ch in (10, 13, curses.KEY_ENTER):
                cur = slots[sel]
                if cur == "__BACK__" and has_prev:
                    page -= 1; sel = 0
                elif cur == "__NEXT__" and has_next:
                    page += 1; sel = 0
                elif cur:
                    _edit_view(stdscr, cur, arp, code)
    finally:
        arp.stop()
