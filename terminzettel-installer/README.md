# T2med-Terminzettel

In T2med **Terminzettel** als Drucker auswählen. Der Dienst druckt einen 58-mm-Bon über die vorhandene lokale CUPS-Warteschlange **TMm10**. Auf Wunsch ergänzt er einen Offline-Kalender-QR für alle Termine.

## Installation auf dem Raspberry Pi

Voraussetzung: Raspberry Pi OS mit Python ab 3.10, Linux-Kernel ab 6.4, systemd und cgroup v2 mit Speichercontroller. Die lokale CUPS-Warteschlange `TMm10` muss bereits funktionieren. Bei älteren Systemen meldet der Installer, was fehlt.

Das gesamte Projektverzeichnis wird benötigt. Darin ausführen:

```bash
sudo ./install-terminzettel.sh
```

In T2med einen PDF- oder PostScript-fähigen Treiber für die Freigabe `Terminzettel` verwenden. Pro Druckauftrag wird genau **eine Seite für einen Patienten** erwartet. Die lesbare Terminliste bleibt immer auf dem Bon.

Der Installer sichert die Konfiguration, schützt fremde gleichnamige Freigaben und nimmt seine Dateiänderungen zurück, wenn die Umstellung scheitert. Vor der Installation müssen laufende Druckaufträge abgeschlossen sein.

**Die RAM-Umstellung betrifft den lokalen CUPS-Dienst und den Samba-Druckcache insgesamt.** Druckwarteschlangen, Druckhistorie und vorübergehende Druckdaten gehen bei einem Neustart verloren. CUPS-Dateilogs und das normale Samba-Dateilog werden deaktiviert. Vorhandene Drucker bleiben konfiguriert. Ein eigenständiger Samba-Server wird vorausgesetzt; Domänenserver werden abgelehnt.

## Konfiguration

```bash
sudo nano /etc/terminzettel/config.toml
```

Änderungen gelten ab dem nächsten Auftrag. Kopf und Fuß lassen sich dort frei einstellen. Standardziel:

```toml
[output]
queue = "TMm10"
format = "escpos"
```

### Kalender-QR

```toml
[calendar_qr]
enabled = true
summary = "Termin Arztpraxis"
timezone = "Europe/Berlin"
default_duration_minutes = 15

include_location = false
location = ""

caption = "Alle Termine in Kalender übernehmen"
error_correction = "M"
quiet_zone_modules = 4
max_width_dots = 360
min_module_dots = 3
```

Für die Praxisadresse beispielsweise `include_location = true` und `location = "Praxis Beispiel, Musterstraße 1, 12345 Musterstadt"` setzen. Titel und Adresse sind feste Praxisangaben; dort keine Patienteninformationen eintragen. Es gibt keine Platzhalter für Name, Behandlungsgrund oder Termintyp.

Der eine QR enthält einen vollständigen Kalender mit einem Eintrag pro Termin. Beginn und Ende werden mit der eingestellten Zeitzone nach UTC umgerechnet. Die Standarddauer beträgt 15 Minuten. Der Kalendergenerator unterstützt zusätzlich eine ausdrücklich angegebene Endzeit; der gegenwärtige T2med-Parser liefert nur Anfangszeiten. Mehrdeutige oder nicht existierende Zeiten bei der Zeitumstellung werden vom Kalendergenerator nicht geraten.

Der QR benötigt weder URL noch Internet oder Kalenderdienst. Patientenname und Termintyp werden nicht an das Kalendermodul übergeben. Der QR wird im RAM erzeugt und als Schwarzweiß-Raster gedruckt. Die Adresse erscheint nur bei aktivierter Option im Kalendereintrag. Jede Neuausgabe erhält neue zufällige IDs; erneutes Scannen desselben Bons liest dieselben IDs.

