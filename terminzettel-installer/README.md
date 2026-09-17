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
