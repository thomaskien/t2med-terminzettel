#!/usr/bin/env bash
set -euo pipefail

APP_NAME="terminzettel"
APP_USER="terminzettel"
APP_GROUP="terminzettel"
APP_DIR="/usr/local/lib/terminzettel"
APP_PY="$APP_DIR/terminzettel.py"
WRAPPER="/usr/local/sbin/terminzettel-submit"
CONFIG_DIR="/etc/terminzettel"
CONFIG_FILE="$CONFIG_DIR/config.toml"
DOC_DIR="/usr/local/share/doc/terminzettel"
SPOOL_DIR="/var/spool/samba/terminzettel"
SMB_CONF="/etc/samba/smb.conf"
BEGIN_MARK="# BEGIN TERMINZETTEL MANAGED"
END_MARK="# END TERMINZETTEL MANAGED"

need_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "Bitte als root ausführen: sudo $0" >&2
    exit 1
  fi
}

reload_samba() {
  if command -v systemctl >/dev/null 2>&1; then
    systemctl reload smbd 2>/dev/null || systemctl restart smbd 2>/dev/null || true
  elif command -v service >/dev/null 2>&1; then
    service smbd restart 2>/dev/null || true
  fi
}

remove_managed_block() {
  local file="$1"
  local tmp
  tmp="$(mktemp)"
  awk -v begin="$BEGIN_MARK" -v end="$END_MARK" '
    $0 == begin {skip=1; next}
    $0 == end   {skip=0; next}
    !skip {print}
  ' "$file" > "$tmp"
  cat "$tmp" > "$file"
  rm -f "$tmp"
}