**Zu viele Termine oder lange Adressen können die lesbare QR-Größe überschreiten.** Dann wird der Bon ohne QR gedruckt. Ebenso bei einem QR-Fehler. Es erscheinen nur feste technische Fehlermeldungen, keine QR-Inhalte. Die Rasterbreite darf höchstens 384 Punkte betragen; mindestens drei Punkte pro Modul und vier freie Randmodule werden erzwungen. Im Ausgabeformat `text` gibt es keinen QR.

Im automatisierten Test passen ein bis drei Termine mit dem Standardtitel in 360 Punkte. Fünf Termine ohne Adresse benötigen 363 Punkte und passen erst mit `max_width_dots = 384`. Diese breitere Einstellung vorher am Drucker prüfen; eine Adresse vergrößert den QR zusätzlich.

Ein korrekt lesbarer Kalender-QR garantiert noch keinen Kalenderimport durch jede Smartphone-Kamera. Vor dem Praxiseinsatz auf dem TM-m10 mit iPhone und Android prüfen: Erkennung, Import aller Einträge, Uhrzeit und erneutes Scannen. Dieser Gerätetest ist noch offen.

## Patientendaten

Es gibt keine Archivierung, keine Debug-Kopien und keinen Export von Belegen oder QR-Payloads. Das Programm protokolliert keine Patientennamen, Termine oder fremden Fehlertexte.

Samba-Spooldateien werden beim Übernehmen entfernt. Konvertierungen und CUPS-Zwischendaten liegen auf einem begrenzten RAM-Dateisystem ohne Swap. Die Druckprozesse dürfen ebenfalls keinen Swap verwenden; ohne diesen Schutz wird der Auftrag abgelehnt. PDF wird direkt per Pipe verarbeitet. PostScript und XPS benötigen kurzzeitig Dateien im geschützten RAM-Verzeichnis.

CUPS bekommt nur den festen Auftragsnamen `Terminzettel`. Der Auftrag wird nach Beendigung entfernt, bei Fehlern oder nach 60 Sekunden abgebrochen. Ein Bereinigungsdienst entfernt verwaiste Aufträge und Dateien; bei einem Absturz können Daten bis zum nächsten Bereinigungslauf kurzzeitig im RAM verbleiben. Nach einem Neustart sind sie weg. Ein fehlgeschlagener Auftrag wird aus T2med neu gedruckt.

Die Überwachung bestätigt den CUPS-Auftrag, nicht den tatsächlichen Papierauswurf. Bei ausgeschalteter Druckhistorie kann ein bereits entfernter Auftrag nachträglich nicht mehr nach Erfolg oder Abbruch unterschieden werden.

Der Dienst kontrolliert den Raspberry Pi. Bereits vorhandene Altdateien sowie Aufbewahrung auf dem T2med-Client oder im Drucker werden dadurch nicht rückwirkend geändert. Suspend/Hibernation und zusätzliche systemweite Audit-/Backup-Konfigurationen müssen zur Vorgabe passen. Die Installationssicherung enthält ausschließlich Programm- und Konfigurationsdateien und ist nur für root zugänglich.

## Prüfen und entfernen

Selbsttest ohne echte Patientendaten oder Druck:

```bash
terminzettel-submit --self-test
```

Deinstallation aus demselben Projektverzeichnis:

```bash
sudo ./install-terminzettel.sh --uninstall
```

Nachträglich veränderte Dateien werden nicht überschrieben. Die Konfiguration wird vor dem Entfernen überprüft; bei Konflikten bricht die Deinstallation ab. Dienstbenutzer, Pakete und Installationssicherung bleiben erhalten.

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -B -m unittest discover -s tests -v
bash -n install-terminzettel.sh
```

Die Tests verwenden ausschließlich künstliche Namen und Termine. Der QR wird zusätzlich mit einem unabhängigen Decoder zurückgelesen und bytegenau verglichen. Produktionsabhängigkeiten werden durch den Installer als Debian-Pakete installiert; `zxing-cpp` und `icalendar` werden ausschließlich für Entwicklungstests benötigt.
