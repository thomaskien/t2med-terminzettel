# T2med-Terminzettel

In T2med **Terminzettel** als Drucker auswählen. Der Dienst druckt einen 58-mm-Bon über die vorhandene lokale CUPS-Warteschlange **TMm10**. Auf Wunsch ergänzt er einen Offline-Kalender-QR für alle Termine.

## Installation auf dem Raspberry Pi

Voraussetzung: Raspberry Pi OS mit Python ab 3.10, systemd und eine funktionierende lokale CUPS-Warteschlange `TMm10`. Bei älteren Systemen meldet der Installer, was fehlt.

### Download und Installation

[Projekt als Archiv herunterladen](https://github.com/thomaskien/t2med-terminzettel/archive/refs/heads/main.tar.gz). Das gesamte Archiv wird benötigt, nicht nur das Installationsskript.

Direkt auf dem Raspberry Pi herunterladen, entpacken und installieren:

```bash
cd ~
curl -fL https://github.com/thomaskien/t2med-terminzettel/archive/refs/heads/main.tar.gz -o terminzettel.tar.gz
tar -xzf terminzettel.tar.gz
cd t2med-terminzettel-main/terminzettel-installer
sudo ./install-terminzettel.sh
```

Falls `curl` fehlt: `sudo apt-get update && sudo apt-get install -y curl`. Die übrigen benötigten Pakete installiert das Skript selbst. Download und Paketinstallation benötigen Internet; der spätere Kalender-QR funktioniert offline. Wer bereits als `root` angemeldet ist, kann `sudo` weglassen.

Ist das Projekt bereits entpackt, im Unterordner `terminzettel-installer` einfach `sudo ./install-terminzettel.sh` ausführen.

### Vorhandene Installation aktualisieren

Bei einem Download als Archiv die Download- und Installationsbefehle oben erneut ausführen. Einstellungen gehören nach `/etc/terminzettel/config.toml`; diese übernimmt der Installer beim Update.

Falls das Projekt mit Git nach `~/terminzettel` heruntergeladen wurde:

```bash
cd ~/terminzettel
git pull --ff-only
cd terminzettel-installer
sudo ./install-terminzettel.sh
```

Auch nach dem früheren Abbruch mit „cgroup v2 und Speichercontroller erforderlich“ genügt der aktuelle Download und ein erneuter Installationslauf. Die cgroup-/Swap-Sperre wurde entfernt; dafür ist kein Systemupdate erforderlich.

### Drucker auf dem Mac hinzufügen

Der Installer richtet **Terminzettel** als freigegebene CUPS-Warteschlange ein. Damit wird er über die vorhandene Bonjour-Druckerfreigabe der kienzlebox angekündigt, genauso wie `TMm10` und die Faxdrucker.

1. **Systemeinstellungen → Drucker & Scanner → Drucker hinzufügen** öffnen.
2. Unter **Default / Standard** den Eintrag **Terminzettel @ kienzlebox** auswählen (der angezeigte Rechnername kann abweichen).
3. Die angebotene **T2med Terminzettel**-Software verwenden. Falls sie nicht automatisch gewählt wird, **Generic PostScript Printer** auswählen und hinzufügen.
4. In T2med diesen Drucker **Terminzettel** für das Terminblatt auswählen.

`Terminzettel` erzeugt den Bon einschließlich Kalender-QR und druckt ihn anschließend über die vorhandene Warteschlange `TMm10`. Als Eingangsformat bleibt die normale Seite des Terminblatts eingestellt, zum Beispiel A4. Das Bonformat entsteht erst auf dem Raspberry Pi.

**Falls der Eintrag nicht automatisch erscheint:** Im Dialog **IP** wählen, Adresse `kienzlebox.local` (alternativ die IP-Adresse), Protokoll **Internet Printing Protocol – IPP**, Warteliste **printers/Terminzettel**, Name **Terminzettel**, Verwenden **Generic PostScript Printer**. Der vollständige Anschluss lautet `ipp://kienzlebox.local:631/printers/Terminzettel`.

Voraussetzung ist die bereits eingerichtete CUPS-Netzwerkfreigabe auf dem Raspberry Pi. Sind andere CUPS-Drucker wie `TMm10` bereits als Bonjour-Drucker sichtbar, ist sie vorhanden. Der Installer ergänzt die neue Warteschlange und installiert Avahi für Bonjour. Er verändert weder die Netzwerkzugriffsregeln noch die Anschlussadressen der bestehenden Drucker. Hintergrund: [CUPS-Druckerfreigabe und Bonjour](https://www.cups.org/doc/sharing.html).

Ältere Versionen dieses Projekts hatten nur eine Samba-Freigabe. Für Bonjour das Projekt aktualisieren und den Installer erneut ausführen. Nur den Samba-Cache mit `chmod` zu korrigieren legt noch keinen Bonjour-Drucker an.

### Samba-Warnung zum Cacheverzeichnis beheben

Meldet `testparm` bei einer älteren Installation „cache directory ... should have permissions 0755 for browsing to work“, auf der kienzlebox ausführen:

```bash
sudo chmod 0755 /run/terminzettel/samba-cache
```

Danach den Druckerdialog auf dem Mac neu öffnen. Der aktuelle Installer setzt die Rechte auch beim Systemstart korrekt. Für die dauerhafte Korrektur das Projekt wie oben beschrieben aktualisieren und den Installer erneut ausführen; der einzelne `chmod`-Befehl wirkt bei der alten Version nur bis zum nächsten Neustart. Das private Spoolverzeichnis behält seine bisherigen Rechte.

### Drucker unter Windows hinzufügen

Nach der Installation unter Windows die Druckerfreigabe `\\kienzlebox\Terminzettel` verbinden und in T2med als Drucker auswählen. Falls der Raspberry Pi anders heißt, `kienzlebox` entsprechend ersetzen. `TMm10` bleibt die bereits vorhandene lokale CUPS-Ausgabewarteschlange auf dem Raspberry Pi.

In T2med einen PDF- oder PostScript-fähigen Treiber für die Freigabe `Terminzettel` verwenden. Pro Druckauftrag wird genau **eine Seite für einen Patienten** erwartet. Die lesbare Terminliste bleibt immer auf dem Bon.

Der Installer sichert die Konfiguration, schützt fremde gleichnamige Freigaben und nimmt seine Dateiänderungen zurück, wenn die Umstellung scheitert. Vor der Installation müssen laufende Druckaufträge abgeschlossen sein.

**Die RAM-Umstellung betrifft den lokalen CUPS-Dienst und den Samba-Druckcache insgesamt.** Druckwarteschlangen, Druckhistorie und vorübergehende Druckdaten gehen bei einem Neustart verloren. CUPS-Dateilogs und das normale Samba-Dateilog werden deaktiviert. Vorhandene Drucker bleiben konfiguriert. Ein eigenständiger Samba-Server wird vorausgesetzt; Domänenserver werden abgelehnt.

## Konfiguration

```bash
sudo nano /etc/terminzettel/config.toml
```

Änderungen gelten ab dem nächsten Auftrag; ein Neustart ist nicht nötig. Die folgenden Abschnitte in der vorhandenen Datei bearbeiten, nicht doppelt anlegen.

Kopf und Fuß beispielsweise:

```toml
[header]
enabled = true
align = "center"
bold = true
text = "Praxis Beispiel"

[footer]
enabled = true
align = "center"
bold = false
text = "Bitte bringen Sie Ihre Versichertenkarte mit."
```

Mit `enabled = false` lässt sich der jeweilige Block abschalten. Standardziel:

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

Samba-Spooldateien werden beim Übernehmen entfernt. Konvertierungen und CUPS-Zwischendaten liegen auf einem begrenzten RAM-Dateisystem. Das tmpfs kann bei aktiviertem Betriebssystem-Swap ausgelagert werden. PDF wird direkt per Pipe verarbeitet. PostScript und XPS benötigen kurzzeitig Dateien im geschützten RAM-Verzeichnis.

CUPS bekommt nur den festen Auftragsnamen `Terminzettel`. Der Auftrag wird nach Beendigung entfernt, bei Fehlern oder nach 60 Sekunden abgebrochen. Ein Bereinigungsdienst entfernt verwaiste Aufträge und Dateien; bei einem Absturz können Daten bis zum nächsten Bereinigungslauf kurzzeitig im RAM verbleiben. Nach einem Neustart stehen diese Aufträge nicht mehr zur Verfügung. Ein fehlgeschlagener Auftrag wird aus T2med neu gedruckt.

Auch der neue Bonjour-/IPP-Eingang verwendet den vorübergehenden CUPS-Zwischenspeicher. Vom Client übermittelte Benutzernamen und Dokumenttitel können dort während des Auftrags vorhanden sein. Der Folgeauftrag an `TMm10` verwendet den festen Namen `Terminzettel`.

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

Im Unterordner `terminzettel-installer` ausführen:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -B -m unittest discover -s tests -v
bash -n install-terminzettel.sh
```

Den aktuellen [Teststatus und die offenen Gerätetests](https://github.com/thomaskien/t2med-terminzettel/blob/main/TESTSTATUS.md) separat beachten. Die Tests verwenden ausschließlich künstliche Namen und Termine. Der QR wird zusätzlich mit einem unabhängigen Decoder zurückgelesen und bytegenau verglichen. Produktionsabhängigkeiten werden durch den Installer als Debian-Pakete installiert; `zxing-cpp` und `icalendar` werden ausschließlich für Entwicklungstests benötigt.
