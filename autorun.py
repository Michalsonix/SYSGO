#!/usr/bin/env python3
"""
SYSGO installer / repair / uninstaller.
Run with: sudo python3 autorun.py
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

INSTALL_DIR = Path("/opt/sysgo")
BIN_PATH = Path("/usr/local/bin/sysgo")
CONFIG_DIR = Path("/etc/sysgo")

SUPPORTED = {
    # id -> (family, install_cmd, pkgs)
    "debian":   ("debian", ["apt-get", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),
    "ubuntu":   ("debian", ["apt-get", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),
    "linuxmint":("debian", ["apt-get", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),
    "pop":      ("debian", ["apt-get", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),
    "raspbian": ("debian", ["apt-get", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),
    "kali":     ("debian", ["apt-get", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),

    "opensuse-leap":      ("suse", ["zypper", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),
    "opensuse-tumbleweed":("suse", ["zypper", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),
    "opensuse":           ("suse", ["zypper", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),
    "sles":               ("suse", ["zypper", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute2"]),

    "fedora":   ("fedora", ["dnf", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute"]),
    "rhel":     ("fedora", ["dnf", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute"]),
    "centos":   ("fedora", ["dnf", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute"]),
    "rocky":    ("fedora", ["dnf", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute"]),
    "almalinux":("fedora", ["dnf", "install", "-y"], ["python3", "python3-pip", "python3-psutil", "iproute"]),

    "arch":     ("arch", ["pacman", "-S", "--noconfirm", "--needed"], ["python", "python-pip", "python-psutil", "iproute2"]),
    "manjaro":  ("arch", ["pacman", "-S", "--noconfirm", "--needed"], ["python", "python-pip", "python-psutil", "iproute2"]),
    "cachyos":  ("arch", ["pacman", "-S", "--noconfirm", "--needed"], ["python", "python-pip", "python-psutil", "iproute2"]),
    "endeavouros":("arch", ["pacman", "-S", "--noconfirm", "--needed"], ["python", "python-pip", "python-psutil", "iproute2"]),
    "garuda":   ("arch", ["pacman", "-S", "--noconfirm", "--needed"], ["python", "python-pip", "python-psutil", "iproute2"]),
}


def detect_distro():
    info = {}
    p = Path("/etc/os-release")
    if not p.exists():
        return None, None
    for line in p.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k] = v.strip().strip('"')
    did = info.get("ID", "").lower()
    id_like = info.get("ID_LIKE", "").lower().split()
    pretty = info.get("PRETTY_NAME", did)

    if did in SUPPORTED:
        return did, pretty
    for parent in id_like:
        if parent in SUPPORTED:
            return parent, pretty
    return None, pretty


def require_root():
    if os.geteuid() != 0:
        print("\033[1;31m[!] SYSGO installer must be run as root.\033[0m")
        print("    Try:  sudo python3 autorun.py")
        sys.exit(1)


def banner():
    os.system("clear")
    print("\033[1;36m")
    print("=" * 80)
    print("                          S Y S G O   I N S T A L L E R")
    print("=" * 80)
    print("\033[0m")


def menu():
    banner()
    distro_id, pretty = detect_distro()
    if not distro_id:
        print(f"\033[1;31m[!] Unsupported distribution: {pretty}\033[0m")
        print("    Supported families: Debian/Ubuntu, openSUSE, Fedora/RHEL, Arch/Manjaro/CachyOS.")
        sys.exit(2)

    print(f"  Detected distribution : \033[1;32m{pretty}\033[0m  (family: {SUPPORTED[distro_id][0]})")
    print()
    print("  [1] Install      - install SYSGO and required base packages")
    print("  [2] Repair       - reinstall SYSGO files and packages (keeps user config)")
    print("  [3] Uninstall    - remove SYSGO CLI/UI (keeps packages and configs)")
    print("  [0] Quit")
    print()
    while True:
        choice = input("  > ").strip()
        if choice in {"0", "1", "2", "3"}:
            return choice, distro_id


def run_pkg_install(distro_id):
    family, cmd, pkgs = SUPPORTED[distro_id]
    print(f"\n\033[1;34m[*] Installing base packages via {cmd[0]}...\033[0m")
    if family == "debian":
        subprocess.run(["apt-get", "update"], check=False)
    try:
        subprocess.run(cmd + pkgs, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\033[1;31m[!] Package installation failed: {e}\033[0m")
        sys.exit(3)


def copy_app():
    src = Path(__file__).resolve().parent / "sysgo"
    if not src.exists():
        print(f"\033[1;31m[!] Missing source dir: {src}\033[0m")
        sys.exit(4)
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
    shutil.copytree(src, INSTALL_DIR)
    os.chmod(INSTALL_DIR, 0o755)
    print(f"\033[1;32m[+] Copied SYSGO to {INSTALL_DIR}\033[0m")


def install_launcher():
    launcher = f"""#!/usr/bin/env bash
exec /usr/bin/env python3 {INSTALL_DIR}/main.py "$@"
"""
    BIN_PATH.write_text(launcher)
    BIN_PATH.chmod(0o755)
    print(f"\033[1;32m[+] Installed launcher at {BIN_PATH}\033[0m")


def ensure_config(distro_id):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    marker = CONFIG_DIR / "distro"
    marker.write_text(distro_id + "\n")
    # first-run marker is absent on fresh install
    fr = CONFIG_DIR / "first_run_done"
    if fr.exists():
        fr.unlink()
    print(f"\033[1;32m[+] Initialized config at {CONFIG_DIR}\033[0m")


def do_install(distro_id):
    run_pkg_install(distro_id)
    copy_app()
    install_launcher()
    ensure_config(distro_id)
    print("\n\033[1;32m[OK] SYSGO installed. Run:  sudo sysgo\033[0m\n")


def do_repair(distro_id):
    run_pkg_install(distro_id)
    copy_app()
    install_launcher()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "distro").write_text(distro_id + "\n")
    print("\n\033[1;32m[OK] SYSGO repaired. User config preserved.\033[0m\n")


def do_uninstall():
    removed = []
    if BIN_PATH.exists():
        BIN_PATH.unlink()
        removed.append(str(BIN_PATH))
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
        removed.append(str(INSTALL_DIR))
    if removed:
        print("\n\033[1;32m[OK] Removed:\033[0m " + ", ".join(removed))
    else:
        print("\n\033[1;33m[i] Nothing to remove.\033[0m")
    print("    Packages and configs were kept intact.\n")


def main():
    require_root()
    while True:
        choice, distro_id = menu()
        if choice == "1":
            do_install(distro_id); break
        if choice == "2":
            do_repair(distro_id); break
        if choice == "3":
            do_uninstall(); break
        if choice == "0":
            sys.exit(0)


if __name__ == "__main__":
    main()
