#!/bin/sh
# Qisutu Monitoring: install a site collector without a web interface.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Bitte als root ausführen.' >&2; exit 1; }
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$source_dir"
sha256sum -c SHA256SUMS >/dev/null || { echo 'Ungültige Paketprüfsummen.' >&2; exit 1; }
command -v systemctl >/dev/null || { echo 'Dieser Messsammler-Installer benötigt systemd.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Python 3.9 oder neuer installieren.' >&2; exit 1; }
python3 -c 'import sys,sqlite3,ssl; assert sys.version_info >= (3,9)'
id netzmonitor-collector >/dev/null 2>&1 || useradd --system --home-dir /var/lib/netzmonitor-collector --shell /usr/sbin/nologin netzmonitor-collector
systemctl stop netzmonitor-collector.service 2>/dev/null || true
mkdir -p /opt/netzmonitor-collector /var/lib/netzmonitor-collector
cp -R netzmonitor /opt/netzmonitor-collector/
cp collector.py uninstall-collector.sh /opt/netzmonitor-collector/
chmod 700 /var/lib/netzmonitor-collector
if [ ! -f /var/lib/netzmonitor-collector/collector.json ]; then
 python3 /opt/netzmonitor-collector/collector.py configure
fi
chown -R netzmonitor-collector:netzmonitor-collector /var/lib/netzmonitor-collector
cat > /etc/systemd/system/netzmonitor-collector.service <<'UNIT'
[Unit]
Description=Qisutu Monitoring Messsammler
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=netzmonitor-collector
Group=netzmonitor-collector
WorkingDirectory=/opt/netzmonitor-collector
ExecStart=/usr/bin/python3 /opt/netzmonitor-collector/collector.py run
Restart=on-failure
RestartSec=10
UMask=0077
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now netzmonitor-collector.service
echo 'Messsammler gestartet. Prüfprogramme wie ping, OpenSSH, Net-SNMP und Datenbank-Clients müssen für die zugewiesenen Prüfungen installiert sein.'
