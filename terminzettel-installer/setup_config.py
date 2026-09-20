#!/usr/bin/env python3
"""Kleine, testbare Konfigurationsbausteine für den Installer."""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

BEGIN = "# BEGIN TERMINZETTEL MANAGED"
END = "# END TERMINZETTEL MANAGED"
APPARMOR_PROFILE = "/etc/apparmor.d/usr.sbin.cupsd"
APPARMOR_LOCAL = "/etc/apparmor.d/local/usr.sbin.cupsd"


def remove_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if not begins and not ends:
        return text
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        raise ValueError("Beschädigter Terminzettel-Verwaltungsblock; keine Änderung vorgenommen.")
    return "".join(lines[:begins[0]] + lines[ends[0] + 1:])


def managed(text: str, body: str) -> str:
    clean = remove_block(text)
    return clean.rstrip() + "\n\n" + BEGIN + "\n" + body.strip() + "\n" + END + "\n"


def samba_config(text: str) -> str:
    clean = remove_block(text)
    sections = re.findall(r"^\s*\[([^]\n]+)\]", clean, re.M)
    if any(re.sub(r"\s+", "", name).casefold() == "terminzettel" for name in sections):
        raise ValueError("Eine fremde Freigabe Terminzettel existiert bereits.")
    return managed(clean, """
[global]
    cache directory = /run/terminzettel/samba-cache
    log file = /dev/null
    logging = file
    log level = 0

[Terminzettel]
    comment = T2med Terminbeleg 58mm
    path = /run/terminzettel/spool
    printable = yes
    browseable = yes
    guest ok = yes
    read only = yes
    use client driver = yes
    force user = terminzettel
    force group = terminzettel
    printjob username = terminzettel
    printing = bsd
    print command = /usr/local/sbin/terminzettel-submit "%s"
    lpq command =
    lprm command =
""")


def cups_files_config(text: str) -> str:
    return managed(text, """
RequestRoot /run/terminzettel/cups
TempDir /run/terminzettel/cups/tmp
CacheDir /run/terminzettel/cups-cache
AccessLog /dev/null
PageLog /dev/null
ErrorLog /dev/null
""")


def cups_daemon_config(text: str) -> str:
    return managed(text, """
PreserveJobHistory No
PreserveJobFiles No
""")


