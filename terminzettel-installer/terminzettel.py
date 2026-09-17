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
