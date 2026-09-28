"""Optional integrations: configuration, persistence, histories and bounded workers."""
import json
import math
from pathlib import Path
from .advanced_config import SCHEMAS, SECRET_FIELDS, validate_advanced
import subprocess
import sys
import time

KINDS = {'tls': 'TLS-Zertifikat', 'dns': 'DNS', 'smtp': 'SMTP', 'imap': 'IMAP', 'pop3': 'POP3',
         'windows': 'Windows', 'hyperv': 'Hyper-V', 'vmware': 'VMware', 'redfish': 'iLO / iDRAC / Redfish',
         'synology': 'Synology NAS', 'ups': 'USV (UPS-MIB)', 'database': 'Datenbank', 'printer': 'Drucker',
         'flow': 'Datenverkehr nach Verursacher', 'quality': 'Netzwerkqualität'}
KINDS.update({key: row['label'] for key,row in SCHEMAS.items()})
DEFAULT_INTERVALS = {'tls': 86400, 'database': 60, 'printer': 300, 'flow': 60, 'quality': 60}
SECRETS = ('password', 'community', 'auth_password', 'priv_password') + SECRET_FIELDS
SELECT = '''SELECT i.*,d.name AS device_name,d.address AS device_address,d.enabled AS device_enabled,
            d.revision AS device_revision,d.blocked AS device_blocked,d.license_blocked AS device_license_blocked,d.block_revision AS device_block_revision FROM integration_targets i
            JOIN devices d ON d.id=i.device_id'''


def string(value, name, limit=255):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(name + ': ungültige Zeichen oder zu lang.')
    return value.strip()


def names(value, label):
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError(label + ': höchstens 500 Einträge.')
    return list(dict.fromkeys(string(n, label, 200) for n in value if n))


