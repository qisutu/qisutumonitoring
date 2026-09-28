"""Qisutu Monitoring: persistent state, ICMP checks and bounded background jobs."""
import contextlib
import concurrent.futures
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from .resources import ResourceStore, RESOURCE_SELECT, probe_resources
from .services import ServiceStore, SERVICE_SELECT, probe_service
from .fleet import FleetStore
from .extended import ExtendedStore
from .integrations import IntegrationStore, SELECT as INTEGRATION_SELECT, probe_integration
from .dependencies import DependencyStore
from .connections import ConnectionStore
from .licensing import LicenseStore
from .notifications import NotificationStore, NotificationWorker

VERSION = '1.0.1'
DEFAULTS = {'interval': 30, 'timeout': 2, 'threshold': 3, 'scan_timeout': 1}
LOG = logging.getLogger('netzmonitor')


def timestamp():
    return time.time()


def integer(value, low, high, label):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
        raise ValueError(label + ': Bitte eine ganze Zahl eingeben.')
    number = int(value)
    if not low <= number <= high:
        raise ValueError('%s: Erlaubt sind %s bis %s.' % (label, low, high))
    return number


def address(value):
    value = str(value).strip().rstrip('.').lower()
    try:
        ip = ipaddress.ip_address(value)
        if ip.is_multicast or ip.is_unspecified:
            raise ValueError('Ungeeignete Zieladresse.')
        return str(ip)
    except ValueError:
        if (not value or len(value) > 253 or
                any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p)
                    for p in value.split('.')) or re.fullmatch(r'[\d.]+', value)):
            raise ValueError('Bitte eine gültige IP-Adresse oder einen Hostnamen eingeben.')
        return value


def targets(expression):
    """IPv4 CIDR, single IPv4 address or explicit address range; bounded /16."""
    expression = str(expression).strip()
    try:
        if '-' in expression:
            start, end = (ipaddress.IPv4Address(x.strip()) for x in expression.split('-', 1))
            first, last = int(start), int(end)
        else:
            network = ipaddress.IPv4Network(expression, strict=False)
            first, last = int(network.network_address), int(network.broadcast_address)
            if network.prefixlen < 31:
                first, last = first + 1, last - 1
        count = last - first + 1
        if count < 1 or count > 65536:
            raise ValueError()
        for n in (first, last):
            ip = ipaddress.IPv4Address(n)
            if ip.is_multicast or ip.is_unspecified or ip.is_reserved or n == 0xffffffff:
                raise ValueError()
        return [str(ipaddress.IPv4Address(n)) for n in range(first, last + 1)]
    except (ValueError, TypeError):
        raise ValueError('IPv4-Netz (z. B. CIDR /24), einzelne IPv4-Adresse oder Von-bis-Bereich angeben; maximal 65.536 Adressen je Bereich.')


def probe(host, timeout, executable=None):
    executable = executable or shutil.which('ping')
    if not executable:
        return {'kind': 'error', 'message': 'Das Programm ping fehlt auf dem Monitoring-Server.', 'rtt': None, 'ip': ''}
    try:
        result = subprocess.run([executable, '-n', '-c', '1', '-W', str(math.ceil(timeout)), host],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=timeout + 0.5, env=dict(os.environ, LC_ALL='C', LANG='C'),
                                encoding='utf-8', errors='replace')
        output = result.stdout
        match = re.search(r'time[=<]\s*([\d.]+)\s*ms', output)
        ip_match = re.search(r'^PING\s+\S+\s+\(([^)]+)\)', output)
        resolved = ip_match.group(1) if ip_match else ''
        if result.returncode == 0:
            return {'kind': 'up', 'rtt': float(match.group(1)) if match else None, 'message': '', 'ip': resolved}
        if result.returncode == 1:
            return {'kind': 'down', 'rtt': None, 'message': 'Keine Ping-Antwort innerhalb der Antwortfrist.', 'ip': resolved}
        return {'kind': 'error', 'rtt': None, 'message': output.strip()[-350:] or 'Ping konnte nicht ausgeführt werden.', 'ip': resolved}
    except subprocess.TimeoutExpired:
        return {'kind': 'down', 'rtt': None, 'message': 'Antwortfrist überschritten.', 'ip': ''}
    except OSError as exc:
        return {'kind': 'error', 'rtt': None, 'message': 'Ping-Ausführung fehlgeschlagen: ' + str(exc), 'ip': ''}


