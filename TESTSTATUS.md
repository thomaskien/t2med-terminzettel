# Teststatus

Stand: 19. September 2026. Die Software ist für den Gerätetest vorbereitet; eine Produktivfreigabe am Raspberry Pi und Drucker steht noch aus. Alle Testdaten sind künstlich.

## Automatisiert geprüft

- 96 Tests lokal unter Python 3.14 mit CUPS-Eingang und ohne cgroup-/Swap-Sperre: 95 bestanden, ein PostScript-Integrationstest übersprungen, weil das lokal installierte Ghostscript nicht ausführbar ist.
- Echte PDF-Textextraktion mit Poppler; PostScript-Fehlerbehandlung und Aufräumen separat getestet.
- Einseitige T2med-Erkennung, mehrzeilige Beschreibungen, Sortierung, Duplikate und Ablehnung beschädigter Terminzeilen.
- Flüchtige Dateiverarbeitung, Löschung übernommener Eingaben auch im Fehlerfall, feste Fehlermeldungen ohne Beleginhalte sowie CUPS-Auftragsablauf mit simuliertem Server.
- Installer-Konfiguration, Sicherung/Rücknahme bei Dienstfehlern und Schutz nachträglich geänderter Dateien. Installation und Verarbeitung mit normalem tmpfs ohne cgroup-/Swap-Prüfungen; Einhängefehler werden weiterhin erkannt.
- iCalendar für einen, zwei und fünf Termine; Zeitzonen einschließlich Sommer-/Winterzeit, Dauer, Endzeit, Sortierung, Duplikate, Escaping, UTF-8-Zeilenfaltung und optionale Adresse. Unabhängig mit `icalendar` eingelesen.
- QR aus dem ESC/POS-Raster mit `zxing-cpp` zurückgelesen und bytegenau mit dem Kalender verglichen. Ein QR-Fehler lässt den lesbaren Bon unverändert.
- Python-3.10-Syntax aller Programmmodule und 16 Parser-Tests mit einem echten Python-3.10-Interpreter geprüft.
- Shell-Syntax, CLI-Selbsttest und Git-Diff auf Formatfehler geprüft.

Ein zusätzlicher Linux-Integrationstest prüft Installation, Update, PDF-Eingang über CUPS, fertigen ESC/POS-Bon mit QR, Bonjour-Ankündigung und Deinstallation mit einem simulierten Ausgabedrucker. Der aktuelle Erfolg dieses Tests ist unter Actions sichtbar. Die PPD wurde lokal mit `cupstestppd` geprüft.

Die GitHub-Actions-Konfiguration führt die Suite unter Python 3.10 und 3.13 mit Poppler und Ghostscript aus. Ihr aktueller Ausführungsstatus ist im Repository unter **Actions** sichtbar.

## Gemessene QR-Größen

Standardtitel, 15 Minuten Dauer, Fehlerkorrektur M, vier Randmodule, ohne Adresse. Die konkrete Größe hängt vom Inhalt und der Encoder-Version ab.

| Termine | Maximale Breite | Ergebnis im Test |
| --- | --- | --- |
| 1 | 360 Punkte | 292 Punkte, 4 Punkte pro Modul, dekodiert |
| 2 | 360 Punkte | 340 Punkte, 4 Punkte pro Modul, dekodiert |
| 3 | 360 Punkte | 291 Punkte, 3 Punkte pro Modul, dekodiert |
| 5 | 360 Punkte | Kein QR; normaler Textbon und feste Fehlermeldung |
| 5 | 384 Punkte | 363 Punkte, 3 Punkte pro Modul, dekodiert |

Ein langer Adresszusatz kann auch bei 384 Punkten zu groß werden. Die Software druckt dann den vollständigen Textbon ohne QR. Es gibt keine Verkleinerung auf unlesbare ein oder zwei Punkte pro Modul.

## Noch am Gerät prüfen

1. Installation auf dem vorgesehenen Raspberry Pi OS, Neustart und lokaler CUPS-Zugriff auf `TMm10`; temporäres RAM-Dateisystem und tatsächliche Dienstberechtigungen.
2. Bonjour-Drucker auf dem Mac unter „Default“ hinzufügen. Echter T2med-Auftrag über IPP und gegebenenfalls Samba: PDF und gegebenenfalls PostScript/XPS, Umlaute, Layout und Schnitt. XPS wurde lokal nicht mit einem echten Konverter geprüft.
3. Drucker ausgeschaltet, Papier leer und abgebrochener Auftrag: Verhalten von CUPS und anschließende Bereinigung kontrollieren.
4. Gedruckte Bons mit einem, zwei, drei und fünf Terminen: QR-Erkennung auf iPhone und Android, Import **aller** Kalendereinträge, richtige Uhrzeiten und erneutes Scannen. Für fünf Termine zusätzlich die Einstellung 384 Punkte testen.
5. Optionaler Praxisadresszusatz und eine Kalender-App ohne Internetverbindung.

Das erfolgreiche maschinelle Dekodieren beweist den QR-Inhalt. Es beweist nicht, dass jede Smartphone-Kamera einen direkt eingebetteten Kalender mit mehreren Einträgen importieren kann. Dieser Test bleibt Voraussetzung für den Praxiseinsatz der QR-Funktion.
