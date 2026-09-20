# Version 1.3

Unter dem Datum stehen jetzt links die Uhrzeit und Terminart und rechts der jeweilige Kalender-QR. Die große Schrift bleibt erhalten; lange Terminarten werden umgebrochen. Die Beschriftung „Termin speichern“ entfällt vollständig.

Der TOML-Wert `calendar_qr.summary` ist jetzt der Präfix des Kalender-Titels: `Praxis ABC` und die Terminart `Lufu` ergeben **Praxis ABC: Lufu**. Der Installer fragt diesen Präfix ab; `-` entfernt ihn. Bestehende Werte bleiben als Vorgabe erhalten. Jeder QR enthält weiterhin genau einen Termin; jeder gewünschte Termin wird einzeln gescannt.

QR, Praxiskopf und Fußtext bleiben abschaltbar, die Praxisadresse bleibt optional. Verarbeitung und QR-Erzeugung erfolgen lokal ohne Archivierung. Der Kalender-Titel enthält jetzt ausdrücklich die jeweilige Terminart, weiterhin keinen Patientennamen.

## Installation / Update

Auf dem Raspberry Pi:

```bash
cd ~ &&
curl -fL https://github.com/thomaskien/t2med-terminzettel/archive/refs/tags/v1.3.tar.gz -o terminzettel-1.3.tar.gz &&
tar -xzf terminzettel-1.3.tar.gz &&
cd t2med-terminzettel-1.3/terminzettel-installer &&
sudo ./install-terminzettel.sh
```

Als root kann `sudo` entfallen. Die vorhandene TOML wird übernommen. Nach dem Update einen Bon aus T2med drucken und Layout sowie QR-Import auf dem Smartphone prüfen. Automatisierte Tests prüfen Druckbefehle, QR-Inhalte und den CUPS-Druckweg; das neue Layout muss zusätzlich am tatsächlichen TM-m10 bestätigt werden.
