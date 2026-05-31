# SYSGO

YaST-like text/graphical UI for Linux server administration.

## Install

```bash
sudo python3 autorun.py
```

Choose **Install**. After it finishes, run:

```bash
sudo sysgo
```

Supported distributions: Debian, Ubuntu (+ derivatives), openSUSE Leap/Tumbleweed, Fedora/RHEL/Rocky/Alma, Arch, Manjaro, CachyOS, EndeavourOS, Garuda.

## Actions in the installer

- **Install**   - installs base packages and copies SYSGO to `/opt/sysgo` + launcher `/usr/local/bin/sysgo`.
- **Repair**    - reinstalls base packages and SYSGO files (preserves `/etc/sysgo/config.json`).
- **Uninstall** - removes only SYSGO CLI/UI files. Packages and configs stay.

## First run

On the first launch SYSGO plays a short welcome animation and asks for language (POLSKI / ENGLISH / NORWAY) and menu size. The choice is saved to `/etc/sysgo/config.json`.

## Main menu

- Left panel: hostname, current user, up to 3 active interfaces, services with color-coded status.
- Right panel: live process list.
- Bottom: 8 action buttons.

Keys:

- arrows  - move between buttons / scroll list
- ENTER   - activate
- ESC     - back / exit confirmation
- TAB     - toggle focus to process list
- In process list: `F` filter, `T` terminate, `K` kill (no warning).