def validate(kind, value, old=None):
    from .core import integer, address
    if kind not in KINDS or not isinstance(value, dict):
        raise ValueError('Unbekannte Prüfungsart.')
    old = old or {}
    if kind in SCHEMAS:
        return validate_advanced(kind, value, old)
    common = {'host', 'port', 'fingerprint', 'username', 'password'}
    extras = {'tls': {'warn_days', 'critical_days', 'server_name'},
              'dns': {'query', 'record_type', 'expected'},
              'smtp': {'security'}, 'imap': {'security'}, 'pop3': {'security'},
              'windows': {'basic', 'services', 'event_errors', 'event_minutes', 'disk_io', 'network', 'process_monitoring', 'processes', 'performance_counters', 'event_channels', 'event_ids', 'event_source', 'event_text', 'cpu_warn', 'cpu_crit', 'ram_warn', 'ram_crit', 'disk_warn', 'disk_crit'},
              'hyperv': {'expected_running'},
              'vmware': {'hosts', 'vms', 'datastores', 'expected_running', 'performance', 'performance_limit', 'events', 'event_minutes', 'cpu_warn', 'cpu_crit', 'ram_warn', 'ram_crit', 'disk_warn', 'disk_crit'},
              'redfish': {'system', 'thermal', 'power', 'storage'},
              'synology': {'version', 'community', 'auth_password', 'priv_password', 'auth_protocol', 'priv_protocol'},
              'database': {'engine', 'database', 'security', 'connections_warn', 'connections_crit', 'replication', 'replication_warn', 'replication_crit'},
              'quality': {'packets', 'loss_warn', 'loss_crit', 'latency_warn', 'latency_crit', 'jitter_warn', 'jitter_crit'},
              'flow': {'window_minutes'},
              'printer': {'version', 'community', 'auth_password', 'priv_password', 'auth_protocol', 'priv_protocol', 'supply_warn', 'supply_crit'},
              'ups': {'version', 'community', 'auth_password', 'priv_password', 'auth_protocol', 'priv_protocol'}}
    if set(value) - common - extras[kind]:
        raise ValueError('Unbekannte Einstellung für ' + KINDS[kind] + '.')
    cfg = dict(value)
    for key in SECRETS:
        if key in common | extras[kind]:
            secret = cfg.get(key) or old.get(key, '')
            if not isinstance(secret, str) or len(secret) > 1024 or '\x00' in secret or '\r' in secret or '\n' in secret:
                raise ValueError('Ungültiges Passwort oder SNMP-Geheimnis.')
            cfg[key] = secret
    cfg['host'] = address(string(cfg.get('host', ''), 'Serveradresse'))
    default_port = {'tls':443,'dns':53,'smtp':587,'imap':993,'pop3':995,'windows':5986,'hyperv':5986,
                    'vmware':443,'redfish':443,'synology':161,'ups':161,'printer':161,'quality':1,'flow':2055,
                    'database':5432 if cfg.get('engine')=='postgresql' else 3306}[kind]
    cfg['port'] = integer(cfg.get('port', default_port), 1, 65535, 'Port')
    cfg['username'] = string(cfg.get('username', ''), 'Benutzername')
    if ':' in cfg['username']:
        raise ValueError('Benutzername darf keinen Doppelpunkt enthalten.')
    pin = string(cfg.get('fingerprint', ''), 'Fingerabdruck').replace(':', '').replace(' ', '').lower()
    if pin and (len(pin) != 64 or any(c not in '0123456789abcdef' for c in pin)):
        raise ValueError('SHA-256-Fingerabdruck mit 64 Hexadezimalstellen angeben.')
    if old and pin and (old.get('host'), old.get('port')) != (cfg['host'], cfg['port']) and pin == old.get('fingerprint'):
        raise ValueError('Für die neue Adresse das Server-Zertifikat erneut bestätigen.')
    cfg['fingerprint'] = pin
    def flag(key, default=True):
        val = cfg.get(key, default)
        if not isinstance(val, bool): raise ValueError('Ungültige Auswahl: ' + key)
        cfg[key] = val
    if kind in ('windows', 'hyperv', 'vmware', 'redfish'):
        if not cfg['username'] or not cfg['password']:
            raise ValueError('Benutzername und Passwort mit Leserechten angeben.')
    if kind == 'tls':
        cfg['warn_days'] = integer(cfg.get('warn_days', 30), 1, 3650, 'Zertifikatswarnung')
        cfg['critical_days'] = integer(cfg.get('critical_days', 7), 0, 3650, 'Kritischer Zertifikatsablauf')
        if cfg['critical_days'] >= cfg['warn_days']: raise ValueError('Kritische Restlaufzeit muss kleiner als die Warnzeit sein.')
        cfg['server_name'] = address(cfg['server_name']) if cfg.get('server_name') else ''
    if kind == 'dns':
        from .check_protocols import DNS_TYPES
        query = string(cfg.get('query', ''), 'DNS-Name').rstrip('.')
        try: query = query.encode('idna').decode('ascii')
        except UnicodeError: raise ValueError('Ungültiger DNS-Name.')
        if not query or len(query) > 253 or any(not p or len(p) > 63 or not all(c.isalnum() or c in '-_' for c in p) for p in query.split('.')):
            raise ValueError('Einen gültigen DNS-Namen angeben.')
        cfg['query'] = query
        cfg['record_type'] = cfg.get('record_type', 'A')
        if cfg['record_type'] not in DNS_TYPES: raise ValueError('Ungültiger DNS-Eintragstyp.')
        cfg['expected'] = string(cfg.get('expected', ''), 'Erwartete DNS-Antwort', 1024)
        if cfg['expected'] and cfg['record_type'] in ('A', 'AAAA'):
            import ipaddress
            try:
                ip = ipaddress.ip_address(cfg['expected'])
                if ip.version != (4 if cfg['record_type'] == 'A' else 6): raise ValueError()
                cfg['expected'] = str(ip)
            except ValueError: raise ValueError('Erwartete Antwort muss zur gewählten IP-Version passen.')
    if kind in ('smtp', 'imap', 'pop3'):
        cfg['security'] = cfg.get('security', 'starttls' if kind == 'smtp' else 'tls')
        if cfg['security'] not in ('tls', 'starttls', 'plain'): raise ValueError('Ungültige Mail-Verschlüsselung.')
        if cfg['username'] and not cfg['password']: raise ValueError('Passwort für die Mail-Anmeldung angeben.')
        if cfg['username'] and cfg['security'] == 'plain': raise ValueError('Eine Anmeldung benötigt TLS oder STARTTLS.')
        if not cfg['username']: cfg['password'] = ''
    if kind in ('windows', 'vmware'):
        for stem in ('cpu', 'ram', 'disk'):
            cfg[stem+'_warn'] = integer(cfg.get(stem+'_warn', 80), 1, 100, 'Warngrenze')
            cfg[stem+'_crit'] = integer(cfg.get(stem+'_crit', 95), 1, 100, 'Kritische Grenze')
            if cfg[stem+'_warn'] >= cfg[stem+'_crit']: raise ValueError('Warnwert muss kleiner als kritischer Wert sein.')
    if kind == 'windows':
        from .windows_extended import validate_windows
        validate_windows(cfg)
        flag('basic'); flag('event_errors', False)
        cfg['services'] = names(cfg.get('services', []), 'Windows-Dienste')
        if any("'" in n or '\\' in n for n in cfg['services']): raise ValueError('Ungültiger interner Windows-Dienstname.')
        cfg['event_minutes'] = integer(cfg.get('event_minutes', 15), 1, 1440, 'Ereigniszeitraum')
        if not any(cfg[k] for k in ('basic','services','event_errors','disk_io','network','process_monitoring','performance_counters')): raise ValueError('Mindestens einen Windows-Bereich auswählen.')
    if kind in ('hyperv', 'vmware'):
        cfg['expected_running'] = names(cfg.get('expected_running', []), 'Dauerhaft laufende VMs')
    if kind == 'vmware':
        flag('performance',False);flag('events',False)
        cfg['performance_limit']=integer(cfg.get('performance_limit',50),1,200,'VMware-Leistungsgrenze')
        cfg['event_minutes']=integer(cfg.get('event_minutes',15),1,1440,'Ereigniszeitraum')
        for key in ('hosts', 'vms', 'datastores'): flag(key)
        if not any(cfg[k] for k in ('hosts', 'vms', 'datastores')): raise ValueError('Mindestens einen VMware-Bereich wählen.')
        if cfg['expected_running'] and not cfg['vms']: raise ValueError('Für erwartete VMs die VM-Überwachung aktivieren.')
    if kind == 'redfish':
        for key in ('system', 'thermal', 'power', 'storage'): flag(key)
        if not any(cfg[k] for k in ('system', 'thermal', 'power', 'storage')): raise ValueError('Mindestens einen Hardwarebereich wählen.')
    if kind in ('synology', 'ups', 'printer'):
        from .resources import validate_config
        version = cfg.get('version', old.get('version', 'auto' if kind=='printer' else '3'))
        if kind=='printer':
            if version not in ('auto','1','2c','3'): raise ValueError('Eine der angebotenen Drucker-Zugriffsarten wählen.')
            if version!='3': cfg['community'] = cfg.get('community') or 'public'
            elif not cfg['username'] or not cfg['auth_password'] or not cfg['priv_password']:
                raise ValueError('Verschlüsselter Zugriff wurde gewählt. Dafür muss am Drucker ein SNMPv3-Benutzer eingerichtet sein. Falls das nicht der Fall ist, „Automatisch“ wählen.')
        snmp = validate_config({**cfg, 'method':'snmp', 'version':'2c' if kind=='printer' and version in ('auto','1') else version}, {**old, 'method':'snmp'} if old else None)
        snmp['version'] = version
        cfg = {k:snmp[k] for k in (extras[kind] - {'supply_warn', 'supply_crit'}) | {'username', 'port'}} | {'host':cfg['host']}
    if kind == 'printer':
        cfg['supply_warn'] = integer(value.get('supply_warn', 20), 1, 99, 'Verbrauchsmaterial-Warnung')
        cfg['supply_crit'] = integer(value.get('supply_crit', 5), 0, 98, 'Verbrauchsmaterial kritisch')
        if cfg['supply_crit'] >= cfg['supply_warn']: raise ValueError('Kritischer Restbestand muss kleiner als die Warngrenze sein.')
    if kind == 'database':
        flag('replication', False)
        cfg['replication_warn'] = integer(cfg.get('replication_warn',30),1,86400,'Replikationswarnung')
        cfg['replication_crit'] = integer(cfg.get('replication_crit',120),2,86400,'Replikation kritisch')
        if cfg['replication_warn'] >= cfg['replication_crit']: raise ValueError('Warnwert muss kleiner als kritischer Wert sein.')
        cfg['engine'] = cfg.get('engine', 'mysql')
        if cfg['engine'] not in ('mysql', 'postgresql'): raise ValueError('MariaDB/MySQL oder PostgreSQL auswählen.')
        cfg['database'] = string(cfg.get('database', 'postgres' if cfg['engine']=='postgresql' else ''), 'Datenbankname', 128)
        if any(c in cfg['database'] for c in '=:/\\') or cfg['database'].startswith('-'):
            raise ValueError('Bitte einen Datenbanknamen ohne Verbindungsparameter angeben.')
        if cfg['engine']=='postgresql' and not cfg['database']: raise ValueError('Datenbankname angeben.')
        cfg['security'] = cfg.get('security', 'verify')
        if cfg['security'] not in ('verify', 'plain'): raise ValueError('Ungültige Datenbankverschlüsselung.')
        if not cfg['username'] or not cfg['password']: raise ValueError('Datenbankbenutzer und Passwort angeben.')
        cfg['connections_warn'] = integer(cfg.get('connections_warn',80),1,99,'Verbindungswarnung')
        cfg['connections_crit'] = integer(cfg.get('connections_crit',95),2,100,'Verbindungen kritisch')
        if cfg['connections_warn'] >= cfg['connections_crit']: raise ValueError('Warnwert muss kleiner als kritischer Wert sein.')
    if kind == 'quality':
        cfg['packets'] = integer(cfg.get('packets',10),3,20,'Anzahl Testpakete')
        for stem,limits,defaults in [('loss',(1,100),(10,30)),('latency',(1,60000),(100,300)),('jitter',(1,60000),(30,100))]:
            cfg[stem+'_warn'] = integer(cfg.get(stem+'_warn',defaults[0]),*limits,'Warngrenze')
            cfg[stem+'_crit'] = integer(cfg.get(stem+'_crit',defaults[1]),*limits,'Kritische Grenze')
            if cfg[stem+'_warn'] >= cfg[stem+'_crit']: raise ValueError('Warnwert muss kleiner als kritischer Wert sein.')
    if kind == 'flow':
        import ipaddress
        try: cfg['host'] = str(ipaddress.ip_address(cfg['host']))
        except ValueError: raise ValueError('Die Quell-IP des exportierenden Routers/Switches eintragen (kein Hostname).')
        cfg['port'] = integer(cfg['port'],1024,65535,'Lokaler UDP-Empfangsport')
        cfg['window_minutes'] = integer(cfg.get('window_minutes',5),1,60,'Auswertungszeitraum')
    return cfg


