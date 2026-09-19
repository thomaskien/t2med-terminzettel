"""Verwaltet ausschließlich die eigene virtuelle CUPS-Warteschlange."""
from pathlib import Path
import tempfile

NAME = "Terminzettel"
URI = "terminzettel:/"
SOCKET = "/run/cups/cups.sock"
PPD = "/usr/local/share/terminzettel/terminzettel.ppd"


def connection():
    import cups
    cups.setUser("root")
    return cups.Connection(host=SOCKET)


def inspect_queue(owned):
    conn = connection()
    names = [name for name in conn.getPrinters() if name.casefold() == NAME.casefold()]
    classes = [name for name in conn.getClasses() if name.casefold() == NAME.casefold()]
    if classes or (names and not owned):
        raise RuntimeError("Eine fremde CUPS-Warteschlange Terminzettel existiert bereits; keine Änderung.")
    if not names:
        return None
    attrs = conn.getPrinterAttributes(names[0])
    if attrs.get("device-uri") != URI:
        raise RuntimeError("Das Ziel der CUPS-Warteschlange Terminzettel wurde verändert; keine Änderung.")
    return {"attributes": attrs, "ppd": Path("/etc/cups/ppd", names[0] + ".ppd").read_bytes()}


def create_queue(run):
    run("lpadmin", "-h", SOCKET, "-p", NAME, "-E", "-v", URI, "-P", PPD,
        "-D", NAME, "-o", "printer-is-shared=true", "-o", "printer-error-policy=abort-job",
        "-o", "job-sheets-default=none,none")


def delete_queue(run, *, optional=False):
    run("lpadmin", "-h", SOCKET, "-x", NAME, optional=optional)


def restore_queue(run, saved):
    attrs = saved["attributes"]
    with tempfile.TemporaryDirectory(prefix="terminzettel-restore-", dir="/run") as directory:
        ppd = Path(directory) / "printer.ppd"
        ppd.write_bytes(saved["ppd"])
        run("lpadmin", "-h", SOCKET, "-p", NAME, "-v", URI, "-P", str(ppd),
            "-D", attrs.get("printer-info", NAME), "-L", attrs.get("printer-location", ""),
            "-o", "printer-is-shared=" + str(attrs.get("printer-is-shared", True)).lower(),
            "-o", "printer-error-policy=" + attrs.get("printer-error-policy", "abort-job"),
            "-o", "job-sheets-default=" + ",".join(attrs.get("job-sheets-default", ["none", "none"])))
    conn = connection()
    (conn.disablePrinter if attrs.get("printer-state") == 5 else conn.enablePrinter)(NAME)
    (conn.acceptJobs if attrs.get("printer-is-accepting-jobs", True) else conn.rejectJobs)(NAME)


def verify_queue():
    attrs = connection().getPrinterAttributes(NAME)
    if attrs.get("device-uri") != URI or not attrs.get("printer-is-shared"):
        raise RuntimeError("Die CUPS-Freigabe Terminzettel ist nicht aktiv.")
