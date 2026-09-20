# Teststatus

Stand: 20. September 2026. Die automatisierten Tests verwenden ausschließlich künstliche Daten. Der direkte PDF-Druck und anschließend der normale T2med-Druck mit OCR am vorgesehenen TM-m10 wurden vom Benutzer bestätigt. Beim iPhone-Test des Sammel-QR wurde nur der erste Termin übernommen. Die neue Ausgabe mit kleinen Einzelcodes muss noch auf dem gedruckten Bon am iPhone bestätigt werden.

## Automatisiert geprüft

- 136 Tests lokal unter Python 3.14 mit CUPS-Eingang und ohne cgroup-/Swap-Sperre: 134 bestanden, zwei PostScript-Integrationstests übersprungen, weil das lokal installierte Ghostscript nicht ausführbar ist.
- Installer-Abfragen für mehrzeiligen Praxiskopf, Kalender-QR, Kalender-Terminname und Fußtext: getrennte Schalter, bestehende Werte, Textlöschung, Abbruch vor Systemänderungen und unbeaufsichtigte Installation ohne Abfragen.
- Tatsächliche ESC/POS-Schriftgrößenbefehle geprüft: sämtliche Textzeilen doppelt hoch und doppelt breit, 17 statt 35 Zeichen je Zeile, Groß-/Kleinschreibung erhalten, Rücksetzen vor dem Schnitt.
- Echte lokale OCR mit Tesseract und deutschem Sprachmodell: Bild-PDF ohne Textschicht, ein und fünf Termine, mehrzeiliger Termintyp und abgesetzter Praxisfuß. Ergebnis mit der Text-PDF verglichen; keine Arbeitsdateien zurückgelassen.
- OCR-Abschaltung, Seitenbegrenzung, fehlende Abhängigkeit, leeres Ergebnis und Wochentag-/Datumswiderspruch getestet. Konfigurationsupdates aktivieren OCR, erhalten aber ein ausdrücklich gesetztes `false`.
- Mac-PDF-Treiber mit `cupstestppd` und beiden PDF-MIME-Typen ohne zusätzlichen Konvertierungsfilter geprüft.
- Echte PDF-Textextraktion mit Poppler; PostScript-Fehlerbehandlung und Aufräumen separat getestet.
- Einseitige T2med-Erkennung, mehrzeilige Beschreibungen, Sortierung, Duplikate und Ablehnung beschädigter Terminzeilen.
- Konkrete feste CUPS-Fehlermeldungen für Verarbeitung, Konfiguration und Ausgabe; fremde Fehlertexte, Benutzernamen und Dokumenttitel bleiben unterdrückt.
- Flüchtige Dateiverarbeitung, Löschung übernommener Eingaben auch im Fehlerfall, feste Fehlermeldungen ohne Beleginhalte sowie CUPS-Auftragsablauf mit simuliertem Server.
- Installer-Konfiguration, Sicherung/Rücknahme bei Dienstfehlern und Schutz nachträglich geänderter Dateien. Installation und Verarbeitung mit normalem tmpfs ohne cgroup-/Swap-Prüfungen; Einhängefehler werden weiterhin erkannt.
- iCalendar für einen, zwei und fünf Termine; Zeitzonen einschließlich Sommer-/Winterzeit, Dauer, Endzeit, Sortierung, Duplikate, Escaping, UTF-8-Zeilenfaltung und optionale Adresse. Unabhängig mit `icalendar` eingelesen.
- Einzel-QRs aus dem ESC/POS-Raster mit `zxing-cpp` zurückgelesen: pro Code genau ein Ereignis, jeder Termin an der passenden Stelle, auch bei mehreren Terminen am selben Tag. Ein QR-Fehler lässt die lesbaren Termine und die übrigen Codes erhalten.
- Python-3.10-Syntax aller Programmmodule und 16 Parser-Tests mit einem echten Python-3.10-Interpreter geprüft.
- Shell-Syntax, CLI-Selbsttest und Git-Diff auf Formatfehler geprüft.

