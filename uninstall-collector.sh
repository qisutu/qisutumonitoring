#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Bitte als root ausführen.' >&2; exit 1; }
printf '%s' 'Messsammler einschließlich Zugangsdaten und Puffer vollständig entfernen? [ja/NEIN] '
read -r confirmation
[ "$confirmation" = ja ] || exit 0
systemctl disable --now netzmonitor-collector.service 2>/dev/null || true
rm -f /etc/systemd/system/netzmonitor-collector.service
systemctl daemon-reload
rm -rf /opt/netzmonitor-collector /var/lib/netzmonitor-collector
if id netzmonitor-collector >/dev/null 2>&1; then userdel netzmonitor-collector; fi
if getent group netzmonitor-collector >/dev/null 2>&1; then groupdel netzmonitor-collector; fi
echo 'Messsammler entfernt.'
