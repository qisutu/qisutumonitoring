"""Transactional state-change notifications and persistent per-destination delivery."""
import copy
from datetime import datetime, timezone
import json
import logging
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT = {
    'email': {'enabled': False, 'host': '', 'port': 587, 'security': 'starttls',
              'username': '', 'password': '', 'sender': '', 'recipient': '', 'ca': ''},
    'qisutu': {'enabled': False, 'url': '', 'token': '', 'ca': ''},
    'scope': 'all', 'group_ids': [], 'device_ids': [], 'warnings': True,
    'monitoring_url': '', 'revision': 0,
}
SECRETS = {'email': 'password', 'qisutu': 'token'}
TABLES = {'service': 'services', 'resource': 'resource_targets', 'integration': 'integration_targets'}
LABELS = {'up': 'Wieder in Ordnung', 'down': 'Ausfall', 'critical': 'Kritisch',
          'warning': 'Warnung', 'error': 'Prüffehler', 'unknown': 'Messwerte fehlen'}


def clean(value, name, limit=500):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(name + ': Ungültige Eingabe.')
    return value.strip()


def validate(data, old):
    if not isinstance(data, dict):
        raise ValueError('Ungültige Meldungseinstellungen.')
    cfg = copy.deepcopy(old)
    from .core import integer, address
    for channel in SECRETS:
        incoming = data.get(channel, {})
        if not isinstance(incoming, dict):
            raise ValueError('Ungültige Verbindungseinstellungen.')
        allowed = set(DEFAULT[channel]) | {'clear_secret'}
        if set(incoming) - allowed:
            raise ValueError('Unbekannte Verbindungseinstellung.')
        for key, value in incoming.items():
            if key in (SECRETS[channel], 'clear_secret'):
                continue
            cfg[channel][key] = value
        secret = SECRETS[channel]
        if incoming.get('clear_secret'):
            cfg[channel][secret] = ''
        if incoming.get(secret):
            clean(incoming[secret], 'Zugangsdaten', 4096)
            cfg[channel][secret] = incoming[secret] if channel == 'email' else incoming[secret].strip()
        if not isinstance(cfg[channel]['enabled'], bool):
            raise ValueError('Meldeweg aktivieren oder deaktivieren.')
        ca = cfg[channel]['ca']
        if not isinstance(ca, str) or len(ca) > 65536:
            raise ValueError('Die Zertifikatsdatei ist zu groß.')
        if ca:
            import ssl
            try:
                ssl.create_default_context().load_verify_locations(cadata=ca)
            except (ssl.SSLError, ValueError):
                raise ValueError('Bitte ein gültiges CA-Zertifikat im PEM-Format hochladen.') from None
    e = cfg['email']
    e['host'] = address(e['host']) if e['host'] else ''
    e['port'] = integer(e['port'], 1, 65535, 'Mailserver-Port')
    if e['security'] not in ('starttls', 'tls', 'none'):
        raise ValueError('Bitte STARTTLS, TLS oder unverschlüsseltes internes Relay auswählen.')
    e['username'] = clean(e['username'], 'Benutzername', 255)
    for key in ('sender', 'recipient'):
        e[key] = clean(e[key], 'E-Mail-Adresse', 254)
        if e[key] and not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", e[key]):
            raise ValueError('Bitte eine einzelne gültige Absender- und Empfängeradresse eintragen.')
    if e['enabled'] and not all(e[k] for k in ('host', 'sender', 'recipient')):
        raise ValueError('Für E-Mail bitte Mailserver, Absender und Empfänger eintragen.')
    if e['enabled'] and e['username'] and not e['password']:
        raise ValueError('Für die Anmeldung am Mailserver fehlt das Passwort. Bei einem Relay ohne Anmeldung den Benutzernamen leer lassen.')
    if e['username'] and e['security'] == 'none':
        raise ValueError('Für die Anmeldung am Mailserver bitte TLS oder STARTTLS verwenden.')
    q = cfg['qisutu']
    q['url'] = clean(q['url'], 'Qisutu-Verbindungsadresse', 2048).rstrip('/')
    if q['url']:
        u = urlsplit(q['url'])
        if (u.scheme != 'https' or not u.hostname or u.username is not None or u.password is not None
                or u.query or u.fragment or not re.search(r'/v1/addons/qisutu\.monitoring/events/[0-9a-f]{32}$', u.path)):
            raise ValueError('Die vollständige HTTPS-Verbindungsadresse aus Administration → Monitoring in Qisutu eintragen.')
        try:
            if u.port is not None and not 1 <= u.port <= 65535:
                raise ValueError()
        except ValueError:
            raise ValueError('Qisutu-Verbindungsadresse: Ungültiger Port.') from None
    if q['enabled'] and not all(q[k] for k in ('url', 'token')):
        raise ValueError('Für Qisutu bitte Verbindungsadresse und Zugangsschlüssel eintragen.')
    for key in ('scope', 'group_ids', 'device_ids', 'warnings', 'monitoring_url'):
        if key in data:
            cfg[key] = data[key]
    if cfg['scope'] not in ('all', 'selected'):
        raise ValueError('Bitte den Gerätebereich auswählen.')
    if not isinstance(cfg['warnings'], bool):
        raise ValueError('Warnungen aktivieren oder deaktivieren.')
    for key in ('group_ids', 'device_ids'):
        if not isinstance(cfg[key], list) or len(cfg[key]) > 100000:
            raise ValueError('Ungültige Geräteauswahl.')
        cfg[key] = sorted({integer(v, 1, 2147483647, 'Auswahl') for v in cfg[key]})
    if cfg['scope'] == 'selected' and not (cfg['group_ids'] or cfg['device_ids']):
        raise ValueError('Mindestens eine Gerätegruppe oder ein Gerät auswählen.')
    cfg['monitoring_url'] = clean(cfg['monitoring_url'], 'Monitoring-Adresse', 2048).rstrip('/')
    if cfg['monitoring_url']:
        from .services import http_url
        cfg['monitoring_url'] = http_url(cfg['monitoring_url']).rstrip('/')
    return cfg


