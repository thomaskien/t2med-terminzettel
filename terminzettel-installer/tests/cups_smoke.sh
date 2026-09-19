#!/usr/bin/env bash
# Ausschließlich für die kurzlebige GitHub-Actions-VM, niemals auf dem Praxisrechner.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_OS:-}" != Linux || $EUID -ne 0 ]]; then
  echo "Dieser Integrationstest läuft ausschließlich als root in GitHub Actions." >&2
  exit 1
fi
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
run_installer() {
  python3 -B - "$SOURCE_DIR" "$@" <<'PY'
import sys
sys.path.insert(0, sys.argv.pop(1))
import install
original_run = install.subprocess.run
def trace_run(*args, **kwargs):
    result = original_run(*args, **kwargs)
    if result.returncode and result.stderr:
        print(result.stderr.decode(errors='replace'), file=sys.stderr, flush=True)
    return result
install.subprocess.run = trace_run
install.main()
PY
}
systemctl start cups.service smbd.service avahi-daemon.service
cupsctl --share-printers
cat > /usr/lib/cups/backend/terminzettel-test <<'BACKEND'
#!/usr/bin/python3
import pathlib
import sys
if len(sys.argv) == 1:
    print('direct terminzettel-test:/ "Synthetic printer" "Synthetic printer"')
else:
    data = pathlib.Path(sys.argv[6]).read_bytes() if len(sys.argv) == 7 else sys.stdin.buffer.read()
    pathlib.Path('/tmp/terminzettel-smoke-output').write_bytes(data)
BACKEND
chmod 0700 /usr/lib/cups/backend/terminzettel-test
lpadmin -p TMm10 -E -v terminzettel-test:/ -m raw
run_installer
run_installer
cupstestppd "$SOURCE_DIR/terminzettel.ppd"
python3 -B - "$SOURCE_DIR" <<'PY'
from pathlib import Path
import subprocess
import sys
import time
import cups
sys.path.insert(0, sys.argv[1] + '/tests')
from test_conversion import pdf_fixture
conn = cups.Connection(host='/run/cups/cups.sock')
attrs = conn.getPrinterAttributes('Terminzettel')
assert attrs['printer-is-shared']
assert attrs['device-uri'] == 'terminzettel:/'
assert 'application/pdf' in attrs['document-format-supported']
Path('/tmp/terminzettel-smoke.pdf').write_bytes(pdf_fixture())
conn.printFile('Terminzettel', '/tmp/terminzettel-smoke.pdf', 'Synthetic test', {})
destination = Path('/tmp/terminzettel-smoke-output')
for _ in range(120):
    if destination.exists() and not conn.getJobs(which_jobs='not-completed'):
        break
    time.sleep(0.5)
assert destination.exists(), 'No receipt reached the synthetic printer'
data = destination.read_bytes()
assert b'Testperson Alpha' in data
assert b'\x1dv0\x00' in data, 'QR raster missing'
assert data.endswith(b'\x1dV\x01'), 'Cut missing'
assert not conn.getJobs(which_jobs='not-completed'), 'Jobs did not finish'
listing = subprocess.run(['avahi-browse', '-rt', '_ipp._tcp'], capture_output=True, check=True, timeout=20).stdout
assert b'Terminzettel' in listing, 'Bonjour advertisement missing'
assert Path('/run/terminzettel/samba-cache').stat().st_mode & 0o777 == 0o755
print('PDF -> CUPS -> Terminzettel -> ESC/POS + QR -> TMm10: OK; Bonjour: OK')
PY
run_installer --uninstall
python3 -B - <<'PY'
import cups
conn = cups.Connection(host='/run/cups/cups.sock')
assert 'Terminzettel' not in conn.getPrinters()
assert 'TMm10' in conn.getPrinters()
print('Uninstall removes only the virtual printer: OK')
PY
