"""System info helpers: hostname, user, network, processes, services, users, groups."""
from __future__ import annotations
import os
import socket
import subprocess
import ipaddress
import pwd
import grp
import threading
import time
import shutil
from typing import List, Dict, Optional, Tuple

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None  # type: ignore


# ============================================================
# basic
# ============================================================

def hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def username() -> str:
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"


def run(cmd: list, timeout: int = 5) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except Exception as e:
        return 1, "", str(e)


# ============================================================
# Network
# ============================================================

def _read_default_gw_dns() -> Dict[str, Dict[str, object]]:
    info: Dict[str, Dict[str, object]] = {}
    rc, out, _ = run(["ip", "route"], timeout=2)
    for line in out.splitlines():
        if line.startswith("default"):
            parts = line.split()
            gw, dev = None, None
            if "via" in parts:
                gw = parts[parts.index("via") + 1]
            if "dev" in parts:
                dev = parts[parts.index("dev") + 1]
            if dev:
                info.setdefault(dev, {})["gw"] = gw
    dns: List[str] = []
    try:
        for line in open("/etc/resolv.conf"):
            if line.startswith("nameserver"):
                p = line.split()
                if len(p) > 1:
                    dns.append(p[1])
    except Exception:
        pass
    for v in info.values():
        v["dns"] = dns
    return info


def _global_dns() -> List[str]:
    out = []
    try:
        for line in open("/etc/resolv.conf"):
            if line.startswith("nameserver"):
                p = line.split()
                if len(p) > 1:
                    out.append(p[1])
    except Exception:
        pass
    return out


def list_interfaces() -> List[Dict[str, object]]:
    """All interfaces (except lo) with ip/mask/cidr/gw/dns list."""
    result: List[Dict[str, object]] = []
    if psutil is None:
        return result
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    extra = _read_default_gw_dns()
    dns_global = _global_dns()

    for name, alist in addrs.items():
        if name == "lo":
            continue
        ip = mask = None
        cidr = None
        mac = None
        for a in alist:
            fam = getattr(a, "family", None)
            if fam == socket.AF_INET and not ip:
                ip = a.address
                mask = a.netmask
                if mask:
                    try:
                        cidr = sum(bin(int(o)).count("1") for o in mask.split("."))
                    except Exception:
                        cidr = None
            elif getattr(socket, "AF_PACKET", None) and fam == socket.AF_PACKET and not mac:
                mac = a.address
        st = stats.get(name)
        up = bool(st.isup) if st else False
        gw = extra.get(name, {}).get("gw") if extra.get(name) else None
        dns = extra.get(name, {}).get("dns") or dns_global
        result.append({
            "name": name,
            "up": up,
            "ip": ip,
            "mask": mask,
            "cidr": cidr,
            "gw": gw,
            "mac": mac,
            "dns": list(dns),
            "dns1": dns[0] if len(dns) > 0 else None,
            "dns2": dns[1] if len(dns) > 1 else None,
            "more_dns": dns[2:] if len(dns) > 2 else [],
        })
    result.sort(key=lambda x: (not x["up"], x["name"]))
    return result


def interface_by_name(name: str) -> Optional[Dict[str, object]]:
    for it in list_interfaces():
        if it["name"] == name:
            return it
    return None


def network_calc(ip: str, cidr: int) -> Dict[str, object]:
    try:
        net = ipaddress.ip_network(f"{ip}/{cidr}", strict=False)
        hosts = net.num_addresses - 2 if net.num_addresses >= 2 else 0
        return {
            "network": str(net.network_address),
            "broadcast": str(net.broadcast_address),
            "hosts": hosts,
            "prefix": net.prefixlen,
        }
    except Exception:
        return {"network": None, "broadcast": None, "hosts": 0, "prefix": cidr}


