"""Ping, TCP and HTTP checks, isolated to enforce a total deadline including DNS."""
import http.client
import json
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit, quote


SERVICE_SELECT = '''SELECT s.*, d.address AS device_address, d.name AS device_name,
    d.enabled AS device_enabled, d.revision AS device_revision, d.blocked AS device_blocked,d.license_blocked AS device_license_blocked,d.block_revision AS device_block_revision
    FROM services s JOIN devices d ON d.id=s.device_id'''


def status_codes(value):
    value = str(value).strip()
    if not value or len(value) > 200:
        raise ValueError('HTTP-Statuscodes angeben, z. B. 200-299 oder 200,301,302.')
    accepted = set()
    for part in value.split(','):
        match = re.fullmatch(r'\s*([1-5][0-9]{2})(?:\s*-\s*([1-5][0-9]{2}))?\s*', part)
        if not match:
            raise ValueError('HTTP-Statuscodes: 100 bis 599, mit Komma oder als Bereich.')
        start, end = int(match[1]), int(match[2] or match[1])
        if end < start:
            raise ValueError('Der HTTP-Statusbereich ist umgekehrt.')
        accepted.update(range(start, end + 1))
    return accepted


def http_url(value):
    from .core import address
    value = str(value).strip()
    if len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Die URL ist zu lang oder enthält Steuerzeichen.')
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError()
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError()
        host = address(parsed.hostname.encode('idna').decode('ascii'))
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError('Vollständige HTTP/HTTPS-URL ohne Zugangsdaten oder #-Fragment angeben.')
    authority = ('[' + host + ']') if ':' in host else host
    if port is not None:
        authority += ':' + str(port)
    return urlunsplit((parsed.scheme, authority, quote(parsed.path or '/', safe="/%:@!$&'()*+,;=-._~"),
                      quote(parsed.query, safe="%/:?@!$&'()*+,;=-._~"), ''))


