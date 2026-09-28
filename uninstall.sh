#!/bin/sh
# Standalone entry point, also usable from the extracted installation ZIP.
set -eu
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9; do
 if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' >/dev/null 2>&1; then
  exec "$candidate" "$SOURCE/uninstall.py" "$@"
 fi
done
echo 'Python >= 3.9 fehlt. Bitte über die Paketverwaltung bereitstellen.' >&2
exit 1