def active_metric(kind,cfg,key):
    if kind=='windows':
        if key.startswith('diskio:') or key=='missing:Windows-Festplattenleistung': return cfg.get('disk_io',False)
        if key.startswith('winnet:') or key=='missing:Windows-Netzwerk': return cfg.get('network',False)
        if key.startswith('process:'):
            selected={n.lower()[:-4] if n.lower().endswith('.exe') else n.lower() for n in cfg.get('processes',[])}
            return cfg.get('process_monitoring',False) and (not selected or key.split(':')[1].lower() in selected)
        if key=='missing:Windows-Prozesse': return cfg.get('process_monitoring',False)
        if key.startswith('counter:'): return key.split(':')[1]+'.'+key.rsplit(':',1)[-1] in cfg.get('performance_counters',[])
        if key.startswith('missing:Win32_PerfFormattedData_'):return key[8:] in cfg.get('performance_counters',[])
        if key.startswith(('cpu','ram','disk:')) or key in ('missing:CPU','missing:Arbeitsspeicher','missing:Laufwerke'): return cfg['basic']
        if key.startswith('service:'): return key[8:] in cfg['services']
        if key=='missing:Windows-Dienste': return bool(cfg['services'])
        if key.startswith('events:'): return cfg['event_errors'] and key[7:] in cfg.get('event_channels',['System','Application'])
        if key=='missing:Ereignisprotokolle': return cfg['event_errors']
    if kind=='redfish':
        return cfg.get(key.split(':',1)[0],True)
    if kind=='vmware':
        if key.startswith('perf:') or key.startswith('missing:perf:') or key=='missing:performance': return cfg.get('performance',False)
        if key=='vmware:events' or key=='missing:events': return cfg.get('events',False)
        for prefix,flag in [('HostSystem:','hosts'),('VirtualMachine:','vms'),('Datastore:','datastores')]:
            if key.startswith(prefix): return cfg[flag]
    if key.startswith('missing-vm:'): return key[11:] in cfg.get('expected_running',[])
    return True


