# T2med-Terminzettel

Einfacher Terminbon für einen 58-mm-ESC/POS-Drucker: in T2med die Freigabe **Terminzettel** auswählen. Die Ausgabe erfolgt auf dem Raspberry Pi über die bestehende CUPS-Warteschlange **TMm10**.

- Eine Seite und ein Patient pro Auftrag.
- Termine chronologisch auf dem Bon.
- Optional ein vollständig offline nutzbarer Kalender-QR für alle Termine.
- Titel, Dauer, Zeitzone und optionale Praxisadresse über TOML einstellbar.
- Keine Belegarchivierung oder Patientendaten in Programm-Logs.

```bash
cd terminzettel-installer
sudo ./install-terminzettel.sh
```

[Installation, Voraussetzungen und Konfiguration](terminzettel-installer/README.md) · [Teststatus und offene Gerätetests](TESTSTATUS.md)

Der Installer stellt den CUPS-Zwischenspeicher und Samba-Druckcache des Raspberry Pi auf RAM um. Die vollständige Prüfung am Raspberry Pi, TM-m10 und den vorgesehenen Smartphones steht noch aus.
