#!/bin/sh
# Qisutu Monitoring installer: no Docker, no external web server, no pip downloads.
set -eu
umask 027
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DESTDIR=""
START=1
PACKAGES=1
INSTALL_LANGUAGE=""
while [ "$#" -gt 0 ]; do
 case "$1" in
  --destdir) [ "$#" -ge 2 ] || exit 2; DESTDIR=$2; START=0; PACKAGES=0; shift 2 ;;
  --language) [ "$#" -ge 2 ] || exit 2; INSTALL_LANGUAGE=$2; shift 2 ;;
  --no-start) START=0; shift ;;
  --skip-packages) PACKAGES=0; shift ;;
  *) echo 'Aufruf: sh install.sh [--language cs|de|en|es|fr|it|nl|pl|pt-BR|pt-PT|tr] [--no-start] [--skip-packages] [--destdir STAGING-VERZEICHNIS]' >&2; exit 2 ;;
 esac
done
case "$INSTALL_LANGUAGE" in ''|cs|de|en|es|fr|it|nl|pl|pt-BR|pt-PT|tr) ;; *) echo 'Unknown language / Unbekannte Sprache.' >&2; exit 2 ;; esac
[ "$(uname -s)" = Linux ] || { echo 'Dieses Paket ist für Linux vorgesehen.' >&2; exit 1; }
[ -n "$DESTDIR" ] || [ "$(id -u)" = 0 ] || { echo 'Bitte mit sudo sh install.sh oder als root starten.' >&2; exit 1; }
case "$DESTDIR" in ''|/*) ;; *) echo '--destdir muss ein absoluter Pfad sein.' >&2; exit 1 ;; esac
if command -v sha256sum >/dev/null 2>&1; then
 (cd "$SOURCE" && sha256sum -c SHA256SUMS >/dev/null) || { echo 'Paketprüfung fehlgeschlagen. Installation abgebrochen.' >&2; exit 1; }
else
 echo 'sha256sum fehlt. Bitte die coreutils des Systems bereitstellen.' >&2; exit 1
fi
find_python() {
 for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys,sqlite3,ssl; sys.exit(0 if sys.version_info >= (3,9) else 1)' >/dev/null 2>&1; then
   PYTHON=$(command -v "$candidate"); return 0
  fi
 done
 return 1
}
if ! find_python || ! command -v ping >/dev/null 2>&1 || ! command -v openssl >/dev/null 2>&1; then
 if [ "$PACKAGES" = 1 ]; then
  echo 'Benötigte Systempakete werden installiert …'
  if command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y --no-remove --no-upgrade python3 iputils-ping openssl
  elif command -v dnf >/dev/null 2>&1; then dnf install -y python3 iputils openssl; find_python || dnf install -y python3.11
  elif command -v yum >/dev/null 2>&1; then yum install -y python3 iputils openssl; find_python || yum install -y python3.11
  elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive install python3 iputils openssl; find_python || zypper --non-interactive install python311
  elif command -v apk >/dev/null 2>&1; then apk add python3 iputils openssl
  elif command -v pacman >/dev/null 2>&1; then pacman -S --needed --noconfirm python iputils openssl
  elif command -v xbps-install >/dev/null 2>&1; then xbps-install -Sy python3 iputils openssl
  else echo 'Bitte Python >= 3.9 mit SQLite/SSL, ping und openssl über die Paketverwaltung installieren.' >&2; exit 1
  fi
 fi
fi
find_python || { echo 'Python >= 3.9 mit SQLite und SSL fehlt.' >&2; exit 1; }
if [ -z "$DESTDIR" ]; then
 command -v ping >/dev/null 2>&1 || { echo 'ping fehlt. Bitte iputils-ping bzw. iputils installieren.' >&2; exit 1; }
 command -v openssl >/dev/null 2>&1 || { echo 'openssl fehlt.' >&2; exit 1; }
fi
if { ! command -v ssh >/dev/null 2>&1 || ! command -v ssh-keyscan >/dev/null 2>&1; } && [ "$PACKAGES" = 1 ]; then
 echo 'OpenSSH-Client für Ressourcenabfragen wird installiert …'
 if command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y --no-remove --no-upgrade openssh-client
 elif command -v dnf >/dev/null 2>&1; then dnf install -y openssh-clients
 elif command -v yum >/dev/null 2>&1; then yum install -y openssh-clients
 elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive install openssh
 elif command -v apk >/dev/null 2>&1; then apk add openssh-client
 elif command -v pacman >/dev/null 2>&1; then pacman -S --needed --noconfirm openssh
 elif command -v xbps-install >/dev/null 2>&1; then xbps-install -Sy openssh
 else echo 'OpenSSH-Client bitte über die Paketverwaltung bereitstellen.' >&2
 fi
fi
# Only the SNMP client is needed on the monitoring server.
if { ! command -v snmpbulkwalk >/dev/null 2>&1 || ! command -v snmpwalk >/dev/null 2>&1; } && [ "$PACKAGES" = 1 ]; then
 echo 'Net-SNMP für Ressourcen- und Schnittstellenabfragen wird installiert …'
 if command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y --no-remove --no-upgrade snmp
 elif command -v dnf >/dev/null 2>&1; then dnf install -y net-snmp-utils
 elif command -v yum >/dev/null 2>&1; then yum install -y net-snmp-utils
 elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive install net-snmp
 elif command -v apk >/dev/null 2>&1; then apk add net-snmp-tools
 elif command -v pacman >/dev/null 2>&1; then pacman -S --needed --noconfirm net-snmp
 elif command -v xbps-install >/dev/null 2>&1; then xbps-install -Sy net-snmp
 else echo 'Net-SNMP-Client bitte über die Paketverwaltung bereitstellen.' >&2
 fi
fi
if [ -z "$DESTDIR" ] && { ! command -v snmpbulkwalk >/dev/null 2>&1 || ! command -v snmpwalk >/dev/null 2>&1; }; then
 echo 'Hinweis: SNMP-Prüfungen benötigen snmpbulkwalk und snmpwalk. SSH, Ping und Dienste bleiben nutzbar.' >&2
fi
# Reuse either MariaDB or MySQL; a missing PostgreSQL client must never
# trigger a switch of the existing MySQL/MariaDB package family.
install_database_client() {
 db_engine=$1
 echo "Fehlender Datenbank-Client wird installiert: $db_engine …"
 if command -v apt-get >/dev/null 2>&1; then
  case "$db_engine" in postgresql) db_package=postgresql-client ;; mysql) db_package=mariadb-client ;; esac
  # Enforce the removal guard on the real transaction (a simulation alone
  # would leave a race). Never retry without it or request a server package.
  apt-get update && apt-get install -y --no-remove --no-upgrade "$db_package" ca-certificates
 elif command -v dnf >/dev/null 2>&1; then
  case "$db_engine" in postgresql) db_package=postgresql ;; mysql) db_package=mariadb ;; esac
  dnf install -y "$db_package" ca-certificates
 elif command -v yum >/dev/null 2>&1; then
  case "$db_engine" in postgresql) db_package=postgresql ;; mysql) db_package=mariadb ;; esac
  yum install -y "$db_package" ca-certificates
 elif command -v zypper >/dev/null 2>&1; then
  case "$db_engine" in postgresql) db_package=postgresql ;; mysql) db_package=mariadb-client ;; esac
  zypper --non-interactive install "$db_package" ca-certificates
 elif command -v apk >/dev/null 2>&1; then
  case "$db_engine" in postgresql) db_package=postgresql-client ;; mysql) db_package=mariadb-client ;; esac
  apk add "$db_package" ca-certificates
 elif command -v pacman >/dev/null 2>&1; then
  case "$db_engine" in postgresql) db_package=postgresql-libs ;; mysql) db_package=mariadb-clients ;; esac
  pacman -S --needed --noconfirm "$db_package" ca-certificates
 elif command -v xbps-install >/dev/null 2>&1; then
  case "$db_engine" in postgresql) db_package=postgresql-client ;; mysql) db_package=mariadb-client ;; esac
  xbps-install -Sy "$db_package" ca-certificates
 else
  return 1
 fi
}
if [ "$PACKAGES" = 1 ]; then
 if ! command -v psql >/dev/null 2>&1; then
  if ! install_database_client postgresql; then
   echo 'PostgreSQL-Client konnte nicht sicher installiert werden. Passendes Clientpaket bitte manuell bereitstellen; PostgreSQL-Prüfungen sind bis dahin nicht verfügbar.' >&2
  fi
 fi
 if ! command -v mariadb >/dev/null 2>&1 && ! command -v mysql >/dev/null 2>&1; then
  if ! install_database_client mysql; then
   echo 'MariaDB/MySQL-Client konnte nicht sicher installiert werden. Passendes Clientpaket bitte manuell bereitstellen; MariaDB/MySQL-Prüfungen sind bis dahin nicht verfügbar.' >&2
  fi
 fi
fi
APP="$DESTDIR/opt/netzmonitor"
DATA="$DESTDIR/var/lib/netzmonitor"
BIN="$DESTDIR/usr/local/bin"
USER_NAME=netzmonitor
if [ -z "$DESTDIR" ]; then
 if ! id "$USER_NAME" >/dev/null 2>&1; then
  if command -v useradd >/dev/null 2>&1; then
   useradd --system --user-group --home-dir /var/lib/netzmonitor --shell /bin/false "$USER_NAME"
  elif command -v adduser >/dev/null 2>&1; then
   adduser -S -D -H -h /var/lib/netzmonitor -s /bin/false "$USER_NAME"
  else echo 'Benutzerverwaltung fehlt. Systembenutzer netzmonitor zuerst anlegen.' >&2; exit 1
  fi
 fi
fi
mkdir -p "$APP" "$DATA" "$BIN"
# Stop an existing service before updating its program files.
if [ -z "$DESTDIR" ] && [ -f "$APP/control.py" ]; then
 "$PYTHON" "$APP/control.py" stop || { echo 'Vorhandener Dienst konnte nicht gestoppt werden.' >&2; exit 1; }
fi
cp -R "$SOURCE/netzmonitor" "$SOURCE/vendor" "$APP/"
cp "$SOURCE/run.py" "$SOURCE/control.py" "$SOURCE/uninstall.py" "$SOURCE/uninstall.sh" "$SOURCE"/README*.md "$SOURCE/CHANGELOG.md" "$SOURCE/DEVELOPMENT.md" "$SOURCE/LICENSE" "$SOURCE/THIRD_PARTY_NOTICES.md" "$APP/"
cp -R "$SOURCE/docs" "$APP/"
# Remove only documentation delivered under the previous package filenames.
"$PYTHON" - "$APP" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for name in ('README-DE.txt', 'INSTALLIEREN.txt', 'SPRACHEN-AGENTEN.txt',
             'MELDUNGEN-EINRICHTEN.txt', 'KUNDENANLEITUNG-FREISCHALTUNG.txt',
             'DEINSTALLIEREN.txt', 'FREISCHALTDATEIFORMAT.txt', 'CHANGELOG.txt',
             'THIRD-PARTY.txt', 'vendor/README.txt', 'vendor/TORNADO-LICENSE.txt'):
    path = root / name
    if path.is_file() or path.is_symlink():
        path.unlink()
PY
chmod -R go-w "$APP"
find "$APP" -type d -exec chmod 755 {} \;
find "$APP" -type f -exec chmod 644 {} \;
cat > "$BIN/netzmonitor" <<EOF
#!/bin/sh
exec '$PYTHON' /opt/netzmonitor/control.py "\$@"
EOF
chmod 755 "$BIN/netzmonitor"
if [ -n "$DESTDIR" ]; then
 echo "Staging-Paket erstellt: $DESTDIR (ohne Dienst, Benutzer oder Dateninitialisierung)."
 exit 0
fi
if [ -n "$INSTALL_LANGUAGE" ]; then
 "$PYTHON" "$APP/run.py" init --data-dir "$DATA" --language "$INSTALL_LANGUAGE"
else
 "$PYTHON" "$APP/run.py" init --data-dir "$DATA"
fi
if [ ! -f "$DATA/server.crt" ] || [ ! -f "$DATA/server.key" ]; then
 openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 \
  -subj '/CN=Qisutu Monitoring' -keyout "$DATA/server.key" -out "$DATA/server.crt" >/dev/null 2>&1
fi
chown -R "$USER_NAME:$(id -gn "$USER_NAME")" "$DATA"
chmod 750 "$DATA"
chmod 600 "$DATA/config.json" "$DATA/server.key"
if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
 cat > /etc/systemd/system/netzmonitor.service <<EOF
[Unit]
Description=Qisutu Monitoring - lokale Netzwerküberwachung
After=network.target

[Service]
Type=simple
User=netzmonitor
Group=$(id -gn netzmonitor)
WorkingDirectory=/opt/netzmonitor
ExecStart=$PYTHON /opt/netzmonitor/run.py serve --data-dir /var/lib/netzmonitor
Restart=on-failure
RestartSec=5
TimeoutStopSec=90
UMask=0027
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
AmbientCapabilities=CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_RAW

[Install]
WantedBy=multi-user.target
EOF
 systemctl daemon-reload
 systemctl enable netzmonitor
 if [ "$START" = 1 ]; then
  systemctl restart netzmonitor
  "$PYTHON" -c 'import time; time.sleep(1)'
  systemctl is-active --quiet netzmonitor || { echo 'Dienststart fehlgeschlagen. Bitte journalctl -u netzmonitor -n 40 prüfen.' >&2; exit 1; }
 fi
elif command -v rc-update >/dev/null 2>&1 && [ -d /etc/init.d ]; then
 cat > /etc/init.d/netzmonitor <<'EOF'
#!/sbin/openrc-run
name="Qisutu Monitoring"
description="Lokale Netzwerküberwachung"
depend() { need net; }
start() { /usr/local/bin/netzmonitor start; }
stop() { /usr/local/bin/netzmonitor stop; }
EOF
 chmod 755 /etc/init.d/netzmonitor
 rc-update add netzmonitor default
 if [ "$START" = 1 ]; then rc-service netzmonitor start; fi
elif command -v update-rc.d >/dev/null 2>&1 || command -v chkconfig >/dev/null 2>&1; then
 cat > /etc/init.d/netzmonitor <<'EOF'
#!/bin/sh
### BEGIN INIT INFO
# Provides: netzmonitor
# Required-Start: $network $remote_fs
# Required-Stop: $network $remote_fs
# Default-Start: 2 3 4 5
# Default-Stop: 0 1 6
# Short-Description: Qisutu Monitoring
### END INIT INFO
# chkconfig: 2345 90 10
exec /usr/local/bin/netzmonitor "$@"
EOF
 chmod 755 /etc/init.d/netzmonitor
 if command -v update-rc.d >/dev/null 2>&1; then update-rc.d netzmonitor defaults; else chkconfig --add netzmonitor; fi
 if [ "$START" = 1 ]; then "$BIN/netzmonitor" start; fi
else
 echo 'Kein unterstütztes Autostart-System erkannt. Start/Stop erfolgt über netzmonitor; Autostart bitte im vorhandenen Dienstmanager hinterlegen.'
 if [ "$START" = 1 ]; then "$BIN/netzmonitor" start; fi
fi
echo ''
echo 'Qisutu Monitoring wurde installiert.'
echo 'Browseradresse: https://SERVERADRESSE:8787'
echo 'Bei Neuinstallation: Startpasswort oben beachten und bei der ersten Anmeldung ändern.'
echo 'Bei einem Update bleiben Zugang, Geräte und Messwerte erhalten. Browser mit Strg+F5 neu laden.'
echo 'Das zunächst selbstsignierte Zertifikat verursacht einen Browserhinweis.'
echo 'Status prüfen: sudo netzmonitor status'
echo 'Alle Prüfungen am Gerät verwalten: Geräte öffnen und Einrichten anklicken.'
echo 'Ping-Zugriff bei Bedarf prüfen: sudo netzmonitor doctor'