Der [Linux-Integrationstest vom 20. September 2026](https://github.com/thomaskien/t2med-terminzettel/actions/runs/35503056571) ist erfolgreich: Installation, Update, Text-PDF, PostScript und Bild-PDF mit echter OCR über IPP/CUPS, fertiger ESC/POS-Bon mit großer Schrift, Hinweistext und QR, Bonjour-Ankündigung und Deinstallation mit einem simulierten Ausgabedrucker. Die vorhandene Zielwarteschlange bleibt erhalten. Der Test läuft mit aktivem AppArmor; der Installer ergänzt gegebenenfalls die benötigten Regeln für den RAM-Zwischenspeicher. Beide PPDs bestehen `cupstestppd`.

Im selben GitHub-Actions-Lauf wurden alle 127 Tests sowohl unter Python 3.10 als auch unter Python 3.13 ausgeführt: jeweils 126 bestanden, nur der ausschließlich unter macOS verfügbare Filtertest wurde übersprungen. Enthalten sind echte OCR mit dem deutschen Sprachpaket, PostScript-Konvertierung und ein mit dem macOS-Treiber „Generic PostScript Printer“ erzeugter Musterzettel. Auch die sichtbare sichere Fehlermeldung nach einer abgewiesenen Eingabe ist mit laufendem CUPS geprüft. Weitere Ausführungen sind im Repository unter **Actions** sichtbar.

## Lokaler Abgleich des T2med-Druckwegs

Die gespeicherte Original-PDF enthält auslesbaren Text. Die untersuchten Mac-Druckaufträge enthalten dagegen nur ein Bild. Der neue OCR-Weg wurde ausschließlich lokal und im Arbeitsspeicher an einem solchen Auftrag geprüft: Patientenname, alle fünf Daten, Uhrzeiten, Wochentage und Termintypen stimmen mit der Original-PDF überein. Die zugehörigen Belegdaten sind weder im Repository noch in GitHub Actions enthalten. Der Benutzer hat anschließend den erfolgreichen Druck aus T2med auf der kienzlebox bestätigt.

## Gemessene QR-Größen

Standardtitel, 15 Minuten Dauer, Fehlerkorrektur M, vier Randmodule, ohne Adresse. Die neue Obergrenze ist 256 Punkte. Die konkrete Größe hängt vom Titel, der Adresse und der Encoder-Version ab.

| Termine auf dem Bon | QR-Codes | Größe je Code | Inhalt je Code |
| --- | --- | --- | --- |
| 1 | 1 | 219 × 219 Punkte | Genau ein Termin |
| 2 | 2 | Je 219 × 219 Punkte | Jeweils der zugehörige Termin |
| 5 | 5 | Je 219 × 219 Punkte | Jeweils der zugehörige Termin |

ESC/POS ergänzt die Rasterbreite auf volle Bytes, hier 224 Punkte mit weißer Auffüllung. Die vorherige Sammel-Ausgabe für fünf Termine war 363 × 363 Punkte groß; der Kalender enthielt alle Einträge, aber das getestete iPhone importierte nur den ersten.

Ein langer Titel oder Adresszusatz kann eine größere Obergrenze (300 bis maximal 384 Punkte) benötigen. Passt ein Code nicht oder schlägt seine Erzeugung fehl, fehlt nur dieser QR. Der vollständige Termintext und andere Codes werden weiter gedruckt. Mindestens drei Punkte pro Modul bleiben vorgeschrieben.

## Noch am Gerät prüfen

1. Update auf dem vorgesehenen Raspberry Pi OS, Neustart und lokaler CUPS-Zugriff auf `TMm10`; temporäres RAM-Dateisystem und tatsächliche Dienstberechtigungen.
2. Echter T2med-Auftrag über den vorhandenen Bonjour-Drucker nach dem Einzel-QR-Update: Termine und Namen auf dem Bon mit dem Original vergleichen, Umlaute, Layout und Schnitt prüfen. Gegebenenfalls zusätzlich Samba/PostScript/XPS testen. XPS wurde lokal nicht mit einem echten Konverter geprüft.
3. Drucker ausgeschaltet, Papier leer und abgebrochener Auftrag: Verhalten von CUPS und anschließende Bereinigung kontrollieren.
4. Gedruckte Bons mit einem, zwei, drei und fünf Terminen: QR-Erkennung auf iPhone und Android, Import **aller** Kalendereinträge, richtige Uhrzeiten und erneutes Scannen. Alle Codes einzeln scannen; neue Vorgabe 256 Punkte je Code.
5. Optionaler Praxisadresszusatz und eine Kalender-App ohne Internetverbindung.

Das erfolgreiche maschinelle Dekodieren beweist den QR-Inhalt. Die kleineren gedruckten Einzelcodes müssen zusätzlich auf realen Smartphones gelesen und jeweils dem richtigen Termin zugeordnet werden. Dieser Test bleibt Voraussetzung für den Praxiseinsatz der QR-Funktion.
