#!/usr/bin/env bash
set -euo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "--help" ]]; then
  echo "Installation: sudo ./install-terminzettel.sh"
  echo "Entfernen:    sudo ./install-terminzettel.sh --uninstall"
  exit 0
fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--uninstall" ) ]]; then
  echo "Unbekannte Option. Verwende --help." >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo "Bitte mit sudo ausführen." >&2
  exit 1
fi
if [[ "$(uname -s)" != "Linux" ]] || ! command -v apt-get >/dev/null || ! command -v systemctl >/dev/null; then
  echo "Raspberry Pi OS mit apt und systemd erforderlich." >&2
  exit 1
fi
if ! /usr/bin/python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo "Python 3.10 oder neuer erforderlich. Bitte Raspberry Pi OS aktualisieren." >&2
  exit 1
fi
if [[ "${1:-}" != "--uninstall" ]]; then
  echo "Terminzettel verwendet die vorhandene lokale CUPS-Warteschlange."
  echo "CUPS-Zwischendaten und Samba-Druckmetadaten werden für diesen Rechner auf RAM umgestellt."
  echo "Druckaufträge und Druckhistorie bleiben nach einem Neustart nicht erhalten."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3-tomli python3-cups python3-qrcode python3-pil tzdata samba cups-client poppler-utils ghostscript libgxps-utils
fi
exec /usr/bin/python3 -B "$SOURCE_DIR/install.py" "$@"