def reverse_name(ip):
    # DNS lookups run in a subprocess: a broken resolver must not block discovery.
    try:
        result = subprocess.run([sys.executable, '-c',
            'import socket,sys; print(socket.gethostbyaddr(sys.argv[1])[0])', ip],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1.5,
            encoding='utf-8', errors='replace')
        return result.stdout.strip()[:253] if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


class Store(ServiceStore, ResourceStore, FleetStore, ExtendedStore, IntegrationStore, DependencyStore, ConnectionStore, LicenseStore, NotificationStore):
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'monitoring.sqlite3'
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL UNIQUE,
                interval INTEGER NOT NULL, timeout INTEGER NOT NULL, threshold INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'pending',
                failures INTEGER NOT NULL DEFAULT 0, last_checked REAL, last_seen REAL,
                rtt REAL, message TEXT NOT NULL DEFAULT '', last_ip TEXT NOT NULL DEFAULT '',
                next_check REAL NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                time REAL NOT NULL, kind TEXT NOT NULL, rtt REAL);
            CREATE INDEX IF NOT EXISTS samples_device_time ON samples(device_id,time);
            CREATE INDEX IF NOT EXISTS samples_time ON samples(time);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, time REAL NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ranges (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, expression TEXT NOT NULL,
                every_minutes INTEGER NOT NULL DEFAULT 0, last_scan REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS discoveries (
                ip TEXT PRIMARY KEY, hostname TEXT NOT NULL, rtt REAL, first_seen REAL NOT NULL,
                last_seen REAL NOT NULL, range_id INTEGER);
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY, range_id INTEGER, name TEXT NOT NULL, started REAL NOT NULL,
                finished REAL, status TEXT NOT NULL, total INTEGER NOT NULL,
                checked INTEGER NOT NULL DEFAULT 0, found INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS configuration_receipts (
                request_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                saved INTEGER NOT NULL, created_at REAL NOT NULL);
            ''')
            for key, value in DEFAULTS.items():
                db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, json.dumps(value)))
        os.chmod(self.path, 0o600)
        self.init_services()
        self.init_resources()
        self.init_extended()
        self.init_fleet()
        self.init_dependencies()
        self.init_integrations()
        self.init_connections()
        self.init_license()
        self.migrate_device_pings()
        self.init_notifications()
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM schema_migrations WHERE name='tls-daily-default'").fetchone():
                db.execute("""UPDATE integration_targets SET interval=86400,revision=revision+1,
                    next_check=CASE WHEN last_checked IS NULL THEN 0
                      WHEN failures>0 AND failures<threshold THEN last_checked+60
                      ELSE last_checked+86400 END WHERE kind='tls' AND interval=60""")
                db.execute("INSERT INTO schema_migrations VALUES('tls-daily-default',?)", (timestamp(),))
            if not db.execute("SELECT 1 FROM schema_migrations WHERE name='plain-ping-name'").fetchone():
                db.execute("UPDATE services SET name='Ping',revision=revision+1 WHERE legacy_device_id IS NOT NULL AND name='Ping (übernommen)'")
                db.execute("INSERT INTO schema_migrations VALUES('plain-ping-name',?)", (timestamp(),))

    @contextlib.contextmanager
    def connect(self, connection=None):
        if connection is not None:
            yield connection
            return
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def settings(self):
        return {row['key']: json.loads(row['value']) for row in self.rows('SELECT * FROM settings')}

    def migrate_device_pings(self):
        # A single transaction makes conversion resumable and prevents duplicates.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY,applied_at REAL NOT NULL)')
            if db.execute("SELECT 1 FROM schema_migrations WHERE name='device-pings-to-services'").fetchone():
                return
            db.execute("""INSERT INTO services(device_id,name,type,interval,timeout,threshold,
                enabled,status,failures,last_checked,last_seen,rtt,message,legacy_device_id)
                SELECT id,'Ping','ping',interval,timeout,threshold,
                0,status,failures,last_checked,last_seen,rtt,message,id FROM devices""")
            db.execute("""INSERT INTO service_samples(service_id,time,kind,rtt,message,status_code)
                SELECT s.id,p.time,p.kind,p.rtt,
                    CASE p.kind WHEN 'up' THEN 'Ping beantwortet.' WHEN 'down' THEN 'Keine Ping-Antwort.'
                    ELSE 'Ping-Prüffehler.' END,NULL
                FROM samples p JOIN services s ON s.legacy_device_id=p.device_id""")
            # Values now live in service_samples; the old table stays for schema compatibility.
            db.execute('DELETE FROM samples')
            db.execute("INSERT INTO schema_migrations VALUES('device-pings-to-services',?)", (timestamp(),))

    def save_device(self, data, _db=None):
        host = address(data.get('address', ''))
        name = str(data.get('name', '')).strip() or host
        if len(name) > 120:
            raise ValueError('Der Gerätename darf maximal 120 Zeichen enthalten.')
        try:
            with self.connect(_db) as db:
                if _db is None: db.execute('BEGIN IMMEDIATE')
                if data.get('id'):
                    ident = integer(data['id'], 1, 2147483647, 'Gerät')
                    old = db.execute('SELECT * FROM devices WHERE id=?', (ident,)).fetchone()
                    if not old:
                        raise ValueError('Das Gerät existiert nicht mehr.')
                    if old['name'] == name and old['address'] == host:
                        return ident
                    db.execute('UPDATE devices SET name=?,address=?,revision=revision+1 WHERE id=?', (name, host, ident))
                    if old['address'] != host:
                        db.execute("UPDATE devices SET last_ip='' WHERE id=?", (ident,))
                        db.execute("DELETE FROM service_samples WHERE service_id IN (SELECT id FROM services WHERE device_id=? AND type IN ('tcp','ping'))", (ident,))
                        db.execute("UPDATE services SET revision=revision+1,next_check=0,status='pending',failures=0,rtt=NULL,last_checked=NULL,last_seen=NULL,message='',status_code=NULL WHERE device_id=? AND type IN ('tcp','ping')", (ident,))
                        db.execute('DELETE FROM resource_metrics WHERE target_id IN (SELECT id FROM resource_targets WHERE device_id=?)', (ident,))
                        db.execute('DELETE FROM extended_metrics WHERE target_id IN (SELECT id FROM resource_targets WHERE device_id=?)', (ident,))
                        db.execute('DELETE FROM counter_baselines WHERE target_id IN (SELECT id FROM resource_targets WHERE device_id=?)', (ident,))
                        db.execute("UPDATE resource_targets SET revision=revision+1,next_check=0,status='pending',failures=0,last_checked=NULL,message='' WHERE device_id=?", (ident,))
                    return ident
                # Legacy columns remain in SQLite, but no job is attached to a device.
                self.check_device_capacity(db, 1)
                defaults = self.settings()
                ident = db.execute('INSERT INTO devices(name,address,interval,timeout,threshold) VALUES(?,?,?,?,?)',
                                  (name,host,defaults['interval'],defaults['timeout'],defaults['threshold'])).lastrowid
                self.register_license_devices(db,[ident])
                return ident
        except sqlite3.IntegrityError:
            raise ValueError('Diese Adresse ist bereits als Gerät angelegt.')

    def import_devices(self, ips):
        if not isinstance(ips, list) or not 1 <= len(ips) <= 2048:
            raise ValueError('Bitte 1 bis 2.048 gefundene Geräte auswählen.')
        defaults = self.settings()
        count = 0
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = []
            for ip in dict.fromkeys(ips):
                found = db.execute('SELECT * FROM discoveries WHERE ip=?', (str(ip),)).fetchone()
                if not found:
                    raise ValueError('Eine ausgewählte Adresse wurde nicht gefunden.')
                if db.execute('SELECT 1 FROM devices WHERE address=? OR last_ip=?', (ip, ip)).fetchone():
                    continue
                pending.append((ip, found['hostname']))
            self.check_device_capacity(db, len(pending))
            created=[]
            for ip, hostname in pending:
                created.append(db.execute('INSERT INTO devices(name,address,interval,timeout,threshold) VALUES (?,?,?,?,?)',
                           (hostname or ip, ip, defaults['interval'], defaults['timeout'], defaults['threshold'])).lastrowid)
                count += 1
            if created:self.register_license_devices(db,created)
        return count

    def state(self):
        from .status import summarize
        self.refresh_dependencies()
        now = timestamp()
        devices = self.rows('''SELECT id,name,address,enabled,revision,last_ip,blocked,block_reason,license_blocked,
            (SELECT service_id FROM device_dependencies WHERE device_id=devices.id) AS dependency_service_id
            FROM devices ORDER BY name COLLATE NOCASE,id''')
        services = self.rows(SERVICE_SELECT + ' ORDER BY d.name COLLATE NOCASE,s.name COLLATE NOCASE,s.id')
        resources = self.resource_state()
        integrations = self.integration_state()
        summarize(devices, services, resources, now, integrations)
        from .setup import configuration_token
        for device in devices:
            device['config_token'] = configuration_token(device, [s for s in services if s['device_id']==device['id']], [r for r in resources if r['device_id']==device['id']])
        return {'version': VERSION, 'time': now, 'settings': self.settings(),
                'license': self.license_status(),
                'devices': devices, 'services': services, 'resources': resources, 'integrations': integrations,
                'extended': self.extended_state(), **self.fleet_state(), **self.connection_state(),
                'ranges': self.rows('SELECT * FROM ranges ORDER BY id'),
                'scans': self.rows('SELECT * FROM scans ORDER BY id DESC LIMIT 10'),
                'discoveries': self.rows('SELECT c.*, EXISTS(SELECT 1 FROM devices d WHERE d.address=c.ip OR d.last_ip=c.ip) AS monitored FROM discoveries c ORDER BY c.last_seen DESC, c.ip LIMIT 10000'),
                'events': self.rows('SELECT * FROM events ORDER BY id DESC LIMIT 40')}


class Engine:
    def __init__(self, store, probe_fn=probe, resolver=reverse_name, service_probe=probe_service, resource_probe=probe_resources, integration_probe=probe_integration):
        self.store, self.probe, self.resolver = store, probe_fn, resolver
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.active_services = set()
        self.active_resources = set()
        self.active_integrations = set()
        self.integration_probe = integration_probe
        from .flow import FlowCollector
        self.flow_collector = FlowCollector(store)
        self.notifications = NotificationWorker(store)
        self.integration_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix='integration')
        self.resource_probe = resource_probe
        self.resource_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="resources")
        self.service_probe = service_probe
        self.service_pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix='service')
        self.scan_cancel = threading.Event()
        self.scan_thread = None
        self.scan_running = False
        self.heartbeat = 0
        self.thread = threading.Thread(target=self.loop, name='scheduler', daemon=True)

    def start(self):
        with self.store.connect() as db:
            db.execute("UPDATE scans SET status='interrupted',finished=?,message='Durch Neustart unterbrochen.' WHERE status='running'", (timestamp(),))
            db.execute('UPDATE services SET next_check=0')
            db.execute('UPDATE resource_targets SET next_check=0')
            db.execute("UPDATE integration_targets SET next_check=0 WHERE kind!='tls'")
        self.flow_collector.start()
        self.notifications.start()
        self.thread.start()

    def close(self):
        self.stopping.set()
        self.scan_cancel.set()
        self.flow_collector.close()
        self.notifications.close()
        if self.thread.is_alive():
            self.thread.join(5)
        if self.scan_thread:
            self.scan_thread.join(35)
        self.service_pool.shutdown(wait=True)
        self.resource_pool.shutdown(wait=True)
        self.integration_pool.shutdown(wait=True)

    def check_integration(self, target):
        try:
            if not self.store.license_allows(target['device_id']):return
            self.store.record_integration(target, self.flow_collector.probe(target) if target['kind']=='flow' else self.integration_probe(target))
        except Exception:
            LOG.exception('Zusätzliche Prüfung fehlgeschlagen: %s', target['id'])
        finally:
            with self.lock:
                self.active_integrations.discard(target['id'])

    def check_resource(self, target):
        try:
            if not self.store.license_allows(target['device_id']):return
            self.store.record_resource(target, self.resource_probe(target))
        except Exception:
            LOG.exception('Ressourcenprüfung fehlgeschlagen: %s', target['id'])
        finally:
            with self.lock:
                self.active_resources.discard(target['id'])

    def check_service(self, service):
        try:
            if not self.store.license_allows(service['device_id']):return
            result = self.probe(service['device_address'], service['timeout']) if service['type'] == 'ping' else self.service_probe(service)
            if service['type'] == 'ping' and result['kind'] == 'up':
                result = {**result, 'message': 'Ping beantwortet.'}
            self.store.record_service(service, result)
            self.store.refresh_dependencies()
        except Exception:
            LOG.exception('Dienstprüfung fehlgeschlagen: %s', service['id'])
        finally:
            with self.lock:
                self.active_services.discard(service['id'])

    def loop(self):
        cleaned = 0
        while not self.stopping.is_set():
            try:
                self.heartbeat = timestamp()
                self.store.refresh_dependencies()
                for service in self.store.rows(SERVICE_SELECT + ' WHERE s.enabled=1 AND d.enabled=1 AND d.blocked=0 AND d.license_blocked=0 AND s.next_check<=? ORDER BY s.next_check,s.id LIMIT 32', (timestamp(),)):
                    with self.lock:
                        if service['id'] in self.active_services or len(self.active_services) >= 8:
                            continue
                        self.active_services.add(service['id'])
                    self.service_pool.submit(self.check_service, service)
                for target in self.store.rows(RESOURCE_SELECT + ' WHERE r.enabled=1 AND d.enabled=1 AND d.blocked=0 AND d.license_blocked=0 AND r.next_check<=? ORDER BY r.next_check,r.id LIMIT 16', (timestamp(),)):
                    with self.lock:
                        if target['id'] in self.active_resources or len(self.active_resources) >= 4:
                            continue
                        self.active_resources.add(target['id'])
                    self.resource_pool.submit(self.check_resource, target)
                for target in self.store.rows(INTEGRATION_SELECT + ' WHERE i.enabled=1 AND d.enabled=1 AND d.blocked=0 AND d.license_blocked=0 AND i.next_check<=? ORDER BY i.next_check,i.id LIMIT 16', (timestamp(),)):
                    with self.lock:
                        if target['id'] in self.active_integrations or len(self.active_integrations) >= 4:
                            continue
                        self.active_integrations.add(target['id'])
                    self.integration_pool.submit(self.check_integration, target)
                if not self.scan_running:
                    for row in self.store.rows('SELECT * FROM ranges WHERE every_minutes>0 AND last_scan+every_minutes*60<=? ORDER BY last_scan,id LIMIT 1', (timestamp(),)):
                        try:
                            self.start_scan(row['id'])
                        except ValueError:
                            pass
                if timestamp() - cleaned > 3600:
                    with self.store.connect() as db:
                        cutoff = timestamp() - 30 * 86400
                        db.execute('DELETE FROM samples WHERE time<?', (cutoff,))
                        db.execute('DELETE FROM integration_samples WHERE time<?', (cutoff,))
                        db.execute('DELETE FROM service_samples WHERE time<?', (cutoff,))
                        db.execute('DELETE FROM resource_samples WHERE time<?', (cutoff,))
                        db.execute('DELETE FROM extended_samples WHERE time<?', (cutoff,))
                        db.execute('DELETE FROM events WHERE time<?', (cutoff,))
                        db.execute('DELETE FROM discoveries WHERE last_seen<?', (cutoff,))
                        db.execute("DELETE FROM scans WHERE started<? AND status!='running'", (cutoff,))
                    cleaned = timestamp()
            except Exception:
                LOG.exception('Fehler im Hintergrunddienst')
            self.stopping.wait(0.5)

    def start_scan(self, range_id):
        with self.lock:
            if self.scan_running:
                raise ValueError('Es läuft bereits eine Netzwerksuche. Bitte warten oder die Suche abbrechen.')
            rows = self.store.rows('SELECT * FROM ranges WHERE id=?', (int(range_id),))
            if not rows:
                raise ValueError('Der Netzwerkbereich existiert nicht mehr.')
            row = rows[0]
            hosts = targets(row['expression'])
            with self.store.connect() as db:
                cur = db.execute("INSERT INTO scans(range_id,name,started,status,total) VALUES(?,?,?,'running',?)",
                                 (row['id'], row['name'], timestamp(), len(hosts)))
                scan_id = cur.lastrowid
                db.execute('UPDATE ranges SET last_scan=? WHERE id=?', (timestamp(), row['id']))
            self.scan_running = True
            self.scan_cancel.clear()
            self.scan_thread = threading.Thread(target=self.scan, args=(scan_id, row, hosts), daemon=True, name='discovery')
            self.scan_thread.start()
            return scan_id

    def scan_host(self, ip, timeout):
        if self.stopping.is_set() or self.scan_cancel.is_set():
            return ip, None, ''
        result = self.probe(ip, timeout)
        hostname = self.resolver(ip) if result['kind'] == 'up' else ''
        return ip, result, hostname

    def scan(self, scan_id, row, hosts):
        checked = found = errors = 0
        message = ''
        status = 'finished'
        try:
            # Abort promptly when ping itself is unavailable or not permitted.
            preflight = self.probe('127.0.0.1', 1)
            if preflight['kind'] == 'error':
                raise RuntimeError(preflight['message'])
            timeout = self.store.settings()['scan_timeout']
            with concurrent.futures.ThreadPoolExecutor(max_workers=32, thread_name_prefix='discovery-ping') as pool:
                iterator = iter(hosts)
                futures = set()
                def fill():
                    while len(futures) < 32 and not self.scan_cancel.is_set() and not self.stopping.is_set():
                        try:
                            ip = next(iterator)
                        except StopIteration:
                            break
                        futures.add(pool.submit(self.scan_host, ip, timeout))
                fill()
                while futures:
                    done, futures = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                    with self.store.connect() as db:
                        for future in done:
                            ip, result, hostname = future.result()
                            if result is None:
                                continue
                            checked += 1
                            if result['kind'] == 'up':
                                found += 1
                                now = timestamp()
                                existing = db.execute('SELECT 1 FROM discoveries WHERE ip=?', (ip,)).fetchone()
                                if existing:
                                    db.execute('UPDATE discoveries SET hostname=?,rtt=?,last_seen=?,range_id=? WHERE ip=?', (hostname, result['rtt'], now, row['id'], ip))
                                else:
                                    db.execute('INSERT INTO discoveries VALUES(?,?,?,?,?,?)', (ip, hostname, result['rtt'], now, now, row['id']))
                            elif result['kind'] == 'error':
                                errors += 1
                                message = result['message']
                        db.execute('UPDATE scans SET checked=?,found=?,errors=?,message=? WHERE id=?', (checked, found, errors, message, scan_id))
                    fill()
            if self.scan_cancel.is_set() or self.stopping.is_set():
                status = 'cancelled'
            elif errors:
                status = 'partial'
        except Exception as exc:
            status, message = 'error', str(exc)[:400]
            LOG.exception('Netzwerksuche fehlgeschlagen')
        finally:
            with self.store.connect() as db:
                db.execute('UPDATE scans SET status=?,finished=?,message=? WHERE id=?', (status, timestamp(), message, scan_id))
            with self.lock:
                self.scan_running = False
