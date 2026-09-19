# Mac-PostScript-Muster

`mac-generic-postscript.ps.gz` wurde ausschließlich aus der künstlichen
`pdf_fixture()` in `test_conversion.py` erzeugt. Keine Patientendaten.

Erzeugung auf macOS mit dem mitgelieferten „Generic PostScript Printer“:

```bash
cupsfilter -p /System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/PrintCore.framework/Versions/A/Resources/Generic.ppd -m application/postscript /tmp/t2med-mac-driver-test.pdf > /tmp/t2med-mac-driver-test.ps
```

Der Benutzername wurde in den PostScript-Metadaten durch `synthetic` und der
Zeitstempel durch `Synthetic fixture` ersetzt; anschließend gzip-komprimiert.
Der Test prüft die tatsächliche Mac-Ausgabe einschließlich eingebetteter Fonts.