def cidr_to_netmask(cidr: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{cidr}").netmask)


def _nm_connection_for_device(iface: str) -> Optional[str]:
    rc, out, _ = run(["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"], timeout=3)
    if rc == 0:
        for line in out.splitlines():
            if ":" in line:
                con, dev = line.rsplit(":", 1)
                if dev.strip() == iface:
                    return con.replace("\\:", ":").strip()
    rc, out, _ = run(["nmcli", "-t", "-f", "GENERAL.CONNECTION", "device", "show", iface], timeout=3)
    if rc == 0:
        for line in out.splitlines():
            if ":" in line:
                con = line.split(":", 1)[1].strip()
                if con and con != "--":
                    return con.replace("\\:", ":")
    return None


def dhcp_status(iface: str) -> str:
    """Return 'static', 'dhcp_ok', 'dhcp_fail'."""
    # NetworkManager check first. ipv4.method is a connection property, not
    # reliably present in `nmcli device show`, so read the active profile.
    con = _nm_connection_for_device(iface)
    if con:
        rc, out, _ = run(["nmcli", "-g", "ipv4.method", "connection", "show", con], timeout=2)
        method = out.strip().lower() if rc == 0 else ""
        if method == "manual":
            return "static"
        if method == "auto":
            rc_ip, out_ip, _ = run(["ip", "-o", "-4", "addr", "show", "dev", iface], timeout=2)
            return "dhcp_ok" if rc_ip == 0 and " inet " in out_ip else "dhcp_fail"
    # Check dhclient lease
    lease_paths = [
        f"/var/lib/dhcp/dhclient.{iface}.leases",
        f"/var/lib/dhclient/dhclient-{iface}.leases",
        f"/var/lib/NetworkManager/internal-{iface}.lease",
    ]
    for p in lease_paths:
        if os.path.exists(p):
            try:
                age = time.time() - os.path.getmtime(p)
                if age < 24 * 3600:
                    return "dhcp_ok"
            except Exception:
                pass
    # ip -d link
    rc, out, _ = run(["ip", "-d", "addr", "show", "dev", iface], timeout=2)
    if "dynamic" in out:
        return "dhcp_ok"
    return "static"


def arp_neighbors(iface: str, network: Optional[str], limit: int = 50) -> List[str]:
    """Return list of neighbour IPs from ARP cache for iface."""
    rc, out, _ = run(["ip", "neigh", "show", "dev", iface], timeout=2)
    ips = []
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        ip = parts[0]
        if network:
            try:
                net = ipaddress.ip_network(network, strict=False)
                if ipaddress.ip_address(ip) not in net:
                    continue
            except Exception:
                pass
        if "FAILED" in line.upper():
            continue
        ips.append(ip)
        if len(ips) >= limit:
            break
    return ips


# Background ARP scanner
class ArpScanner:
    def __init__(self):
        self.results: Dict[str, List[str]] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._target: Optional[Tuple[str, Optional[str]]] = None
        self._lock = threading.Lock()

    def start(self, iface: str, network: Optional[str]):
        with self._lock:
            self._target = (iface, network)
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get(self, iface: str) -> List[str]:
        return self.results.get(iface, [])

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                tgt = self._target
            if tgt:
                iface, network = tgt
                # try active scan if arp-scan present, else passive
                rc, out, _ = run(["arp-scan", "-q", "-l", "-I", iface], timeout=5)
                if rc == 0 and out:
                    ips = []
                    for line in out.splitlines():
                        parts = line.split()
                        if parts and parts[0].count(".") == 3:
                            try:
                                ipaddress.ip_address(parts[0])
                                if network:
                                    if ipaddress.ip_address(parts[0]) not in \
                                            ipaddress.ip_network(network, strict=False):
                                        continue
                                ips.append(parts[0])
                            except Exception:
                                continue
                        if len(ips) >= 50:
                            break
                    self.results[iface] = ips
                else:
                    # passive: trigger ping sweep softly then read neighbours
                    if network:
                        try:
                            net = ipaddress.ip_network(network, strict=False)
                            if net.num_addresses <= 256:
                                for h in list(net.hosts())[:50]:
                                    if self._stop.is_set():
                                        break
                                    subprocess.run(
                                        ["ping", "-c", "1", "-W", "1", str(h)],
                                        capture_output=True, timeout=2,
                                    )
                        except Exception:
                            pass
                    self.results[iface] = arp_neighbors(iface, network, 50)
            for _ in range(5):
                if self._stop.is_set():
                    return
                time.sleep(1)


# ============================================================
# Network mutation
# ============================================================

def parse_cidr(input_str: str) -> Optional[int]:
    s = input_str.strip().lstrip("/")
    if s.isdigit():
        n = int(s)
        return n if 0 <= n <= 32 else None
    # full mask
    try:
        parts = s.split(".")
        if len(parts) == 4:
            mask = ipaddress.IPv4Address(s)
            bits = bin(int(mask))[2:].zfill(32)
            if "01" in bits:
                return None
            return bits.count("1")
    except Exception:
        return None
    return None


def _admin_cmd(cmd: List[str]) -> List[str]:
    if os.geteuid() == 0:
        return cmd
    sudo = shutil.which("sudo")
    return [sudo, "-n", *cmd] if sudo else cmd


def _privilege_hint(err: str = "") -> str:
    msg = (err or "").strip()
    if os.geteuid() != 0:
        hint = "brak uprawnien: uruchom SYSGO jako root (sudo python3 autorun.py)"
        return f"{hint}; {msg}" if msg else hint
    return msg


def _run_admin(cmd: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    rc, out, err = run(_admin_cmd(cmd), timeout=timeout)
    return rc, out, _privilege_hint(err) if rc != 0 else err


def _iface_ipv4_cidr(name: str) -> Tuple[Optional[str], Optional[int]]:
    rc, out, _ = run(["ip", "-o", "-4", "addr", "show", "dev", name], timeout=2)
    if rc == 0:
        parts = out.split()
        for i, p in enumerate(parts):
            if p == "inet" and i + 1 < len(parts):
                try:
                    ip, cidr = parts[i + 1].split("/", 1)
                    return ip, int(cidr)
                except Exception:
                    return None, None
    info = interface_by_name(name)
    return (str(info.get("ip")), int(info.get("cidr"))) if info and info.get("ip") and info.get("cidr") is not None else (None, None)


def _iface_gateway(name: str) -> Optional[str]:
    rc, out, _ = run(["ip", "route", "show", "default", "dev", name], timeout=2)
    for line in out.splitlines():
        parts = line.split()
        if "via" in parts:
            return parts[parts.index("via") + 1]
    info = interface_by_name(name)
    gw = info.get("gw") if info else None
    return str(gw) if gw else None


def iface_set_ip(name: str, ip: str, cidr: int) -> Tuple[bool, str]:
    """Set static IPv4 and persist it where possible. Always verifies live state."""
    try:
        ipaddress.IPv4Address(ip)
        if cidr < 0 or cidr > 32:
            return False, "bad mask"
    except Exception:
        return False, "bad ip"
    gw = _iface_gateway(name)
    con = _nm_connection_for_device(name)
    errors: List[str] = []
    if con:
        args = ["nmcli", "connection", "modify", con,
                "ipv4.method", "manual", "ipv4.addresses", f"{ip}/{cidr}"]
        if gw:
            args += ["ipv4.gateway", gw]
        rc, _, e = _run_admin(args, timeout=10)
        if rc != 0:
            errors.append(e)
        rc, _, e = _run_admin(["nmcli", "connection", "up", con], timeout=20)
        if rc != 0:
            errors.append(e)
    rc1, _, e1 = _run_admin(["ip", "addr", "flush", "dev", name], timeout=5)
    rc2, _, e2 = _run_admin(["ip", "addr", "add", f"{ip}/{cidr}", "dev", name], timeout=5)
    _run_admin(["ip", "link", "set", name, "up"], timeout=5)
    if gw:
        _run_admin(["ip", "route", "replace", "default", "via", gw, "dev", name], timeout=5)
    if rc2 != 0:
        errors.append(e2 or e1)
    time.sleep(0.4)
    live_ip, live_cidr = _iface_ipv4_cidr(name)
    if live_ip == ip and live_cidr == cidr:
        return True, ""
    return False, "; ".join([e for e in errors if e]) or f"verify failed: {live_ip}/{live_cidr}, wanted {ip}/{cidr} ({cidr_to_netmask(cidr)})"


def iface_set_gw(name: str, gw: str) -> Tuple[bool, str]:
    try:
        ipaddress.IPv4Address(gw)
    except Exception:
        return False, "bad gateway"
    con = _nm_connection_for_device(name)
    errors: List[str] = []
    if con:
        rc, _, e = _run_admin(["nmcli", "connection", "modify", con, "ipv4.gateway", gw], timeout=10)
        if rc != 0:
            errors.append(e)
        _run_admin(["nmcli", "connection", "up", con], timeout=20)
    rc, _, e = _run_admin(["ip", "route", "replace", "default", "via", gw, "dev", name], timeout=5)
    if rc != 0:
        errors.append(e)
    time.sleep(0.2)
    return (_iface_gateway(name) == gw, "; ".join([x for x in errors if x]) or "verify failed")


def iface_up_down(name: str, up: bool) -> Tuple[bool, str]:
    rc, _, e = _run_admin(["ip", "link", "set", name, "up" if up else "down"])
    return rc == 0, e


def iface_rename(old: str, new: str) -> Tuple[bool, str]:
    _run_admin(["ip", "link", "set", old, "down"])
    rc, _, e = _run_admin(["ip", "link", "set", old, "name", new])
    _run_admin(["ip", "link", "set", new, "up"])
    return rc == 0, e


def dns_set(servers: List[str]) -> Tuple[bool, str]:
    clean = []
    for server in servers:
        if not server:
            continue
        try:
            clean.append(str(ipaddress.ip_address(server.strip())))
        except Exception:
            return False, f"bad dns: {server}"
    conns = [it["name"] for it in list_interfaces() if it.get("up")]
    errors: List[str] = []
    for iface in conns:
        con = _nm_connection_for_device(str(iface))
        if con:
            rc, _, e = _run_admin(["nmcli", "connection", "modify", con, "ipv4.dns", ",".join(clean)], timeout=10)
            if rc != 0:
                errors.append(e)
            _run_admin(["nmcli", "connection", "up", con], timeout=20)
    try:
        lines = [f"nameserver {s}\n" for s in clean]
        with open("/etc/resolv.conf", "w") as f:
            f.write("# Managed by SYSGO\n")
            f.writelines(lines)
        return True, ""
    except Exception as e:
        return False, _privilege_hint(str(e) or "; ".join(errors))


def iface_set_dhcp(name: str, enable: bool) -> Tuple[bool, str]:
    """Switch interface between DHCP and STATIC. Verifies result afterwards."""
    errors = []
    # 1) Try NetworkManager first
    rc, _, _ = run(["which", "nmcli"], timeout=1)
    nm_ok = False
    if rc == 0:
        con_name = _nm_connection_for_device(name)
        if con_name:
            if enable:
                rc_mod, _, e_mod = _run_admin(["nmcli", "connection", "modify", con_name, "ipv4.method", "auto",
                                                "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""], timeout=10)
            else:
                cur_ip, cur_cidr = _iface_ipv4_cidr(name)
                args = ["nmcli", "connection", "modify", con_name, "ipv4.method", "manual"]
                if cur_ip and cur_cidr is not None:
                    args += ["ipv4.addresses", f"{cur_ip}/{cur_cidr}"]
                gw = _iface_gateway(name)
                if gw:
                    args += ["ipv4.gateway", gw]
                rc_mod, _, e_mod = _run_admin(args, timeout=10)
            if rc_mod != 0:
                errors.append(f"nmcli modify: {e_mod}")
            rc2, _, e2 = _run_admin(["nmcli", "connection", "up", con_name], timeout=20)
            if rc2 != 0:
                errors.append(f"nmcli up: {e2}")
            else:
                nm_ok = True
        else:
            rc2, _, e2 = _run_admin(["nmcli", "device", "modify", name, "ipv4.method",
                                      "auto" if enable else "manual"], timeout=10)
            if rc2 == 0:
                _run_admin(["nmcli", "device", "reapply", name], timeout=10)
                nm_ok = True
            else:
                errors.append(f"nmcli mod: {e2}")
    # 2) Fallback: dhclient / flush
    if not nm_ok:
        if enable:
            _run_admin(["ip", "addr", "flush", "dev", name])
            _run_admin(["dhclient", "-r", name], timeout=10)
            rc2, _, e = _run_admin(["dhclient", name], timeout=20)
            if rc2 != 0:
                errors.append(f"dhclient: {e}")
        else:
            rc2, _, e = _run_admin(["dhclient", "-r", name], timeout=10)
            if rc2 != 0:
                errors.append(f"dhclient -r: {e}")
    # 3) VERIFY result
    time.sleep(1.0)
    status = dhcp_status(name)
    want_dhcp = enable
    is_dhcp = status in ("dhcp_ok", "dhcp_fail")
    if want_dhcp == is_dhcp:
        return True, ""
    return False, ("verify failed: status=" + status + ("; " + "; ".join(errors) if errors else ""))


def restart_network() -> Tuple[bool, str]:
    for svc in ("NetworkManager", "systemd-networkd", "networking"):
        rc, _, _ = run(["systemctl", "is-active", svc])
        if rc == 0:
            rc2, _, e = run(["systemctl", "restart", svc], timeout=15)
            return rc2 == 0, e
    return False, "no network service detected"


# ============================================================
# processes
# ============================================================

def list_processes(filter_text: str = "") -> List[Dict[str, object]]:
    out = []
    if psutil is None:
        return out
    ft = filter_text.lower().strip()
    for p in psutil.process_iter(["pid", "username", "cpu_percent",
                                  "memory_percent", "name"]):
        try:
            info = p.info
            name = info.get("name") or ""
            if ft and ft not in name.lower() and ft not in str(info.get("pid")):
                continue
            out.append({
                "pid": info.get("pid"),
                "user": (info.get("username") or "")[:12],
                "cpu": float(info.get("cpu_percent") or 0.0),
                "mem": float(info.get("memory_percent") or 0.0),
                "name": name,
            })
        except Exception:
            continue
    out.sort(key=lambda x: x["cpu"], reverse=True)
    return out


def kill_pid(pid: int, hard: bool = False) -> bool:
    if psutil is None:
        return False
    try:
        p = psutil.Process(pid)
        if hard:
            p.kill()
        else:
            p.terminate()
        return True
    except Exception:
        return False


# ============================================================
# services
# ============================================================

TRACKED_SERVICES = ["samba", "smbd", "apache2", "httpd", "ufw",
                    "ssh", "sshd", "nginx", "NetworkManager"]


def service_status(name: str) -> Optional[str]:
    try:
        r = subprocess.run(["systemctl", "is-active", name],
                           capture_output=True, text=True, timeout=2)
        state = r.stdout.strip()
        if state == "active":
            return "active"
        if state == "failed":
            return "failed"
        if state == "inactive":
            r2 = subprocess.run(
                ["systemctl", "list-unit-files", f"{name}.service"],
                capture_output=True, text=True, timeout=2,
            )
            if name in r2.stdout:
                return "inactive"
            return None
        return "unknown"
    except FileNotFoundError:
        return None
    except Exception:
        return "unknown"


def list_services() -> List[Dict[str, str]]:
    seen = set()
    out = []
    for n in TRACKED_SERVICES:
        if n in seen:
            continue
        seen.add(n)
        s = service_status(n)
        if s is not None:
            out.append({"name": n.upper(), "status": s})
    return out


def restart_service(name: str) -> Tuple[bool, str]:
    rc, _, e = run(["systemctl", "restart", name], timeout=15)
    return rc == 0, e


# ============================================================
# users & groups
# ============================================================

def list_users(min_uid: int = 1000, include_root: bool = True) -> List[Dict[str, object]]:
    out = []
    if include_root:
        try:
            r = pwd.getpwnam("root")
            out.append(_user_dict(r))
        except KeyError:
            pass
    for u in pwd.getpwall():
        if u.pw_uid >= min_uid and u.pw_name != "nobody":
            out.append(_user_dict(u))
    return out


def _user_dict(u) -> Dict[str, object]:
    groups = []
    try:
        gids = os.getgrouplist(u.pw_name, u.pw_gid)
        for gid in gids:
            try:
                groups.append(grp.getgrgid(gid).gr_name)
            except KeyError:
                continue
    except Exception:
        pass
    is_sudo = any(g in ("sudo", "wheel", "admin") for g in groups)
    return {
        "name": u.pw_name,
        "uid": u.pw_uid,
        "gid": u.pw_gid,
        "home": u.pw_dir,
        "shell": u.pw_shell,
        "groups": groups,
        "is_sudo": is_sudo,
        "locked": _is_user_locked(u.pw_name),
        "login_state": user_login_state(u.pw_name),
    }


def _is_user_locked(name: str) -> bool:
    rc, out, _ = run(["passwd", "-S", name], timeout=2)
    if rc == 0 and out:
        parts = out.split()
        if len(parts) >= 2:
            state = parts[1].upper()
            if state in ("L", "LK"):
                return True
            if state in ("P", "PS", "NP"):
                return False
    try:
        import spwd  # type: ignore
        pw = spwd.getspnam(name).sp_pwdp
        return pw.startswith("!") or pw.startswith("*")
    except Exception:
        pass
    return False


def user_login_state(name: str) -> str:
    rc, out, _ = run(["who"], timeout=2)
    if rc != 0 or not out.strip():
        return "unlogged"
    lines = [line for line in out.splitlines() if line.split() and line.split()[0] == name]
    if not lines:
        return "unlogged"
    if any("(" in line and ")" in line for line in lines):
        return "logged-ssh"
    return "logged"


def user_exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def list_groups() -> List[str]:
    return sorted({g.gr_name for g in grp.getgrall()})


def sudo_group_name() -> str:
    # Detect distro convention
    names = {g.gr_name for g in grp.getgrall()}
    if "wheel" in names:
        return "wheel"
    if "sudo" in names:
        return "sudo"
    return "sudo"


def add_user(name: str, uid: Optional[int], password: Optional[str],
             sudo: bool) -> Tuple[bool, str]:
    cmd = ["useradd", "-m"]
    if uid is not None:
        cmd += ["-u", str(uid)]
    cmd.append(name)
    rc, _, e = run(cmd, timeout=10)
    if rc != 0:
        return False, e
    if password:
        proc = subprocess.run(["chpasswd"], input=f"{name}:{password}",
                              text=True, capture_output=True, timeout=10)
        if proc.returncode != 0:
            return False, proc.stderr
    if sudo:
        run(["usermod", "-aG", sudo_group_name(), name])
    return True, ""


def del_user(name: str) -> Tuple[bool, str]:
    if name == "root":
        return False, "cannot remove root"
    rc, _, e = run(["userdel", "-r", name], timeout=10)
    return rc == 0, e


def set_user_password(name: str, password: str) -> Tuple[bool, str]:
    proc = subprocess.run(["chpasswd"], input=f"{name}:{password}",
                          text=True, capture_output=True, timeout=10)
    return proc.returncode == 0, proc.stderr


def toggle_sudo(name: str) -> Tuple[bool, str]:
    info = next((u for u in list_users() if u["name"] == name), None)
    if not info:
        return False, "no user"
    sg = sudo_group_name()
    if info["is_sudo"]:
        rc, _, e = run(["gpasswd", "-d", name, sg], timeout=5)
    else:
        rc, _, e = run(["usermod", "-aG", sg, name], timeout=5)
    return rc == 0, e


def lock_user(name: str, lock: bool) -> Tuple[bool, str]:
    rc, _, e = run(["usermod", "-L" if lock else "-U", name], timeout=5)
    return rc == 0, e


def force_password_change(name: str) -> Tuple[bool, str]:
    rc, _, e = run(["chage", "-d", "0", name], timeout=5)
    return rc == 0, e


def rename_user(old: str, new: str) -> Tuple[bool, str]:
    rc, _, e = run(["usermod", "-l", new, "-d", f"/home/{new}", "-m", old], timeout=10)
    return rc == 0, e


def change_uid(name: str, uid: int) -> Tuple[bool, str]:
    rc, _, e = run(["usermod", "-u", str(uid), name], timeout=10)
    return rc == 0, e


def add_to_group(user: str, group: str) -> Tuple[bool, str]:
    rc, _, e = run(["usermod", "-aG", group, user], timeout=5)
    return rc == 0, e


def remove_from_group(user: str, group: str) -> Tuple[bool, str]:
    rc, _, e = run(["gpasswd", "-d", user, group], timeout=5)
    return rc == 0, e


def user_login_logs(name: str, limit: int = 30) -> List[str]:
    out_lines: List[str] = []
    rc, out, _ = run(["last", "-n", str(limit), name], timeout=5)
    if rc == 0:
        out_lines += [l for l in out.splitlines() if l.strip()]
    rc, out, _ = run(["lastb", "-n", "10", name], timeout=5)
    if rc == 0 and out:
        out_lines.append("--- failed ---")
        out_lines += [l for l in out.splitlines() if l.strip()]
    return out_lines


def set_login_notice(name: str, message: str) -> Tuple[bool, str]:
    try:
        u = pwd.getpwnam(name)
    except KeyError:
        return False, "no user"
    home = u.pw_dir
    try:
        os.makedirs(home, mode=0o755, exist_ok=True)
        path = os.path.join(home, ".sysgo_motd")
        with open(path, "w") as f:
            f.write(message.rstrip() + "\n")
        os.chown(path, u.pw_uid, u.pw_gid)
        os.chmod(path, 0o644)
        for profile in (".profile", ".bash_profile", ".bashrc"):
            p = os.path.join(home, profile)
            existing = ""
            if os.path.exists(p):
                with open(p) as f:
                    existing = f.read()
            line = "\n[ -f \"$HOME/.sysgo_motd\" ] && cat \"$HOME/.sysgo_motd\"\n"
            if "sysgo_motd" not in existing:
                with open(p, "a") as f:
                    f.write(line)
                os.chown(p, u.pw_uid, u.pw_gid)
        return True, ""
    except Exception as e:
        return False, _privilege_hint(str(e))


# ============================================================
# system settings
# ============================================================

def os_pretty() -> str:
    try:
        for line in open("/etc/os-release"):
            if line.startswith("PRETTY_NAME"):
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return "Linux"


def set_hostname(name: str) -> Tuple[bool, str]:
    rc, _, e = _run_admin(["hostnamectl", "set-hostname", name], timeout=5)
    return rc == 0, e


def timezone_get() -> str:
    rc, out, _ = run(["timedatectl", "show", "--value", "-p", "Timezone"], timeout=2)
    return out.strip() if rc == 0 else "?"


def timezone_list() -> List[str]:
    rc, out, _ = run(["timedatectl", "list-timezones"], timeout=5)
    return out.splitlines() if rc == 0 else []


def timezone_set(tz: str) -> Tuple[bool, str]:
    rc, _, e = _run_admin(["timedatectl", "set-timezone", tz], timeout=5)
    return rc == 0, e


def ntp_set(enable: bool) -> Tuple[bool, str]:
    rc, _, e = _run_admin(["timedatectl", "set-ntp", "true" if enable else "false"], timeout=5)
    return rc == 0, e


def time_set(value: str) -> Tuple[bool, str]:
    ntp_set(False)
    rc, _, e = _run_admin(["timedatectl", "set-time", value], timeout=5)
    return rc == 0, e


def locale_set(locale: str) -> Tuple[bool, str]:
    rc, _, e = _run_admin(["localectl", "set-locale", f"LANG={locale}"], timeout=10)
    return rc == 0, e


def keyboard_set(keymap: str) -> Tuple[bool, str]:
    rc, _, e = _run_admin(["localectl", "set-keymap", keymap], timeout=10)
    return rc == 0, e


def time_status() -> str:
    rc, out, _ = run(["timedatectl"], timeout=2)
    return out if rc == 0 else "?"


def locale_get() -> str:
    rc, out, _ = run(["localectl", "status"], timeout=2)
    for line in out.splitlines():
        if "System Locale" in line:
            return line.split(":", 1)[1].strip()
    return "?"


def keyboard_get() -> str:
    rc, out, _ = run(["localectl", "status"], timeout=2)
    for line in out.splitlines():
        if "Keymap" in line:
            return line.split(":", 1)[1].strip()
    return "?"


def scheduled_shutdown() -> Optional[str]:
    rc, out, _ = run(["shutdown", "--show"], timeout=2)
    if rc == 0 and out.strip():
        return out.strip()
    # systemd-based
    try:
        if os.path.exists("/run/systemd/shutdown/scheduled"):
            return open("/run/systemd/shutdown/scheduled").read().strip()
    except Exception:
        pass
    return None


def schedule_shutdown(seconds: int) -> Tuple[bool, str]:
    mins = max(1, seconds // 60)
    rc, _, e = run(["shutdown", f"+{mins}"], timeout=5)
    return rc == 0, e


def cancel_shutdown() -> Tuple[bool, str]:
    rc, _, e = run(["shutdown", "-c"], timeout=5)
    return rc == 0, e


# ============================================================
# logs
# ============================================================

class JournalTail:
    def __init__(self):
        self.lines: List[str] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            proc = subprocess.Popen(
                ["journalctl", "-f", "-n", "40", "--no-pager", "-o", "short"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            for line in proc.stdout:  # type: ignore
                if self._stop.is_set():
                    proc.terminate()
                    return
                self.lines.append(line.rstrip())
                if len(self.lines) > 200:
                    self.lines = self.lines[-200:]
        except Exception:
            pass