class ServiceStore:
    def init_services(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT, device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                name TEXT NOT NULL, type TEXT NOT NULL, port INTEGER, url TEXT NOT NULL DEFAULT '',
                expected_codes TEXT NOT NULL DEFAULT '200-299', verify_tls INTEGER NOT NULL DEFAULT 1,
                interval INTEGER NOT NULL, timeout INTEGER NOT NULL, threshold INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'pending',
                failures INTEGER NOT NULL DEFAULT 0, last_checked REAL, last_seen REAL, rtt REAL,
                message TEXT NOT NULL DEFAULT '', status_code INTEGER,
                next_check REAL NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS services_device ON services(device_id);
            CREATE TABLE IF NOT EXISTS service_samples (
                id INTEGER PRIMARY KEY, service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
                time REAL NOT NULL, kind TEXT NOT NULL, rtt REAL, message TEXT NOT NULL, status_code INTEGER);
            CREATE INDEX IF NOT EXISTS service_samples_target ON service_samples(service_id,time);
            CREATE INDEX IF NOT EXISTS service_samples_time ON service_samples(time);
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(services)')}
            if 'legacy_device_id' not in columns:
                db.execute('ALTER TABLE services ADD COLUMN legacy_device_id INTEGER')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS services_legacy_device ON services(legacy_device_id)')

    def save_service(self, data, _db=None):
        from .core import integer
        device_id = integer(data.get('device_id'), 1, 2147483647, 'Gerät')
        kind = data.get('type')
        if kind not in ('ping', 'tcp', 'http'):
            raise ValueError('Ping, HTTP/HTTPS oder TCP als Prüfungsart auswählen.')
        name = str(data.get('name', '')).strip()
        if not name or len(name) > 120:
            raise ValueError('Dienstname: 1 bis 120 Zeichen angeben.')
        port = integer(data.get('port'), 1, 65535, 'TCP-Port') if kind == 'tcp' else None
        url = http_url(data.get('url', '')) if kind == 'http' else ''
        codes = str(data.get('expected_codes', '200-299')).strip() if kind == 'http' else '200-299'
        status_codes(codes)
        verify = integer(data.get('verify_tls', 1), 0, 1, 'Zertifikatsprüfung')
        defaults = self.settings()
        values = (device_id, name, kind, port, url, codes, verify,
                  integer(data.get('interval', defaults['interval']), 5, 86400, 'Prüfintervall'),
                  integer(data.get('timeout', defaults['timeout']), 1, 30, 'Antwortfrist'),
                  integer(data.get('threshold', defaults['threshold']), 1, 20, 'Fehlerschwelle'))
        with self.connect(_db) as db:
            if _db is None: db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM devices WHERE id=?', (device_id,)).fetchone():
                raise ValueError('Das Gerät existiert nicht mehr.')
            if data.get('id'):
                ident = integer(data['id'], 1, 2147483647, 'Dienst')
                old = db.execute('SELECT * FROM services WHERE id=?', (ident,)).fetchone()
                if not old or old['device_id'] != device_id:
                    raise ValueError('Dienst für dieses Gerät nicht gefunden.')
                fields = ('device_id','name','type','port','url','expected_codes','verify_tls','interval','timeout','threshold')
                if tuple(old[k] for k in fields) == values:
                    return ident
                db.execute('UPDATE services SET device_id=?,name=?,type=?,port=?,url=?,expected_codes=?,verify_tls=?,interval=?,timeout=?,threshold=?,revision=revision+1,next_check=0,failures=0,status=\'pending\' WHERE id=?', values + (ident,))
                if (old['type'], old['port'], old['url']) != (kind, port, url):
                    db.execute('DELETE FROM service_samples WHERE service_id=?', (ident,))
                    db.execute("UPDATE services SET last_checked=NULL,last_seen=NULL,rtt=NULL,message='',status_code=NULL WHERE id=?", (ident,))
                return ident
            return db.execute('INSERT INTO services(device_id,name,type,port,url,expected_codes,verify_tls,interval,timeout,threshold) VALUES(?,?,?,?,?,?,?,?,?,?)', values).lastrowid

    def service_action(self, ident, action):
        from .core import integer
        ident = integer(ident, 1, 2147483647, 'Dienst')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(SERVICE_SELECT + ' WHERE s.id=?', (ident,)).fetchone()
            if not row:
                raise ValueError('Dienst nicht gefunden.')
            if action in ('check','resume'):self.require_device_license(row['device_id'],db)
            if action == 'delete':
                self.protect_dependency_source(db, service_id=ident)
                db.execute('DELETE FROM services WHERE id=?', (ident,))
            elif action == 'check':
                if not row['enabled'] or not row['device_enabled']:
                    raise ValueError('Zuerst die Überwachung von Gerät und Dienst starten.')
                db.execute('UPDATE services SET next_check=0 WHERE id=?', (ident,))
            elif action in ('pause', 'resume'):
                db.execute("UPDATE services SET enabled=?,revision=revision+1,next_check=0,status='pending',failures=0 WHERE id=?", (int(action == 'resume'), ident))
            else:
                raise ValueError('Unbekannte Dienstaktion.')

    def record_service(self, service, result):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.refresh_license_access(db)
            current = db.execute(SERVICE_SELECT + ' WHERE s.id=?', (service['id'],)).fetchone()
            if (not current or not current['enabled'] or not current['device_enabled'] or current['device_license_blocked'] or current['device_blocked'] or
                    current['device_block_revision'] != service.get('device_block_revision',0) or current['revision'] != service['revision'] or current['device_revision'] != service['device_revision']):
                return
            failures = current['failures']
            if result['kind'] == 'up':
                failures, status = 0, 'up'
            elif result['kind'] == 'down':
                failures += 1
                status = 'down' if failures >= current['threshold'] else 'warning'
            else:
                status = 'error'
            last_seen = now if status == 'up' else current['last_seen']
            db.execute('UPDATE services SET status=?,failures=?,rtt=?,message=?,last_checked=?,last_seen=?,status_code=?,next_check=? WHERE id=?',
                       (status, failures, result['rtt'], result['message'], now, last_seen, result.get('status_code'), now + current['interval'], service['id']))
            db.execute('INSERT INTO service_samples(service_id,time,kind,rtt,message,status_code) VALUES(?,?,?,?,?,?)',
                       (service['id'], now, result['kind'], result['rtt'], result['message'], result.get('status_code')))
            self.record_notification(db, 'service', current, status, result['message'], now,
                provisional=(status == 'warning' and result['kind'] == 'down'))
            if service['type'] == 'ping' and result.get('ip'):
                db.execute('UPDATE devices SET last_ip=? WHERE id=?', (result['ip'], current['device_id']))
            if current['status'] != status:
                prefix = {'up': 'Dienstprüfung erfolgreich. ', 'down': 'Fehlerschwelle erreicht. ',
                          'warning': 'Dienstprüfung fehlgeschlagen; weitere Prüfung folgt. ', 'error': 'Prüffehler. '}[status]
                db.execute('INSERT INTO events(time,name,kind,message) VALUES(?,?,?,?)',
                           (now, current['device_name'] + ' · ' + current['name'], status, prefix + result['message']))


def check_direct(service):
    started = time.monotonic()
    connection = None
    try:
        if service['type'] == 'tcp':
            with socket.create_connection((service['device_address'], service['port']), timeout=service['timeout']):
                pass
            return {'kind': 'up', 'rtt': (time.monotonic()-started)*1000,
                    'message': 'TCP-Port %s nimmt Verbindungen an.' % service['port'], 'status_code': None}
        parsed = urlsplit(service['url'])
        if parsed.scheme == 'https':
            context = ssl.create_default_context() if service['verify_tls'] else ssl._create_unverified_context()
            connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=service['timeout'], context=context)
        else:
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=service['timeout'])
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        connection.request('GET', path, headers={'User-Agent': 'QisutuMonitoring/1.0.1', 'Connection': 'close', 'Accept': '*/*'})
        response = connection.getresponse()
        ok = response.status in status_codes(service['expected_codes'])
        return {'kind': 'up' if ok else 'down', 'rtt': (time.monotonic()-started)*1000,
                'message': 'HTTP %s · erwartet: %s%s' % (response.status, service['expected_codes'],
                    ' · Zertifikatsprüfung ausgeschaltet' if parsed.scheme == 'https' and not service['verify_tls'] else ''),
                'status_code': response.status}
    except ssl.SSLCertVerificationError:
        message = 'HTTPS-Zertifikat ist nicht vertrauenswürdig, abgelaufen oder passt nicht zum Hostnamen.'
    except ssl.SSLError:
        message = 'TLS-Verbindung konnte nicht aufgebaut werden.'
    except socket.gaierror:
        message = 'Der Zielname konnte nicht aufgelöst werden.'
    except (socket.timeout, TimeoutError):
        message = 'Antwortfrist überschritten.'
    except ConnectionRefusedError:
        message = 'Verbindung vom Ziel abgelehnt.'
    except (OSError, http.client.HTTPException):
        message = 'Netzwerkverbindung fehlgeschlagen oder ungültige HTTP-Antwort.'
    finally:
        if connection:
            connection.close()
    return {'kind': 'down', 'rtt': None, 'message': message, 'status_code': None}


def probe_service(service):
    if service['type'] == 'ping':
        from .core import probe
        result = probe(service['device_address'], service['timeout'])
        if result['kind'] == 'up':
            result['message'] = 'Ping beantwortet.'
        return result
    try:
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
            input=json.dumps(service), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=service['timeout'] + 0.5)
        if completed.returncode != 0:
            raise ValueError('Worker failed')
        return json.loads(completed.stdout)
    except subprocess.TimeoutExpired:
        return {'kind': 'down', 'rtt': None, 'message': 'Antwortfrist überschritten (einschließlich Namensauflösung und Verbindungsaufbau).', 'status_code': None}
    except (OSError, ValueError):
        return {'kind': 'error', 'rtt': None, 'message': 'Dienstprüfung konnte auf dem Monitoring-Server nicht ausgeführt werden.', 'status_code': None}


if __name__ == '__main__' and sys.argv[1:] == ['--worker']:
    print(json.dumps(check_direct(json.load(sys.stdin))))