def selected(db, cfg, device_id):
    if cfg['scope'] == 'all' or device_id in cfg['device_ids']:
        return True
    groups = cfg['group_ids']
    return bool(groups and db.execute('SELECT 1 FROM group_members WHERE device_id=? AND group_id IN (' +
                ','.join('?' for _ in groups) + ') LIMIT 1', [device_id] + groups).fetchone())


class NotificationStore:
    def init_notifications(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS notification_config(id INTEGER PRIMARY KEY CHECK(id=1),config TEXT NOT NULL,instance TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notification_incidents(channel TEXT NOT NULL,check_key TEXT NOT NULL,
                active INTEGER NOT NULL,status TEXT NOT NULL,started REAL NOT NULL,episode TEXT NOT NULL,
                PRIMARY KEY(channel,check_key));
            CREATE TABLE IF NOT EXISTS notification_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,channel TEXT NOT NULL,
                check_key TEXT NOT NULL,device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0,created REAL NOT NULL,delivered REAL,last_error TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS notification_pending ON notification_outbox(state,next_attempt,id);
            ''')
            db.execute('INSERT OR IGNORE INTO notification_config VALUES(1,?,?)', (json.dumps(DEFAULT), uuid.uuid4().hex))

    def notification_config(self, db):
        return json.loads(db.execute('SELECT config FROM notification_config WHERE id=1').fetchone()[0])

    def notification_state(self):
        with self.connect() as db:
            cfg = self.notification_config(db)
            for channel, secret in SECRETS.items():
                cfg[channel]['has_secret'] = bool(cfg[channel].pop(secret))
            cfg['delivery'] = {}
            for channel in SECRETS:
                cfg['delivery'][channel] = dict(
                    pending=db.execute("SELECT count(*) FROM notification_outbox WHERE channel=? AND state='pending'", (channel,)).fetchone()[0],
                    last_sent=db.execute("SELECT max(delivered) FROM notification_outbox WHERE channel=? AND state='sent'", (channel,)).fetchone()[0],
                    error=(db.execute("SELECT last_error FROM notification_outbox WHERE channel=? AND state='pending' AND last_error!='' ORDER BY id LIMIT 1", (channel,)).fetchone() or [''])[0])
            return cfg

    def save_notifications(self, data):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = self.notification_config(db)
            if data.get('revision') != old['revision']:
                raise ValueError('Die Einstellungen wurden inzwischen geändert. Bitte neu laden.')
            cfg = validate(data, old)
            # A destination/scope change must never forward old queued data to a new recipient.
            scope_changed = any(cfg[k] != old[k] for k in ('scope', 'group_ids', 'device_ids', 'warnings'))
            for channel, fields in {'email': ('host', 'sender', 'recipient'), 'qisutu': ('url',)}.items():
                if scope_changed or cfg[channel]['enabled'] != old[channel]['enabled'] or any(cfg[channel][k] != old[channel][k] for k in fields):
                    db.execute("UPDATE notification_outbox SET state='cancelled' WHERE channel=? AND state='pending'", (channel,))
                    db.execute('DELETE FROM notification_incidents WHERE channel=?', (channel,))
                if cfg[channel] != old[channel]:
                    db.execute("UPDATE notification_outbox SET next_attempt=0,last_error='' WHERE channel=? AND state='pending'", (channel,))
            cfg['revision'] = old['revision'] + 1
            db.execute('UPDATE notification_config SET config=? WHERE id=1', (json.dumps(cfg),))
        return self.notification_state()

    def record_notification(self, db, kind, current, status, message, now, provisional=False, details=''):
        if provisional or status not in LABELS:
            return
        cfg = self.notification_config(db)
        if not any(cfg[c]['enabled'] for c in SECRETS) or not selected(db, cfg, current['device_id']):
            return
        if status == 'warning' and not cfg['warnings']:
            return
        key = kind + ':' + str(current['id'])
        instance = db.execute('SELECT instance FROM notification_config WHERE id=1').fetchone()[0]
        name = dict(current).get('name') or 'Ressourcen'
        for channel in SECRETS:
            if not cfg[channel]['enabled']:
                continue
            old = db.execute('SELECT * FROM notification_incidents WHERE channel=? AND check_key=?', (channel, key)).fetchone()
            active = status != 'up'
            if not active and (not old or not old['active']):
                continue
            if old and old['active'] and active and old['status'] == status:
                continue
            started = old['started'] if old and old['active'] else now
            episode = old['episode'] if old and old['active'] else uuid.uuid4().hex
            payload = dict(schema_version=1,event_id=uuid.uuid4().hex,
                fingerprint=instance + ':' + key, status='problem' if active else 'recovery',
                severity={'down':'critical','critical':'critical','error':'critical','unknown':'warning','warning':'warning','up':'info'}[status],
                host=current['device_name'], service=name,
                summary=LABELS[status] + ': ' + current['device_name'] + ' · ' + name,
                details='Gerät: ' + current['device_name'] + '\nAdresse: ' + current['device_address'] + '\nPrüfung: ' + name +
                    '\nZustand: ' + LABELS[status] + '\n' + message + ('\n' + details if details else '') +
                    '\nBeginn: ' + datetime.fromtimestamp(started, timezone.utc).isoformat(),
                occurred_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                event_url=cfg['monitoring_url'],
                tags={'monitoring':'qisutu','device_id':str(current['device_id']),'check_id':key,'episode':episode})
            db.execute('INSERT INTO notification_outbox(channel,check_key,device_id,payload,created) VALUES(?,?,?,?,?)',
                       (channel,key,current['device_id'],json.dumps(payload,ensure_ascii=False),now))
            db.execute('INSERT INTO notification_incidents VALUES(?,?,?,?,?,?) ON CONFLICT(channel,check_key) DO UPDATE SET active=excluded.active,status=excluded.status,started=excluded.started,episode=excluded.episode',
                       (channel,key,int(active),status,started,episode))

    def notification_test(self, data):
        channel = data.get('channel')
        if channel not in SECRETS:
            raise ValueError('E-Mail oder Qisutu auswählen.')
        with self.connect() as db:
            cfg = validate(data.get('config', {}), self.notification_config(db))
        temporary = copy.deepcopy(cfg)
        temporary[channel]['enabled'] = True
        cfg = validate(temporary, cfg)
        result = transport(channel, cfg[channel], test=True)
        if not result['ok']:
            raise ValueError(result['message'])
        return result


def transport(channel, config, payload=None, test=False):
    try:
        result = subprocess.run([sys.executable, '-m', 'netzmonitor.notification_transport'],
            input=json.dumps(dict(channel=channel,config=config,payload=payload,test=test)),
            text=True, encoding='utf-8', capture_output=True, timeout=25,
            cwd=str(Path(__file__).resolve().parents[1]))
        response = json.loads(result.stdout) if result.returncode == 0 else {}
        if not isinstance(response, dict) or not isinstance(response.get('ok'), bool):
            raise ValueError()
        return response
    except subprocess.TimeoutExpired:
        return dict(ok=False,message='Verbindungszeit überschritten. Serveradresse und Firewall prüfen.')
    except (OSError, ValueError):
        return dict(ok=False,message='Der Versand konnte nicht ausgeführt werden. Serverprotokoll und Installation prüfen.')


class NotificationWorker:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.loop, name='meldungen', daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(27)

    def deliver_one(self, channel, send=transport):
        # Configuration mutations use this lock too, so a completed "disable" stops new sends.
        with self.lock:
            with self.store.connect() as db:
                cfg = self.store.notification_config(db)
                if not cfg[channel]['enabled']:
                    return False
                row = db.execute("SELECT * FROM notification_outbox WHERE channel=? AND state='pending' AND next_attempt<=? AND NOT EXISTS (SELECT 1 FROM notification_outbox previous WHERE previous.channel=notification_outbox.channel AND previous.check_key=notification_outbox.check_key AND previous.state='pending' AND previous.id<notification_outbox.id) ORDER BY id LIMIT 1", (channel,time.time())).fetchone()
                if not row:
                    return False
                kind, ident = row['check_key'].split(':')
                exists = db.execute('SELECT 1 FROM ' + TABLES[kind] + ' WHERE id=? AND device_id=?', (int(ident),row['device_id'])).fetchone()
                if not exists or not selected(db,cfg,row['device_id']):
                    db.execute("UPDATE notification_outbox SET state='cancelled' WHERE id=?", (row['id'],))
                    return True
                # Already queued events remain historical facts even if a device is later paused.
                payload = json.loads(row['payload'])
            result = send(channel,cfg[channel],payload)
            with self.store.connect() as db:
                if result['ok']:
                    db.execute("UPDATE notification_outbox SET state='sent',delivered=?,last_error='' WHERE id=?", (time.time(),row['id']))
                else:
                    delay = min(900, 15 * 2 ** min(row['attempts'],6))
                    db.execute('UPDATE notification_outbox SET attempts=attempts+1,next_attempt=?,last_error=? WHERE id=?',
                               (time.time()+delay,result['message'][:500],row['id']))
            return True

    def loop(self):
        cleaned = 0
        while not self.stop.is_set():
            activity = False
            try:
                for channel in SECRETS:
                    if not self.stop.is_set():
                        activity = self.deliver_one(channel) or activity
                if time.time() - cleaned > 3600:
                    with self.store.connect() as db:
                        db.execute("DELETE FROM notification_outbox WHERE state!='pending' AND created<?", (time.time()-30*86400,))
                    cleaned = time.time()
            except Exception:
                logging.getLogger('netzmonitor').exception('Meldungsversand fehlgeschlagen')
            self.stop.wait(0.1 if activity else 2)
