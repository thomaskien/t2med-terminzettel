#!/usr/bin/env python3
"""CUPS-Eingang für Bonjour/IPP; verwendet dieselbe Verarbeitung wie Samba."""
from contextlib import nullcontext
import os
import pwd
import signal
import sys

import terminzettel as app


def drop_privileges():
    account = pwd.getpwnam("terminzettel")
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    if os.geteuid() != account.pw_uid:
        raise ValueError("invalid backend user")
    os.umask(0o077)


def cancel_job(signum, frame):
    raise KeyboardInterrupt


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if not args:
        print('direct terminzettel:/ "T2med Terminzettel" "Terminzettel"')
        return 0
    failure = "CUPS-Eingabe oder Benutzerrechte konnten nicht übernommen werden."
    try:
        if len(args) not in (5, 6):
            raise ValueError("invalid backend arguments")
        copies = int(args[3])
        if not 1 <= copies <= 99:
            raise ValueError("invalid copies")
        signal.signal(signal.SIGTERM, cancel_job)
        # Nur zum Öffnen der CUPS-Spooldatei werden Root-Rechte benötigt.
        # Inhalt erst nach dem Rechtewechsel lesen und verarbeiten.
        source = open(args[5], "rb") if len(args) == 6 else nullcontext(sys.stdin.buffer)
        with source as stream:
            drop_privileges()
            failure = "RAM-Verzeichnis oder Druckeingabe konnte nicht gelesen werden."
            app.ensure_runtime()
            data = stream.read(app.MAX_INPUT + 1)
        failure = "Konfiguration konnte nicht geladen werden. Bitte config.toml prüfen."
        cfg = app.load_config(app.DEFAULT_CONFIG)
        failure = "Beleg konnte nicht umgewandelt oder als Terminbon aufbereitet werden."
        payload = app.make_payload(data, cfg)
        failure = "CUPS-Ausgabe fehlgeschlagen. Bitte die Zielwarteschlange prüfen."
        app.send_cups(payload, cfg, copies=copies)
        return 0
    except app.TicketError as exc:
        # TicketError enthält ausschließlich feste, vom Programm vorgegebene Texte.
        print("ERROR: Terminzettel: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ERROR: Terminzettel: Druckauftrag wurde abgebrochen.", file=sys.stderr)
        return 1
    except Exception:
        # Fremde Fehlertexte, CUPS-Argumente und Tracebacks können Patientendaten enthalten.
        print("ERROR: Terminzettel: " + failure, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
