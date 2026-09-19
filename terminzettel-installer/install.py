#!/usr/bin/env python3
"""Installation mit Vorprüfung, Sicherung und Rücknahme bei Fehlern."""
from __future__ import annotations

import base64
import grp
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from setup_config import plan, remove_block, tomllib
import cups_queue

SOURCE = Path(__file__).resolve().parent
STATE = Path("/var/lib/terminzettel/install-state.json")
SERVICES = ("smbd.service", "cups.path", "cups.socket", "cups.service")
CONFIGS = ("/etc/samba/smb.conf", "/etc/cups/cups-files.conf", "/etc/cups/cupsd.conf")


def run(*args, optional=False):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if result.returncode and not optional:
        raise RuntimeError("Systemprüfung fehlgeschlagen: " + args[0] + ". Keine erfolgreiche Installation.")
    return result


def snapshot(path: Path):
    if path.is_symlink():
        raise ValueError("Eine zu verwaltende Datei ist ein symbolischer Link; keine Änderung.")
    if not path.exists():
        return None
    info = path.stat()
    return {"data": base64.b64encode(path.read_bytes()).decode(), "mode": info.st_mode & 0o777,
            "uid": info.st_uid, "gid": info.st_gid}


def atomic_write(path: Path, data: bytes, mode=0o644, uid=None, gid=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".terminzettel-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            os.fchmod(fh.fileno(), mode)
            if uid is not None and gid is not None:
                os.fchown(fh.fileno(), uid, gid)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def restore(files):
    for name, previous in files.items():
        path = Path(name)
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, base64.b64decode(previous["data"]), previous["mode"], previous["uid"], previous["gid"])


def check_idle():
    result = run("lpstat", "-h", "/run/cups/cups.sock", "-W", "not-completed", "-o")
    if result.stdout.strip():
        raise RuntimeError("Es sind noch CUPS-Druckaufträge vorhanden. Bitte zuerst abschließen und Installation erneut starten.")


def start_previous(active):
    run("systemctl", "daemon-reload")
    for service in reversed(SERVICES):
        if service in active:
            run("systemctl", "start", service)


def prepare_runtime():
    run("getent", "group", "lp")
    if run("getent", "group", "terminzettel", optional=True).returncode:
        run("groupadd", "--system", "terminzettel")
    if run("id", "terminzettel", optional=True).returncode:
        run("useradd", "--system", "--gid", "terminzettel", "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin", "terminzettel")
    runtime = Path("/run/terminzettel")
    runtime.mkdir(mode=0o755, exist_ok=True)
    if run("mountpoint", "-q", str(runtime), optional=True).returncode:
        if any(runtime.iterdir()):
            raise RuntimeError("Das RAM-Zielverzeichnis ist nicht leer; keine Dateien werden verdeckt.")
        result = run("mount", "-t", "tmpfs", "-o", "size=128M,mode=0755,nosuid,nodev,noexec", "tmpfs", str(runtime), optional=True)
        if result.returncode:
            raise RuntimeError("Das temporäre RAM-Dateisystem konnte nicht eingehängt werden.")
    # Prüft auch eine bereits vorhandene Einhängung, bevor Daten dorthin gehen.
    mount = run("findmnt", "-n", "-o", "FSTYPE,OPTIONS", "--mountpoint", str(runtime)).stdout.decode().split()
    if len(mount) != 2 or mount[0] != "tmpfs":
        raise RuntimeError("Das vorhandene Laufzeitverzeichnis ist kein temporäres RAM-Dateisystem.")
    for owner, group, mode, names in [
        ("terminzettel", "terminzettel", "0700", ("spool", "work")),
        ("root", "lp", "0710", ("cups",)),
        ("root", "lp", "1770", ("cups/tmp",)),
        ("lp", "lp", "0700", ("cups-cache",)),
        ("root", "root", "0755", ("samba-cache",)),
    ]:
        run("install", "-d", "-o", owner, "-g", group, "-m", mode, *(str(runtime / name) for name in names))


def validate(changes):
    with tempfile.TemporaryDirectory(prefix="setup-", dir="/run/terminzettel") as td:
        for name in CONFIGS:
            Path(td, Path(name).name).write_text(changes[name])
        run("testparm", "-s", str(Path(td, "smb.conf")))
        run("cupsd", "-t", "-c", str(Path(td, "cupsd.conf")), "-s", str(Path(td, "cups-files.conf")))


def write_file(name, text, prior):
    mode, gid = (prior["mode"], prior["gid"]) if prior else (0o644, 0)
    if name.endswith("/config.toml"):
        mode, gid = 0o640, grp.getgrnam("terminzettel").gr_gid
        Path(name).parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(Path(name).parent, 0, gid)
        os.chmod(Path(name).parent, 0o750)
    if name.endswith("/terminzettel-submit"):
        mode = 0o755
    if name == "/usr/lib/cups/backend/terminzettel":
        mode = 0o700  # CUPS öffnet die Eingabe als root; das Backend gibt die Rechte sofort ab.
    atomic_write(Path(name), text.encode(), mode, 0, gid)