uninstall_app() {
  need_root
  if [[ -f "$SMB_CONF" ]]; then
    cp -a "$SMB_CONF" "$SMB_CONF.terminzettel-uninstall-$(date +%Y%m%d-%H%M%S).bak"
    remove_managed_block "$SMB_CONF"
    if command -v testparm >/dev/null 2>&1; then
      testparm -s "$SMB_CONF" >/dev/null
    fi
    reload_samba
  fi
  rm -f "$WRAPPER"
  rm -rf "$APP_DIR" "$CONFIG_DIR" "$DOC_DIR" "$SPOOL_DIR"
  if id "$APP_USER" >/dev/null 2>&1; then userdel "$APP_USER" 2>/dev/null || true; fi
  if getent group "$APP_GROUP" >/dev/null 2>&1; then groupdel "$APP_GROUP" 2>/dev/null || true; fi
  echo "Terminzettel wurde entfernt. Samba-Backup wurde angelegt."
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall_app
  exit 0
fi

need_root

echo "==> Installiere Abhängigkeiten"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3 samba smbclient poppler-utils ghostscript
  # XPS-Unterstützung ist optional.
  apt-get install -y libgxps-utils >/dev/null 2>&1 || true
else
  echo "Kein apt-get gefunden. Bitte installieren: python3 samba smbclient poppler-utils ghostscript" >&2
  exit 1
fi

if ! python3 - <<'PYTOML' >/dev/null 2>&1
try:
    import tomllib
except ModuleNotFoundError:
    import tomli
PYTOML
then
  apt-get install -y python3-tomli
fi

echo "==> Lege Systembenutzer und Verzeichnisse an"
if ! getent group "$APP_GROUP" >/dev/null 2>&1; then
  groupadd --system "$APP_GROUP"
fi
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --gid "$APP_GROUP" --home-dir /nonexistent --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -o root -g root -m 0755 "$APP_DIR" "$DOC_DIR"
install -d -o root -g "$APP_GROUP" -m 0750 "$CONFIG_DIR"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0770 "$SPOOL_DIR"

echo "==> Installiere Programm"
cat > "$APP_PY" <<'__TERMINZETTEL_PY__'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

DEFAULT_CONFIG = "/etc/terminzettel/config.toml"

WEEKDAYS = {
    "Mo": "Mo.", "Di": "Di.", "Mi": "Mi.", "Do": "Do.",
    "Fr": "Fr.", "Sa": "Sa.", "So": "So.",
}

APPOINTMENT_RE = re.compile(
    r"^\s*(?P<weekday>Mo|Di|Mi|Do|Fr|Sa|So)\.?\s+"
    r"(?P<date>\d{1,2}\.\d{1,2}\.\d{4}),\s*"
    r"(?P<time>\d{1,2}:\d{2})\s+"
    r"(?P<type>\S.*)\s*$"
)


@dataclass
class Appointment:
    weekday: str
    date: str
    time: str
    kind: str

    @property
    def dt(self) -> datetime:
        return datetime.strptime(f"{self.date} {self.time}", "%d.%m.%Y %H:%M")


@dataclass
class ParsedTicket:
    patient: str
    appointments: list[Appointment]


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def log(msg: str) -> None:
    eprint(f"terminzettel: {msg}")
    logger = shutil.which("logger")
    if logger:
        try:
            subprocess.run([logger, "-t", "terminzettel", msg], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def load_config(path: str) -> dict[str, Any]:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def run_checked(args: list[str], *, input_bytes: bytes | None = None) -> bytes:
    proc = subprocess.run(args, input=input_bytes, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"Befehl fehlgeschlagen ({proc.returncode}): {' '.join(args)}\n{stderr}")
    return proc.stdout


def detect_input(path: str) -> str:
    with open(path, "rb") as fh:
        head = fh.read(16)
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"%!PS"):
        return "postscript"
    if head.startswith(b"PK\x03\x04"):
        return "xps"
    return "text"


def extract_text(path: str, cfg: dict[str, Any]) -> str:
    kind = detect_input(path)
    input_cfg = cfg.get("input", {})
    log(f"Eingabeformat erkannt: {kind}")

    if kind == "pdf":
        return run_checked(["pdftotext", "-layout", path, "-"]).decode("utf-8", "replace")

    if kind == "postscript":
        with tempfile.TemporaryDirectory(prefix="terminzettel-") as td:
            pdf = os.path.join(td, "input.pdf")
            run_checked([
                "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
                f"-sOutputFile={pdf}", path,
            ])
            return run_checked(["pdftotext", "-layout", pdf, "-"]).decode("utf-8", "replace")

    if kind == "xps":
        gxps = shutil.which("gxps2pdf")
        if not gxps:
            raise RuntimeError(
                "XPS-Druckjob erkannt, aber gxps2pdf fehlt. Installiere Paket libgxps-utils "
                "oder verwende auf dem Client einen PDF/PostScript-Druckertreiber."
            )
        with tempfile.TemporaryDirectory(prefix="terminzettel-") as td:
            pdf = os.path.join(td, "input.pdf")
            run_checked([gxps, path, pdf])
            return run_checked(["pdftotext", "-layout", pdf, "-"]).decode("utf-8", "replace")

    encoding = str(input_cfg.get("text_encoding", "utf-8"))
    data = Path(path).read_bytes()
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return data.decode("latin-1", "replace")


def parse_t2med(text: str) -> ParsedTicket:
    text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    pages = text.split("\f")
    appointments: list[Appointment] = []
    patient = ""

    for page in pages:
        lines = page.splitlines()
        header_idx = None
        for i, line in enumerate(lines):
            if "Terminzeitpunkt" in line and "Termintyp" in line:
                header_idx = i
                break
        if header_idx is None:
            continue

        if not patient:
            candidates: list[str] = []
            for line in lines[:header_idx]:
                s = line.strip()
                if not s:
                    continue
                if s.upper().startswith("TERMINE"):
                    continue
                candidates.append(s)
            if candidates:
                patient = candidates[-1]

        current: Appointment | None = None
        blank_run = 0
        found_on_page = False
        for line in lines[header_idx + 1:]:
            if not line.strip():
                blank_run += 1
                if found_on_page and blank_run >= 2:
                    break
                continue
            blank_run = 0

            m = APPOINTMENT_RE.match(line)
            if m:
                current = Appointment(
                    weekday=WEEKDAYS[m.group("weekday")],
                    date=m.group("date"),
                    time=m.group("time"),
                    kind=re.sub(r"\s+", " ", m.group("type").strip()),
                )
                appointments.append(current)
                found_on_page = True
                continue

            # Wrapped appointment type: only while still inside the appointment table.
            if current is not None and found_on_page:
                s = line.strip()
                if s and not re.fullmatch(r"[\d\s./+()_-]+", s):
                    current.kind = f"{current.kind} {re.sub(r'\s+', ' ', s)}".strip()

    if not appointments:
        raise ValueError("Keine T2med-Termine unter 'Terminzeitpunkt / Termintyp' gefunden.")
    if not patient:
        patient = "Patient/in"

    # De-duplicate exact rows, then sort chronologically.
    seen: set[tuple[str, str, str]] = set()
    unique: list[Appointment] = []
    for appt in appointments:
        key = (appt.date, appt.time, appt.kind)
        if key not in seen:
            seen.add(key)
            unique.append(appt)
    unique.sort(key=lambda a: a.dt)

    return ParsedTicket(patient=patient, appointments=unique)


def cfg_bool(section: dict[str, Any], key: str, default: bool) -> bool:
    val = section.get(key, default)
    return bool(val)


def align_text(line: str, width: int, align: str) -> str:
    line = line.rstrip()
    if len(line) >= width:
        return line
    if align == "center":
        return line.center(width)
    if align == "right":
        return line.rjust(width)
    return line


class EscPosRenderer:
    ESC = b"\x1b"
    GS = b"\x1d"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        esc = cfg.get("escpos", {})
        layout = cfg.get("layout", {})
        self.encoding = str(esc.get("encoding", "cp858"))
        self.codepage = int(esc.get("codepage", 19))
        self.columns = int(layout.get("columns", 35))
        self.buf = bytearray()
        self._align = "left"
        self._bold = False
        self._double_height = False

    def raw(self, data: bytes) -> None:
        self.buf.extend(data)

    def init(self) -> None:
        esc = self.cfg.get("escpos", {})
        if cfg_bool(esc, "initialize", True):
            self.raw(self.ESC + b"@")
        self.raw(self.ESC + b"t" + bytes([self.codepage & 0xFF]))
        font = str(esc.get("font", "A")).upper()
        self.raw(self.ESC + b"M" + (b"\x01" if font == "B" else b"\x00"))

    def set_align(self, align: str) -> None:
        align = align.lower()
        n = {"left": 0, "center": 1, "right": 2}.get(align, 0)
        if align != self._align:
            self.raw(self.ESC + b"a" + bytes([n]))
            self._align = align

    def set_bold(self, enabled: bool) -> None:
        if enabled != self._bold:
            self.raw(self.ESC + b"E" + (b"\x01" if enabled else b"\x00"))
            self._bold = enabled

    def set_double_height(self, enabled: bool) -> None:
        if enabled != self._double_height:
            self.raw(self.GS + b"!" + (b"\x01" if enabled else b"\x00"))
            self._double_height = enabled

    def reset_style(self) -> None:
        self.set_double_height(False)
        self.set_bold(False)
        self.set_align("left")

    def encode(self, text: str) -> bytes:
        replacement = str(self.cfg.get("escpos", {}).get("unencodable", "?"))[:1] or "?"
        try:
            return text.encode(self.encoding)
        except UnicodeEncodeError:
            safe = text.encode(self.encoding, "replace").decode(self.encoding, "replace")
            if replacement != "?":
                safe = safe.replace("?", replacement)
            return safe.encode(self.encoding, "replace")

    def line(self, text: str = "", *, align: str | None = None,
             bold: bool | None = None, double_height: bool | None = None) -> None:
        if align is not None:
            self.set_align(align)
        if bold is not None:
            self.set_bold(bold)
        if double_height is not None:
            self.set_double_height(double_height)
        self.raw(self.encode(text) + b"\n")

    def wrapped(self, text: str, *, align: str = "left", bold: bool = False,
                initial_indent: str = "", subsequent_indent: str = "") -> None:
        width = max(8, self.columns - len(initial_indent))
        chunks = textwrap.wrap(text.strip(), width=width, break_long_words=False,
                               break_on_hyphens=False) or [""]
        for i, chunk in enumerate(chunks):
            indent = initial_indent if i == 0 else subsequent_indent
            line = indent + chunk
            if align == "center":
                line = align_text(line, self.columns, "center")
            elif align == "right":
                line = align_text(line, self.columns, "right")
            self.line(line.rstrip(), align=align, bold=bold)

    def block(self, section_name: str) -> None:
        sec = self.cfg.get(section_name, {})
        if not cfg_bool(sec, "enabled", True):
            return
        text = str(sec.get("text", "")).strip("\n")
        if not text:
            return
        align = str(sec.get("align", "center"))
        bold = cfg_bool(sec, "bold", False)
        for logical in text.splitlines():
            if not logical.strip():
                self.line("", align=align, bold=bold)
                continue
            for wrapped in textwrap.wrap(logical.strip(), width=self.columns,
                                         break_long_words=False, break_on_hyphens=False) or [""]:
                self.line(wrapped, align=align, bold=bold)

    def finish(self) -> bytes:
        esc = self.cfg.get("escpos", {})
        self.reset_style()
        feed_lines = int(esc.get("feed_lines", 4))
        if feed_lines > 0:
            self.raw(b"\n" * feed_lines)
        cut = str(esc.get("cut", "partial")).lower()
        if cut == "partial":
            self.raw(self.GS + b"V\x01")
        elif cut == "full":
            self.raw(self.GS + b"V\x00")
        elif cut in ("none", "off", "false", ""):
            pass
        else:
            raise ValueError("escpos.cut muss 'partial', 'full' oder 'none' sein")
        return bytes(self.buf)


def render_escpos(ticket: ParsedTicket, cfg: dict[str, Any]) -> bytes:
    r = EscPosRenderer(cfg)
    layout = cfg.get("layout", {})
    r.init()

    r.block("header")
    if str(cfg.get("header", {}).get("text", "")).strip():
        r.line("")

    heading = str(layout.get("heading", "IHRE TERMINE"))
    if heading:
        r.line(heading, align="center", bold=True,
               double_height=cfg_bool(layout, "heading_double_height", True))
        r.set_double_height(False)
        r.line("")

    if cfg_bool(layout, "show_patient", True):
        r.wrapped(ticket.patient, align="left", bold=True)
        r.line("")

    groups: OrderedDict[str, list[Appointment]] = OrderedDict()
    for appt in ticket.appointments:
        groups.setdefault(appt.date, []).append(appt)

    for group_idx, (date, appts) in enumerate(groups.items()):
        first = appts[0]
        date_line = f"{first.weekday} {date}"
        r.line(date_line, align="left", bold=True)

        for appt in appts:
            prefix = f"{appt.time}  "
            available = max(8, r.columns - len(prefix))
            chunks = textwrap.wrap(appt.kind, width=available, break_long_words=False,
                                   break_on_hyphens=False) or [""]
            r.line(prefix + chunks[0], align="left", bold=False)
            for chunk in chunks[1:]:
                r.line(" " * len(prefix) + chunk, align="left", bold=False)

        if group_idx < len(groups) - 1:
            r.line("")

    footer_text = str(cfg.get("footer", {}).get("text", "")).strip()
    if footer_text:
        r.line("")
        if cfg_bool(layout, "footer_separator", True):
            separator = str(layout.get("separator_char", "-"))[:1] or "-"
            r.line(separator * r.columns, align="left", bold=False)
        r.block("footer")

    return r.finish()


def render_text(ticket: ParsedTicket, cfg: dict[str, Any]) -> bytes:
    layout = cfg.get("layout", {})
    output = cfg.get("output", {})
    columns = int(layout.get("columns", 35))
    lines: list[str] = []

    header = str(cfg.get("header", {}).get("text", "")).strip("\n")
    if header:
        lines.extend(header.splitlines())
        lines.append("")
    heading = str(layout.get("heading", "IHRE TERMINE"))
    if heading:
        lines.append(heading)
        lines.append("")
    if cfg_bool(layout, "show_patient", True):
        lines.extend(textwrap.wrap(ticket.patient, columns) or [ticket.patient])
        lines.append("")

    groups: OrderedDict[str, list[Appointment]] = OrderedDict()
    for appt in ticket.appointments:
        groups.setdefault(appt.date, []).append(appt)
    for idx, (date, appts) in enumerate(groups.items()):
        lines.append(f"{appts[0].weekday} {date}")
        for appt in appts:
            prefix = f"{appt.time}  "
            chunks = textwrap.wrap(appt.kind, max(8, columns - len(prefix)),
                                   break_long_words=False, break_on_hyphens=False) or [""]
            lines.append(prefix + chunks[0])
            lines.extend(" " * len(prefix) + c for c in chunks[1:])
        if idx < len(groups) - 1:
            lines.append("")

    footer = str(cfg.get("footer", {}).get("text", "")).strip("\n")
    if footer:
        lines.append("")
        lines.extend(footer.splitlines())
    lines.append("")
    return "\n".join(lines).encode(str(output.get("text_encoding", "utf-8")), "replace")


def render(ticket: ParsedTicket, cfg: dict[str, Any]) -> bytes:
    fmt = str(cfg.get("output", {}).get("format", "escpos")).lower()
    if fmt == "escpos":
        return render_escpos(ticket, cfg)
    if fmt in ("text", "plain", "plaintext"):
        return render_text(ticket, cfg)
    raise ValueError(f"Unbekanntes output.format: {fmt}")


def send_smb(payload: bytes, cfg: dict[str, Any]) -> None:
    output = cfg.get("output", {})
    transport = str(output.get("transport", "smb")).lower()
    if transport != "smb":
        raise ValueError("Derzeit ist output.transport='smb' implementiert.")

    server = str(output.get("server", "localhost"))
    share = str(output.get("share", "TMm10"))
    username = str(output.get("username", ""))
    password = str(output.get("password", ""))
    domain = str(output.get("domain", ""))

    with tempfile.TemporaryDirectory(prefix="terminzettel-out-") as td:
        raw_path = os.path.join(td, "terminzettel.raw")
        Path(raw_path).write_bytes(payload)

        cmd = ["smbclient", f"//{server}/{share}"]
        auth_path = None
        if username:
            auth_path = os.path.join(td, "auth")
            with open(auth_path, "w", encoding="utf-8") as fh:
                fh.write(f"username = {username}\n")
                fh.write(f"password = {password}\n")
                if domain:
                    fh.write(f"domain = {domain}\n")
            os.chmod(auth_path, 0o600)
            cmd += ["-A", auth_path]
        else:
            cmd += ["-N"]

        cmd += ["-c", f"print {raw_path}"]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if proc.returncode != 0:
            out = proc.stdout.decode("utf-8", "replace").strip()
            err = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(
                f"SMB-Druck nach //{server}/{share} fehlgeschlagen ({proc.returncode}).\n{out}\n{err}"
            )
        log(f"RAW-Druckjob an //{server}/{share} übergeben ({len(payload)} Bytes)")


def maybe_save_debug(source_path: str, payload: bytes, cfg: dict[str, Any]) -> None:
    debug = cfg.get("debug", {})
    raw_dir = str(debug.get("save_raw_dir", "")).strip()
    input_dir = str(debug.get("save_input_dir", "")).strip()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if raw_dir:
        Path(raw_dir).mkdir(parents=True, exist_ok=True)
        Path(raw_dir, f"{stamp}.raw").write_bytes(payload)
    if input_dir:
        Path(input_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, Path(input_dir, f"{stamp}-{Path(source_path).name}"))


def main() -> int:
    parser = argparse.ArgumentParser(description="T2med-Terminbeleg -> 58-mm RAW/ESC-POS -> SMB")
    parser.add_argument("input", help="Spooldatei (PDF, PostScript, XPS oder Text)")
    parser.add_argument("--config", default=os.environ.get("TERMINZETTEL_CONFIG", DEFAULT_CONFIG))
    parser.add_argument("--extract", action="store_true", help="Nur erkannte Daten als JSON ausgeben")
    parser.add_argument("--render", metavar="DATEI", help="Nur rendern, RAW-Ausgabe in DATEI schreiben")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
        text = extract_text(args.input, cfg)
        ticket = parse_t2med(text)
        log(f"erkannt: {ticket.patient}; {len(ticket.appointments)} Termin(e)")

        if args.extract:
            print(json.dumps({
                "patient": ticket.patient,
                "appointments": [
                    {"weekday": a.weekday, "date": a.date, "time": a.time, "type": a.kind}
                    for a in ticket.appointments
                ],
            }, ensure_ascii=False, indent=2))
            return 0

        payload = render(ticket, cfg)
        maybe_save_debug(args.input, payload, cfg)

        if args.render:
            Path(args.render).write_bytes(payload)
            print(args.render)
            return 0

        send_smb(payload, cfg)
        return 0
    except Exception as exc:
        log(f"FEHLER: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
__TERMINZETTEL_PY__
chmod 0755 "$APP_PY"

cat > "$WRAPPER" <<'__TERMINZETTEL_WRAPPER__'
#!/bin/sh
exec /usr/bin/python3 /usr/local/lib/terminzettel/terminzettel.py "$@"
__TERMINZETTEL_WRAPPER__
chmod 0755 "$WRAPPER"

if [[ ! -f "$CONFIG_FILE" ]]; then
  cat > "$CONFIG_FILE" <<'__TERMINZETTEL_CONFIG__'
# /etc/terminzettel/config.toml
# T2med-Terminbeleg -> 58-mm-Terminbon -> SMB RAW-Drucker

[input]
# Wird nur für bereits als Text angelieferte Jobs benötigt.
text_encoding = "utf-8"

[output]
transport = "smb"
server = "localhost"
share = "TMm10"

# escpos = Epson/ESC-POS inklusive Steuerzeichen und Schnitt
# text   = reiner Text ohne ESC/POS-Steuerzeichen
format = "escpos"

# Leer = Gastzugriff / -N. Falls Authentifizierung nötig ist, hier eintragen.
username = ""
password = ""
domain = ""

# Nur bei output.format = "text"
text_encoding = "utf-8"

[escpos]
# Epson PC858: Umlaute + Euro. ESC t 19 wird vor dem Text gesendet.
encoding = "cp858"
codepage = 19
font = "A"
initialize = true

# Papier nach dem Inhalt noch etwas vorschieben.
feed_lines = 4

# partial | full | none
cut = "partial"

# Ersatzzeichen für Zeichen, die in der gewählten Codepage fehlen.
unencodable = "?"

[layout]
# TM-m10, 58 mm, Font A: sinnvoller Ausgangswert.
columns = 35
heading = "IHRE TERMINE"
heading_double_height = true
show_patient = true
footer_separator = true
separator_char = "-"

[header]
enabled = true
align = "center"
bold = true
text = """
"""

[footer]
enabled = true
align = "center"
bold = false
text = """
"""

[debug]
# Aus Datenschutzgründen standardmäßig leer: nichts dauerhaft speichern.
save_raw_dir = ""
save_input_dir = ""
__TERMINZETTEL_CONFIG__
  chown root:"$APP_GROUP" "$CONFIG_FILE"
  chmod 0640 "$CONFIG_FILE"
else
  echo "    Vorhandene $CONFIG_FILE bleibt unverändert."
fi

cat > "$DOC_DIR/README.md" <<'__TERMINZETTEL_README__'
# T2med-Terminbeleg auf 58-mm-Bondrucker

Der Dienst stellt über Samba einen virtuellen Drucker **`Terminzettel`** bereit. Ein T2med-Druckjob wird als PDF/PostScript/XPS/Text angenommen, der Patient und alle Termine werden extrahiert, Termine chronologisch sortiert und nach Datum gruppiert. Anschließend wird ein 58-mm-Beleg erzeugt und als RAW-Druckjob über SMB an den in TOML konfigurierten Ziel-Drucker geschickt.

Standardziel: `//localhost/TMm10`, Ausgabeformat: Epson ESC/POS, PC858, Teilschnitt.

## Installation

```bash
chmod +x install-terminzettel.sh
sudo ./install-terminzettel.sh
```

Die vorhandene `/etc/samba/smb.conf` wird vor einer Änderung gesichert. Eine bestehende, fremd konfigurierte `[Terminzettel]`-Freigabe wird nicht überschrieben.

## Konfiguration

```bash
sudo nano /etc/terminzettel/config.toml
```

Kopf und Fuß sind frei konfigurierbar. Beispiel:

```toml
[header]
enabled = true
align = "center"
bold = true
text = """
Praxis Dr. Beispiel
Allgemeinmedizin
"""

[footer]
enabled = true
align = "center"
bold = false
text = """
Bitte bringen Sie Ihre
Gesundheitskarte mit.
"""
```

Das Ziel bleibt vollständig vom Parser getrennt:

```toml
[output]
transport = "smb"
server = "localhost"
share = "TMm10"
format = "escpos"
```

Für einen anderen RAW-SMB-Drucker werden nur `server`, `share` und ggf. die Ausgabeparameter geändert.

## ESC/POS / Schnitt

```toml
[escpos]
encoding = "cp858"
codepage = 19
font = "A"
feed_lines = 4
cut = "partial"   # partial | full | none
```

Der Renderer sendet bei PC858 `ESC t 19`. Der Schnitt wird genau einmal am Jobende erzeugt; es wird kein zweiter Cut über CUPS o.ä. ausgelöst.

## Test ohne Drucken

Parser prüfen:

```bash
terminzettel-submit --extract /pfad/zum/t2med-termin.pdf
```

ESC/POS-Datei erzeugen, aber nicht senden:

```bash
terminzettel-submit --render /tmp/terminzettel.raw /pfad/zum/t2med-termin.pdf
xxd /tmp/terminzettel.raw | head
```

Echten Testdruck auslösen:

```bash
terminzettel-submit /pfad/zum/t2med-termin.pdf
```

## Samba-Eingang

Der Installer ergänzt folgenden Drucker zwischen markierten Kommentarzeilen in `/etc/samba/smb.conf`:

```ini
[Terminzettel]
    comment = T2med Terminbeleg 58mm
    path = /var/spool/samba/terminzettel
    printable = yes
    browseable = yes
    guest ok = yes
    read only = yes
    use client driver = yes
    printing = bsd
    print command = /usr/local/sbin/terminzettel-submit %s
    lpq command =
    lprm command =
```

Samba übergibt die Spooldatei synchron an den Filter. Der Filter verändert die vorhandene `TMm10`-Freigabe nicht.

## Unterstützte Eingangsformate

- PDF: direkt mit `pdftotext -layout`
- PostScript: Ghostscript -> PDF -> `pdftotext`
- XPS: `gxps2pdf` -> PDF -> `pdftotext`
- Text: direkt

Wenn ein Windows-Client PCL/anderen Binärdatenstrom liefert, sollte dort ein PostScript- oder PDF-fähiger Treiber für den virtuellen Drucker verwendet werden. Der Filter bricht bei nicht erkennbaren T2med-Terminen ab, statt unverständliche Daten an den Bondrucker zu schicken.

## Deinstallation

```bash
sudo ./install-terminzettel.sh --uninstall
```

Die Deinstallation entfernt Programm, Konfiguration und den vom Installer markierten Samba-Block. Paketabhängigkeiten werden bewusst nicht automatisch entfernt.
__TERMINZETTEL_README__
chmod 0644 "$DOC_DIR/README.md"

echo "==> Konfiguriere Samba-Eingangsdrucker [Terminzettel]"
if [[ ! -f "$SMB_CONF" ]]; then
  echo "$SMB_CONF fehlt trotz installiertem Samba." >&2
  exit 1
fi
BACKUP="$SMB_CONF.terminzettel-$(date +%Y%m%d-%H%M%S).bak"
cp -a "$SMB_CONF" "$BACKUP"

# Eigene frühere Konfiguration entfernen; fremde gleichnamige Freigabe nicht überschreiben.
remove_managed_block "$SMB_CONF"
if grep -Eq '^[[:space:]]*\[Terminzettel\][[:space:]]*$' "$SMB_CONF"; then
  cp -a "$BACKUP" "$SMB_CONF"
  echo "Es existiert bereits eine nicht von diesem Installer verwaltete [Terminzettel]-Freigabe." >&2
  echo "Keine Samba-Änderung vorgenommen." >&2
  exit 1
fi

cat >> "$SMB_CONF" <<'__TERMINZETTEL_SAMBA__'

# BEGIN TERMINZETTEL MANAGED
[Terminzettel]
    comment = T2med Terminbeleg 58mm
    path = /var/spool/samba/terminzettel
    printable = yes
    browseable = yes
    guest ok = yes
    read only = yes
    use client driver = yes
    force user = terminzettel
    force group = terminzettel
    printing = bsd
    print command = /usr/local/sbin/terminzettel-submit "%s"
    lpq command =
    lprm command =
# END TERMINZETTEL MANAGED
__TERMINZETTEL_SAMBA__

if ! testparm -s "$SMB_CONF" >/dev/null; then
  echo "Samba-Konfiguration ungültig; stelle Backup wieder her." >&2
  cp -a "$BACKUP" "$SMB_CONF"
  exit 1
fi

reload_samba

echo
echo "Installation abgeschlossen."
echo "  Eingangs-Drucker : [Terminzettel]"
echo "  Ziel standardmäßig: //localhost/TMm10"
echo "  Konfiguration    : $CONFIG_FILE"
echo "  Samba-Backup     : $BACKUP"
echo
echo "Parser testen:"
echo "  terminzettel-submit --extract /pfad/termin.pdf"
echo "RAW erzeugen, ohne zu drucken:"
echo "  terminzettel-submit --render /tmp/termin.raw /pfad/termin.pdf"
echo "Echten Druck testen:"
echo "  terminzettel-submit /pfad/termin.pdf"
echo
echo "Hinweis: Der Installer verändert die vorhandene TMm10-Freigabe nicht."
