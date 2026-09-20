"""Offline-Kalender und QR: Terminzeiten und Titel, ohne Patientenname."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo


class PayloadTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class CalendarAppointment:
    start: datetime
    end: datetime | None = None


def appointment_summary(prefix: str, kind: str) -> str:
    """Fester Praxis-Präfix plus Terminart; ein leerer Präfix ist zulässig."""
    if not isinstance(prefix, str) or not isinstance(kind, str):
        raise ValueError("invalid calendar configuration")
    prefix = prefix.strip().rstrip(":").rstrip()
    kind = " ".join(kind.split())
    return f"{prefix}: {kind}" if prefix and kind else prefix or kind


def utc_time(value: datetime, zone: ZoneInfo) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("invalid appointment datetime")
    if value.tzinfo is not None:
        utc = value.astimezone(timezone.utc)
        if utc.astimezone(value.tzinfo).replace(tzinfo=None) != value.replace(tzinfo=None):
            raise ValueError("invalid appointment datetime")
        return utc
    # Bei der Zeitumstellung weder nicht existierende noch mehrdeutige Zeiten raten.
    possible = set()
    for fold in (0, 1):
        aware = value.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == value:
            possible.add(utc)
    if len(possible) != 1:
        raise ValueError("invalid appointment datetime")
    return possible.pop()


def escape_text(value: str) -> str:
    if not isinstance(value, str) or any(ord(c) < 32 and c not in "\r\n\t" for c in value):
        raise ValueError("invalid calendar configuration")
    return value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold_line(value: str) -> bytes:
    """RFC 5545: höchstens 75 Oktette je Zeile; UTF-8-Zeichen bleiben vollständig."""
    lines, current = [], bytearray()
    for char in value:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > 75:
            lines.append(bytes(current))
            current = bytearray(b" ")
        current.extend(encoded)
    lines.append(bytes(current))
    return b"\r\n".join(lines) + b"\r\n"


def build_icalendar(appointments: list[CalendarAppointment], config: dict,
                   *, now: datetime | None = None) -> bytes:
    zone = ZoneInfo(config.get("timezone", "Europe/Berlin"))
    duration = config.get("default_duration_minutes", 15)
    if type(duration) is not int or not 1 <= duration <= 1440:
        raise ValueError("invalid calendar configuration")
    summary = escape_text(config.get("summary", "Termin Arztpraxis"))
    if not summary.strip():
        raise ValueError("invalid calendar configuration")
    include_location = config.get("include_location", False)
    if type(include_location) is not bool:
        raise ValueError("invalid calendar configuration")
    location = escape_text(config.get("location", "")) if include_location else ""
    periods = set()
    for appointment in appointments:
        try:
            start = utc_time(appointment.start, zone)
            end = utc_time(appointment.end, zone) if appointment.end is not None else start + timedelta(minutes=duration)
            if end <= start:
                raise ValueError("invalid appointment datetime")
            periods.add((start, end))
        except (AttributeError, TypeError, ValueError, OverflowError):
            print("invalid appointment datetime", file=sys.stderr)
    if not periods:
        raise ValueError("invalid appointment datetime")
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise ValueError("invalid calendar timestamp")

    def date(value):
        return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Praxis//Terminbon//DE", "CALSCALE:GREGORIAN"]
    for start, end in sorted(periods):
        # Großbuchstaben erlauben dem QR-Encoder den kompakteren Alphanumerikmodus.
        lines.extend(["BEGIN:VEVENT", "UID:" + str(uuid4()).upper(), "DTSTAMP:" + date(stamp),
                      "DTSTART:" + date(start), "DTEND:" + date(end), "SUMMARY:" + summary])
        if location:
            lines.append("LOCATION:" + location)
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return b"".join(fold_line(line) for line in lines)


def build_qr_image(payload: bytes, config: dict):
    import qrcode
    from qrcode.exceptions import DataOverflowError

    levels = {"L": qrcode.constants.ERROR_CORRECT_L, "M": qrcode.constants.ERROR_CORRECT_M,
              "Q": qrcode.constants.ERROR_CORRECT_Q, "H": qrcode.constants.ERROR_CORRECT_H}
    level = config.get("error_correction", "M")
    quiet = config.get("quiet_zone_modules", 4)
    width = config.get("max_width_dots", 256)
    minimum = config.get("min_module_dots", 3)
    if level not in levels or any(type(v) is not int for v in (quiet, width, minimum)):
        raise ValueError("invalid QR configuration")
    if not 4 <= quiet <= 16 or not 64 <= width <= 384 or not 3 <= minimum <= 10:
        raise ValueError("invalid QR configuration")
    qr = qrcode.QRCode(version=1, error_correction=levels[level], border=quiet, box_size=1)
    qr.add_data(payload)
    try:
        qr.make(fit=True)
    except (DataOverflowError, ValueError):
        # qrcode 8.2 meldet einen Überlauf teils als unzulässige Version 41.
        raise PayloadTooLarge("calendar QR payload too large") from None
    module_dots = width // (qr.modules_count + 2 * quiet)
    if module_dots < minimum:
        raise PayloadTooLarge("calendar QR payload too large")
    qr.box_size = module_dots
    return qr.make_image(fill_color="black", back_color="white").convert("1")