class IntegrationStore:
    def init_integrations(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS integration_targets(
              id INTEGER PRIMARY KEY AUTOINCREMENT,device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
              name TEXT NOT NULL,kind TEXT NOT NULL,config TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,
              interval INTEGER NOT NULL DEFAULT 60,timeout INTEGER NOT NULL DEFAULT 30,threshold INTEGER NOT NULL DEFAULT 3,
              revision INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',message TEXT NOT NULL DEFAULT '',
              failures INTEGER NOT NULL DEFAULT 0,last_checked REAL,next_check REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS integration_counter_baselines(target_id INTEGER NOT NULL REFERENCES integration_targets(id) ON DELETE CASCADE,metric_key TEXT NOT NULL,time REAL NOT NULL,value REAL NOT NULL,epoch TEXT NOT NULL,PRIMARY KEY(target_id,metric_key));
            CREATE TABLE IF NOT EXISTS integration_metrics(
              id INTEGER PRIMARY KEY AUTOINCREMENT,target_id INTEGER NOT NULL REFERENCES integration_targets(id) ON DELETE CASCADE,
              metric_key TEXT NOT NULL,label TEXT NOT NULL,value REAL,unit TEXT NOT NULL,status TEXT NOT NULL,
              message TEXT NOT NULL,warn REAL,critical REAL,low INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,UNIQUE(target_id,metric_key));
            CREATE TABLE IF NOT EXISTS integration_samples(
              id INTEGER PRIMARY KEY,metric_id INTEGER NOT NULL REFERENCES integration_metrics(id) ON DELETE CASCADE,
              time REAL NOT NULL,value REAL,status TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS integration_history ON integration_samples(metric_id,time);
            CREATE INDEX IF NOT EXISTS integration_sample_time ON integration_samples(time);
            CREATE INDEX IF NOT EXISTS integration_device ON integration_targets(device_id);
            ''')

    def integration_state(self):
        rows = self.rows(SELECT + ' ORDER BY i.id')
        grouped = {}
        for m in self.rows('SELECT * FROM integration_metrics WHERE active=1 ORDER BY label,id'):
            grouped.setdefault(m['target_id'], []).append(m)
        for row in rows:
            cfg = json.loads(row['config'])
            row['saved_credentials'] = [key for key in SECRETS if cfg.get(key)]
            row['has_password'] = bool(cfg.get('password'))
            row['has_community'] = bool(cfg.get('community'))
            for key in SECRETS:
                if key in cfg: cfg[key] = ''
            row['config'] = cfg
            row['metrics'] = grouped.get(row['id'], [])
            row['type'] = row['kind']
        return rows

    def integration_value(self, data, device, old=None):
        from .core import integer
        kind = data.get('kind')
        if old and kind != old['kind']: raise ValueError('Zum Ändern der Prüfungsart eine neue Prüfung anlegen.')
        cfg = dict(data.get('config') or {})
        cfg['host'] = cfg.get('host') or device['address']
        cfg = validate(kind, cfg, json.loads(old['config']) if old else None)
        name = string(data.get('name') or KINDS[kind], 'Bezeichnung', 120)
        return dict(device_id=device['id'], name=name, kind=kind, config=json.dumps(cfg, sort_keys=True, ensure_ascii=False),
                    enabled=integer(data.get('enabled',1),0,1,'Aktivierung'),
                    interval=integer(data.get('interval',DEFAULT_INTERVALS.get(kind,60)),15,86400,'Prüfintervall'),
                    timeout=integer(data.get('timeout',90 if kind=='flow' else 30),3,90,'Antwortfrist'),
                    threshold=integer(data.get('threshold',3),1,20,'Fehlerschwelle'))

    def save_integrations(self, db, device, values):
        if not isinstance(values, list) or len(values)>100: raise ValueError('Höchstens 100 zusätzliche Prüfungen je Gerät.')
        existing = {r['id']: r for r in db.execute('SELECT * FROM integration_targets WHERE device_id=?',(device['id'],))}
        retained = set(); changed = False; saved_order = []
        for item in values:
            if not isinstance(item, dict): raise ValueError('Ungültige zusätzliche Prüfung.')
            ident = item.get('id')
            if ident and (ident not in existing or ident in retained): raise ValueError('Prüfung gehört nicht zu diesem Gerät oder ist doppelt.')
            old = existing.get(ident)
            v = self.integration_value(item, device, old)
            if old:
                if any(old[k] != val for k,val in v.items()):
                    changed = True
                    previous = json.loads(old['config']); current = json.loads(v['config'])
                    # A different endpoint/question is a new measurement series; threshold changes preserve it.
                    identity_fields = ('host','port','query','record_type','server_name','username','engine','database','window_minutes','expression','sources','command','resource_id','subscription_id','namespace')
                    if any(previous.get(k)!=current.get(k) for k in identity_fields):
                        db.execute('DELETE FROM integration_metrics WHERE target_id=?',(ident,))
                        db.execute('DELETE FROM integration_counter_baselines WHERE target_id=?',(ident,))
                    if v['kind'] in SCHEMAS and previous!=current:
                        db.execute('UPDATE integration_metrics SET active=0 WHERE target_id=?',(ident,))
                        db.execute('DELETE FROM integration_counter_baselines WHERE target_id=?',(ident,))
                    db.execute('UPDATE integration_targets SET '+','.join(k+'=?' for k in v)+
                               ",revision=revision+1,status='pending',failures=0,next_check=0 WHERE id=?",tuple(v.values())+(ident,))
            else:
                changed = True
                ident = db.execute('INSERT INTO integration_targets('+','.join(v)+') VALUES('+','.join('?' for _ in v)+')',tuple(v.values())).lastrowid
            for row in db.execute('SELECT id,metric_key FROM integration_metrics WHERE target_id=?',(ident,)):
                if not active_metric(v['kind'],json.loads(v['config']),row['metric_key']):
                    db.execute('UPDATE integration_metrics SET active=0 WHERE id=?',(row['id'],))
            retained.add(ident); saved_order.append(ident)
        for ident in existing.keys()-retained:
            db.execute('DELETE FROM integration_targets WHERE id=?',(ident,))
        flow_configs=[json.loads(r['config']) for r in db.execute("SELECT config FROM integration_targets WHERE kind='flow' AND enabled=1")]
        if len(flow_configs)>64 or len({(c['port'],':' in c['host']) for c in flow_configs})>16:
            raise ValueError('Maximal 64 aktive Flussexporter und 16 UDP-Empfangsports einrichten.')
        if changed or existing.keys()!=retained:
            db.execute('UPDATE devices SET revision=revision+1 WHERE id=?',(device['id'],))
        return saved_order

    def record_integration(self, target, result, _db=None, _time=None):
        now=time.time() if _time is None else _time
        with self.connect(_db) as db:
            if _db is None: db.execute('BEGIN IMMEDIATE')
            self.refresh_license_access(db)
            current=db.execute(SELECT+' WHERE i.id=?',(target['id'],)).fetchone()
            if not current or not current['enabled'] or not current['device_enabled'] or current['device_license_blocked'] or current['device_blocked'] or current['device_block_revision']!=target.get('device_block_revision',0) or current['revision']!=target['revision'] or current['device_revision']!=target['device_revision']:
                return
            if current['last_checked'] is not None and now < current['last_checked']:
                return
            if current['kind']=='flow':
                db.execute('UPDATE integration_metrics SET active=0 WHERE target_id=?',(target['id'],))
            old={r['metric_key']:r for r in db.execute('SELECT * FROM integration_metrics WHERE target_id=? AND active=1',(target['id'],))}
            metrics=result.get('metrics',[])
            failures=0 if result['kind']=='ok' else current['failures']+1
            if not metrics:
                from .integration_common import metric
                metrics=[metric('availability','Abfrage',None,status='unknown',message=result.get('message','Keine Messwerte geliefert.'))]
            seen={m['key'] for m in metrics}
            if current['kind']=='printer' and result['kind']=='ok':
                for key,row in list(old.items()):
                    if key.startswith('alert:') and key not in seen:
                        db.execute('UPDATE integration_metrics SET active=0 WHERE id=?',(row['id'],));del old[key]
            for key,row in old.items():
                if key not in seen and key!='availability' and not key.startswith(('missing:','missing-vm:')) and not key.endswith(':missing') and key!='inventory':
                    metrics.append(dict(key=key,label=row['label'],value=None,unit=row['unit'],status='unknown',
                        message='Messwert wird nicht mehr geliefert.',warn=row['warn'],critical=row['critical'],low=row['low']))
            for key,row in old.items():
                if key not in seen and (key.startswith(('missing:','missing-vm:')) or key.endswith(':missing') or key=='inventory'):
                    db.execute('UPDATE integration_metrics SET active=0 WHERE id=?',(row['id'],))
            if result['kind']=='ok' and 'availability' in old and 'availability' not in seen:
                db.execute('DELETE FROM integration_metrics WHERE id=?',(old['availability']['id'],))
            rank={'up':0,'warning':1,'unknown':2,'critical':3}
            for m in metrics:
                if m.get('counter') and m.get('value') is not None:
                    from .integration_common import metric as make_metric
                    raw=m['value'];epoch=str(m.get('counter_epoch',''))
                    prior=db.execute('SELECT * FROM integration_counter_baselines WHERE target_id=? AND metric_key=?',(target['id'],m['key'])).fetchone()
                    value=None
                    if prior and epoch==prior['epoch'] and 0<now-prior['time']<=max(current['interval']*3,120) and raw>=prior['value']:
                        value=(raw-prior['value'])/(now-prior['time'])
                    db.execute('INSERT INTO integration_counter_baselines VALUES(?,?,?,?,?) ON CONFLICT(target_id,metric_key) DO UPDATE SET time=excluded.time,value=excluded.value,epoch=excluded.epoch',(target['id'],m['key'],now,raw,epoch))
                    m.update(make_metric(m['key'],m['label'],value,m['unit'],warn=m.get('warn'),critical=m.get('critical'),message='' if value is not None else 'Warte auf eine zweite gültige Zählermessung.'))
                v=m['value']
                if v is not None and (not isinstance(v,(int,float)) or not math.isfinite(v)): m['value']=None;m['status']='unknown'
                vals=(target['id'],m['key'],m['label'],m['value'],m['unit'],m['status'],m.get('message',''),m.get('warn'),m.get('critical'),int(bool(m.get('low'))))
                db.execute('''INSERT INTO integration_metrics(target_id,metric_key,label,value,unit,status,message,warn,critical,low)
                  VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(target_id,metric_key) DO UPDATE SET active=1,label=excluded.label,value=excluded.value,
                  unit=excluded.unit,status=excluded.status,message=excluded.message,warn=excluded.warn,critical=excluded.critical,low=excluded.low''',vals)
                mid=db.execute('SELECT id FROM integration_metrics WHERE target_id=? AND metric_key=?',(target['id'],m['key'])).fetchone()[0]
                db.execute('INSERT INTO integration_samples(metric_id,time,value,status) VALUES(?,?,?,?)',(mid,now,m['value'],m['status']))
            if current['kind']=='flow':
                db.execute('DELETE FROM integration_metrics WHERE target_id=? AND active=0 AND id NOT IN (SELECT id FROM integration_metrics WHERE target_id=? ORDER BY id DESC LIMIT 1000)',(target['id'],target['id']))
            cause=max(metrics,key=lambda m:rank.get(m['status'],2))
            status=cause['status'] if result['kind']=='ok' else ('error' if failures>=current['threshold'] else 'warning')
            message=result.get('message') or (cause['label']+': '+(cause.get('message') or {'up':'OK','warning':'Warngrenze erreicht','critical':'Kritischer Zustand','unknown':'Keine Messwerte'}.get(status,status)))
            if result['kind']=='ok' and status=='up': message='%s Messwerte erfolgreich geprüft.' % len(metrics)
            # Confirm transport failures promptly, even for daily certificate checks.
            delay=current['interval']
            if current['kind']=='tls' and result['kind']!='ok' and failures<current['threshold']:
                delay=min(delay,60)
            db.execute('UPDATE integration_targets SET status=?,message=?,failures=?,last_checked=?,next_check=? WHERE id=?',
                       (status,message,failures,now,now+delay,target['id']))
            details='\n'.join(m['label']+': '+(str(m['value'])+' '+m.get('unit','') if m['value'] is not None else m.get('message','')) for m in metrics if m['status'] not in ('up','pending'))
            if _time is None or time.time()-now <= max(300,current['interval']*3):
                self.record_notification(db, 'integration', current, status, message, now,
                    provisional=(result['kind']!='ok' and failures<current['threshold']),details=details)
            if status!=current['status']:
                db.execute('INSERT INTO events(time,name,kind,message) VALUES(?,?,?,?)',(now,current['device_name']+' · '+current['name'],status,message))


def probe_integration(target):
    import os
    import signal
    cfg=json.loads(target['config']) if isinstance(target['config'],str) else target['config']
    process=None
    try:
        process=subprocess.Popen([sys.executable,'-m','netzmonitor.integration_worker'],cwd=str(Path(__file__).resolve().parent.parent),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        output,_=process.communicate(json.dumps(dict(kind=target['kind'],config=cfg,timeout=target['timeout'],diagnostic=bool(target.get('diagnostic')))),timeout=target['timeout']+1)
        if process.returncode:return dict(kind='error',message='Prüfprozess fehlgeschlagen. Serverprotokoll und Voraussetzungen prüfen.',metrics=[])
        return json.loads(output)
    except subprocess.TimeoutExpired:
        return dict(kind='error',message='Gesamte Antwortfrist überschritten. Erreichbarkeit oder Auswahl prüfen.',metrics=[])
    except (ValueError,OSError):
        return dict(kind='error',message='Prüfung konnte nicht ausgeführt werden.',metrics=[])
    finally:
        if process:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            process.communicate()