def install():
    changes = plan(SOURCE)  # Konflikte und beschädigte Marker vor Dienständerungen erkennen.
    queue = tomllib.loads(changes["/etc/terminzettel/config.toml"])["output"]["queue"]
    role = run("testparm", "-s", "--parameter-name=server role").stdout.decode().strip()
    if role not in ("standalone server", "auto"):
        raise RuntimeError("Der einfache Installer unterstützt nur einen eigenständigen Samba-Server.")
    run("lpstat", "-h", "/run/cups/cups.sock", "-p", queue)
    check_idle()
    previous = json.loads(STATE.read_text()) if STATE.exists() else {"originals": {}}
    virtual_before = cups_queue.inspect_queue(previous.get("cups_queue", False))
    before = {name: snapshot(Path(name)) for name in changes}
    originals = dict(previous["originals"])
    for name, saved in before.items():
        if name not in originals:
            originals[name] = saved
        if name in CONFIGS and saved:
            # Fremde zwischenzeitliche Änderungen bleiben auch bei Deinstallation erhalten.
            clean = remove_block(base64.b64decode(saved["data"]).decode())
            originals[name] = dict(saved, data=base64.b64encode(clean.encode()).decode())
        if ("/etc/systemd/" in name or name == "/usr/lib/cups/backend/terminzettel") and name not in previous["originals"] and saved is not None:
            raise RuntimeError("Eine fremde Terminzettel-Systemdatei existiert bereits; keine Änderung.")
    prepare_runtime()
    validate(changes)
    active = {service for service in SERVICES if run("systemctl", "is-active", "--quiet", service, optional=True).returncode == 0}
    timer_enabled = run("systemctl", "is-enabled", "--quiet", "terminzettel-cleanup.timer", optional=True).returncode == 0
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE.parent, 0o700)
    atomic_write(STATE.with_name("last-backup.json"), json.dumps(before).encode(), 0o600, 0, 0)
    added_queue = False
    try:
        run("systemctl", "stop", "smbd.service")
        check_idle()
        for service in SERVICES[1:]:
            if service == "cups.service" or service in active:
                run("systemctl", "stop", service)
        for name, text in changes.items():
            write_file(name, text, before[name])
        run("systemctl", "daemon-reload")
        run("systemctl", "start", "terminzettel-runtime.service")
        run("systemctl", "restart", "cups.service", "smbd.service")
        start_previous(active)
        if virtual_before is None:
            added_queue = True  # Auch eine teilweise angelegte Warteschlange zurücknehmen.
            cups_queue.create_queue(run)
        cups_queue.verify_queue()
        run("systemctl", "enable", "--now", "terminzettel-cleanup.timer")
        run("testparm", "-s")
        run("lpstat", "-h", "/run/cups/cups.sock", "-p", queue)
        state = {"originals": originals, "cups_queue": True,
                 "installed": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in changes.items()}}
        atomic_write(STATE, json.dumps(state).encode(), 0o600, 0, 0)
    except BaseException:
        if added_queue:
            cups_queue.delete_queue(run, optional=True)
        for service in SERVICES:
            run("systemctl", "stop", service, optional=True)
        if not timer_enabled:
            run("systemctl", "disable", "--now", "terminzettel-cleanup.timer", optional=True)
        restore(before)
        start_previous(active)
        raise
    print("Installation abgeschlossen. CUPS-/Bonjour-Drucker Terminzettel ist freigegeben.")
    print("Am Mac unter Drucker hinzufügen > Default den Terminzettel auswählen.")
    print("Kopf und Fuß: /etc/terminzettel/config.toml")
    print("CUPS und Samba verwenden jetzt RAM-Zwischenspeicher auf diesem Rechner.")


def uninstall():
    if not STATE.is_file():
        raise RuntimeError("Keine passende Installationssicherung gefunden. Es wird nichts entfernt.")
    state = json.loads(STATE.read_text())
    for name, checksum in state["installed"].items():
        path = Path(name)
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise RuntimeError("Installierte Dateien wurden nachträglich geändert. Bitte vor Deinstallation prüfen; es wird nichts überschrieben.")
    virtual_before = cups_queue.inspect_queue(state.get("cups_queue", False))
    check_idle()
    active = {service for service in SERVICES if run("systemctl", "is-active", "--quiet", service, optional=True).returncode == 0}
    before = {name: snapshot(Path(name)) for name in state["installed"]}
    removed_queue = False
    try:
        run("systemctl", "stop", "smbd.service")
        check_idle()
        if virtual_before is not None:
            removed_queue = True
            cups_queue.delete_queue(run)
        for service in SERVICES[1:]:
            if service == "cups.service" or service in active:
                run("systemctl", "stop", service)
        run("systemctl", "disable", "--now", "terminzettel-cleanup.timer")
        restore(state["originals"])
        run("systemctl", "stop", "terminzettel-runtime.service")
        run("umount", "/run/terminzettel")
        start_previous(active)
    except BaseException:
        restore(before)
        start_previous(active)
        if removed_queue:
            cups_queue.restore_queue(run, virtual_before)
        run("systemctl", "enable", "--now", "terminzettel-cleanup.timer", optional=True)
        raise
    STATE.unlink()
    print("Terminzettel entfernt; vorherige Druckkonfiguration wiederhergestellt.")
    print("Der Dienstbenutzer, Paketabhängigkeiten und die Installationssicherung bleiben erhalten.")


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Bitte mit sudo ausführen.")
    if sys.argv[1:] == ["--uninstall"]:
        uninstall()
    elif not sys.argv[1:]:
        install()
    else:
        raise RuntimeError("Unbekannte Option.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Ausschließlich Installationsfehler, keine Druckjob-Ausgaben weiterreichen.
        message = str(exc) if type(exc) in (RuntimeError, ValueError) else "Installation fehlgeschlagen; Systemzustand prüfen."
        print("terminzettel: " + message, file=sys.stderr)
        raise SystemExit(1)