def migrate_config(text: str, defaults: dict | None = None) -> str:
    cfg = tomllib.loads(text)
    cfg.setdefault("input", {}).setdefault("ocr_if_needed", True)
    cfg.setdefault("layout", {}).setdefault("double_height", True)
    cfg["layout"].setdefault("double_width", True)
    if defaults and "calendar_qr" not in cfg:
        cfg["calendar_qr"] = defaults["calendar_qr"]
    output = cfg.setdefault("output", {})
    if output.get("server", "localhost") not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Die alte Konfiguration nutzt einen entfernten Druckserver. Lokale CUPS-Warteschlange erforderlich.")
    cfg["output"] = {
        "queue": output.get("queue", output.get("share", "TMm10")),
        "format": output.get("format", "escpos"),
        "text_encoding": output.get("text_encoding", "utf-8"),
    }
    queue = cfg["output"]["queue"]
    if not isinstance(queue, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", queue) or queue.casefold() == "terminzettel":
        raise ValueError("Ungültige CUPS-Zielwarteschlange.")
    cfg.pop("debug", None)
    return dump_config(cfg)


def dump_config(cfg: dict) -> str:
    result = ["# Terminzettel: lokale CUPS-Ausgabe, keine Belegspeicherung.\n"]
    for name, values in cfg.items():
        if not isinstance(values, dict) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("Ungültiger Konfigurationsabschnitt.")
        result.append("[" + name + "]")
        for key, value in values.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or type(value) not in (str, int, bool):
                raise ValueError("Ungültiger Konfigurationswert.")
            result.append(key + " = " + json.dumps(value, ensure_ascii=False))
        result.append("")
    return "\n".join(result)


MOUNT = """[Unit]
Description=Fluechtige Druckdaten fuer Terminzettel und CUPS
Before=terminzettel-runtime.service

[Mount]
What=tmpfs
Where=/run/terminzettel
Type=tmpfs
Options=size=128M,mode=0755,nosuid,nodev,noexec

[Install]
WantedBy=multi-user.target
"""

RUNTIME = """[Unit]
Description=Terminzettel RAM-Verzeichnisse
Requires=run-terminzettel.mount
After=run-terminzettel.mount
Before=smbd.service cups.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/install -d -o terminzettel -g terminzettel -m 0700 /run/terminzettel/spool /run/terminzettel/work
ExecStart=/usr/bin/install -d -o root -g lp -m 0710 /run/terminzettel/cups
ExecStart=/usr/bin/install -d -o root -g lp -m 1770 /run/terminzettel/cups/tmp
ExecStart=/usr/bin/install -d -o lp -g lp -m 0700 /run/terminzettel/cups-cache
ExecStart=/usr/bin/install -d -o root -g root -m 0755 /run/terminzettel/samba-cache
"""

DROPIN = """[Unit]
Requires=terminzettel-runtime.service
After=terminzettel-runtime.service

[Service]
LimitCORE=0
"""

CLEANUP_SERVICE = """[Unit]
Description=Verwaiste Terminzettel-Auftraege entfernen
Requires=terminzettel-runtime.service
After=terminzettel-runtime.service cups.service

[Service]
Type=oneshot
User=terminzettel
Group=terminzettel
LimitCORE=0
ExecStart=/usr/local/sbin/terminzettel-submit --cleanup
TimeoutStartSec=30
"""

CLEANUP_TIMER = """[Unit]
Description=Terminzettel-Bereinigung

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
"""

WRAPPER = """#!/bin/sh
umask 077
ulimit -c 0
exec /usr/bin/python3 -B /usr/local/lib/terminzettel/terminzettel.py "$@"
"""

BACKEND = """#!/bin/sh
exec /usr/bin/python3 -B /usr/local/lib/terminzettel/cups_backend.py "$@"
"""


def plan(source: Path, root: Path = Path("/")) -> dict[str, str]:
    def read(path):
        return (root / path.lstrip("/")).read_text()
    config = root / "etc/terminzettel/config.toml"
    defaults = (source / "config.toml").read_text()
    changes = {
        "/etc/samba/smb.conf": samba_config(read("/etc/samba/smb.conf")),
        "/etc/cups/cups-files.conf": cups_files_config(read("/etc/cups/cups-files.conf")),
        "/etc/cups/cupsd.conf": cups_daemon_config(read("/etc/cups/cupsd.conf")),
        "/etc/terminzettel/config.toml": migrate_config(config.read_text() if config.exists() else defaults, tomllib.loads(defaults)),
        "/usr/local/lib/terminzettel/terminzettel.py": (source / "terminzettel.py").read_text(),
        "/usr/local/lib/terminzettel/calendar_qr.py": (source / "calendar_qr.py").read_text(),
        "/usr/local/lib/terminzettel/escpos.py": (source / "escpos.py").read_text(),
        "/usr/local/lib/terminzettel/cups_backend.py": (source / "cups_backend.py").read_text(),
        "/usr/local/share/terminzettel/terminzettel.ppd": (source / "terminzettel.ppd").read_text(),
        "/usr/lib/cups/backend/terminzettel": BACKEND,
        "/usr/local/sbin/terminzettel-submit": WRAPPER,
        "/usr/local/share/doc/terminzettel/README.md": (source / "README.md").read_text(),
        "/etc/systemd/system/run-terminzettel.mount": MOUNT,
        "/etc/systemd/system/terminzettel-runtime.service": RUNTIME,
        "/etc/systemd/system/cups.service.d/terminzettel.conf": DROPIN,
        "/etc/systemd/system/smbd.service.d/terminzettel.conf": DROPIN,
        "/etc/systemd/system/terminzettel-cleanup.service": CLEANUP_SERVICE,
        "/etc/systemd/system/terminzettel-cleanup.timer": CLEANUP_TIMER,
    }
    if (root / APPARMOR_PROFILE.lstrip("/")).is_file():
        local = root / APPARMOR_LOCAL.lstrip("/")
        changes[APPARMOR_LOCAL] = managed(local.read_text() if local.exists() else "", """
/{,var/}run/terminzettel/cups/{,**} rwk,
/{,var/}run/terminzettel/cups-cache/{,**} rwk,
""")
    return changes
