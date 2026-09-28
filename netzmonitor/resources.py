"""SNMP resource collection and storage. No writes to monitored devices."""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tempfile
import time

CPU_OID = '.1.3.6.1.2.1.25.3.3.1.2'
STORAGE_OID = '.1.3.6.1.2.1.25.2.3.1'
MEMORY_OID = '.1.3.6.1.4.1.2021.4'
STORAGE_TYPE = '.1.3.6.1.2.1.25.2.1'
RESOURCE_SELECT = '''SELECT r.*,d.address AS device_address,d.name AS device_name,
 d.enabled AS device_enabled,d.revision AS device_revision,d.blocked AS device_blocked,d.license_blocked AS device_license_blocked,d.block_revision AS device_block_revision
 FROM resource_targets r JOIN devices d ON d.id=r.device_id'''
SECRETS = ('community', 'auth_password', 'priv_password', 'ssh_password', 'ssh_key')
DEFAULTS = dict(method='ssh', ssh_auth='password', ssh_password='', ssh_key='', ssh_host_key='', version='3', port=22, username='', community='', auth_password='',
                priv_password='', auth_protocol='SHA-256', priv_protocol='AES',
                interval=60, timeout=15, threshold=3, cpu_warn=80, cpu_crit=95,
                ram_warn=80, ram_crit=95, disk_warn=80, disk_crit=90)


def secret_text(value, label, minimum=1):
    value = str(value)
    if not minimum <= len(value) <= 255 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ValueError(label + ': %s bis 255 druckbare ASCII-Zeichen verwenden.' % minimum)
    return value


def validate_config(data, old=None):
    from .core import integer
    value = {**DEFAULTS, **(old or {})}
    value.update({k: data[k] for k in DEFAULTS if k in data and k not in SECRETS})
    for key in ('community','auth_password','priv_password'):
        if data.get(key):
            value[key] = secret_text(data[key], {'community':'Community','auth_password':'Authentifizierungspasswort','priv_password':'Verschlüsselungspasswort'}[key], 1 if key == 'community' else 8)
    if value['method'] not in ('ssh','snmp'):
        raise ValueError('SSH oder SNMP als Zugang auswählen.')
    if value['method']=='ssh':
        from .ssh_resources import host_key
        if not re.fullmatch(r'[a-zA-Z0-9_.@\\-]{1,128}',str(value['username'])):
            raise ValueError('Gültigen SSH-Benutzernamen angeben.')
        value['ssh_host_key'], _ = host_key(value['ssh_host_key'])
        if value['ssh_auth'] not in ('password','key'):
            raise ValueError('SSH-Anmeldung per Passwort oder privatem Schlüssel wählen.')
        for key in ('ssh_password','ssh_key'):
            if data.get(key):
                value[key]=str(data[key])
        if '\x00' in value['ssh_password'] or '\n' in value['ssh_password'] or '\r' in value['ssh_password'] or len(value['ssh_password'])>1024:
            raise ValueError('SSH-Passwort: höchstens 1.024 Zeichen ohne Zeilenumbrüche.')
        if value['ssh_auth']=='password':
            if not value['ssh_password']:
                raise ValueError('SSH-Passwort eingeben.')
            value['ssh_key']=''
        elif len(value['ssh_key'])>16384 or not re.search(r'-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----',value['ssh_key']):
            raise ValueError('Vollständigen privaten SSH-Schlüssel im OpenSSH- oder PEM-Format einfügen.')
        value.update(community='',auth_password='',priv_password='')
    else:
        if value['version'] not in ('2c', '3'):
            raise ValueError('SNMP-Version 2c oder 3 wählen.')
        if value['version'] == '2c':
            value['community'] = secret_text(value['community'], 'Community')
            value.update(username='', auth_password='', priv_password='')
        else:
            value['username'] = secret_text(value['username'], 'SNMP-Benutzer')
            value['auth_password'] = secret_text(value['auth_password'], 'Authentifizierungspasswort', 8)
            value['priv_password'] = secret_text(value['priv_password'], 'Verschlüsselungspasswort', 8)
            value['community'] = ''
        if value['auth_protocol'] not in ('SHA', 'SHA-256', 'SHA-512') or value['priv_protocol'] != 'AES':
            raise ValueError('SNMPv3: SHA, SHA-256 oder SHA-512 mit AES wählen.')
        value.update(ssh_key='',ssh_password='',ssh_host_key='')
    for key, lo, hi, label in [('port',1,65535,'Port'),('interval',15,86400,'Intervall'),
                               ('timeout',3,60,'Gesamte Antwortfrist'),('threshold',1,20,'Fehlerschwelle')]:
        value[key] = integer(value[key],lo,hi,label)
    for kind in ('cpu','ram','disk'):
        for level in ('warn','crit'):
            key=kind+'_'+level
            value[key] = integer(value[key],1,100,'Grenzwert in Prozent')
        if value[kind+'_warn'] >= value[kind+'_crit']:
            raise ValueError('Der Warnwert muss für CPU, RAM und Festplatten jeweils kleiner als der kritische Wert sein.')
    return {k:value[k] for k in DEFAULTS}


class ResourceStore:
    def init_resources(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS resource_targets (
             id INTEGER PRIMARY KEY AUTOINCREMENT,device_id INTEGER NOT NULL UNIQUE REFERENCES devices(id) ON DELETE CASCADE,
             method TEXT NOT NULL,ssh_auth TEXT NOT NULL,ssh_password TEXT NOT NULL,ssh_key TEXT NOT NULL,ssh_host_key TEXT NOT NULL,
             version TEXT NOT NULL,port INTEGER NOT NULL,username TEXT NOT NULL,community TEXT NOT NULL,
             auth_password TEXT NOT NULL,priv_password TEXT NOT NULL,auth_protocol TEXT NOT NULL,priv_protocol TEXT NOT NULL,
             interval INTEGER NOT NULL,timeout INTEGER NOT NULL,threshold INTEGER NOT NULL,
             cpu_warn INTEGER NOT NULL,cpu_crit INTEGER NOT NULL,ram_warn INTEGER NOT NULL,ram_crit INTEGER NOT NULL,
             disk_warn INTEGER NOT NULL,disk_crit INTEGER NOT NULL,
             enabled INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL DEFAULT 'pending',message TEXT NOT NULL DEFAULT '',
             last_checked REAL,next_check REAL NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS resource_metrics (
             id INTEGER PRIMARY KEY AUTOINCREMENT,target_id INTEGER NOT NULL REFERENCES resource_targets(id) ON DELETE CASCADE,
             metric_key TEXT NOT NULL,kind TEXT NOT NULL,label TEXT NOT NULL,percent REAL,total REAL,used REAL,free REAL,
             status TEXT NOT NULL,message TEXT NOT NULL,last_checked REAL NOT NULL,
             UNIQUE(target_id,metric_key));
            CREATE TABLE IF NOT EXISTS resource_samples (
             id INTEGER PRIMARY KEY,metric_id INTEGER NOT NULL REFERENCES resource_metrics(id) ON DELETE CASCADE,
             time REAL NOT NULL,percent REAL,total REAL,used REAL,free REAL,status TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS resource_samples_metric ON resource_samples(metric_id,time);
            CREATE INDEX IF NOT EXISTS resource_samples_time ON resource_samples(time);
            ''')

    def resource_state(self):
        targets = self.rows(RESOURCE_SELECT+' ORDER BY d.name COLLATE NOCASE,r.id')
        metrics = self.rows('SELECT * FROM resource_metrics ORDER BY kind,label')
        by_target = {}
        for metric in metrics:
            by_target.setdefault(metric['target_id'], []).append(metric)
        for target in targets:
            from .extended import config
            target['advanced']=config(target['advanced'])
            for key in SECRETS:
                target['has_'+key] = bool(target.pop(key))
            if target['ssh_host_key']:
                from .ssh_resources import host_key
                target['fingerprint']=host_key(target['ssh_host_key'])[1]
            target['metrics'] = by_target.get(target['id'], []) if target['advanced']['basic'] else []
        return targets

    def save_resource(self, data, _db=None):
        from .core import integer
        ident = integer(data['id'],1,2147483647,'Ressourcenprüfung') if data.get('id') else None
        device = integer(data.get('device_id'),1,2147483647,'Gerät')
        with self.connect(_db) as db:
            if _db is None: db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM devices WHERE id=?',(device,)).fetchone():
                raise ValueError('Gerät nicht gefunden.')
            old = db.execute('SELECT * FROM resource_targets WHERE id=?',(ident,)).fetchone() if ident else None
            if ident and (not old or old['device_id'] != device):
                raise ValueError('Ressourcenprüfung für dieses Gerät nicht gefunden.')
            if not ident and db.execute('SELECT 1 FROM resource_targets WHERE device_id=?',(device,)).fetchone():
                raise ValueError('Für dieses Gerät ist bereits eine Ressourcenprüfung eingerichtet. Bitte bearbeiten.')
            config = validate_config(data,dict(old) if old else None)
            from .extended import validate, DEFAULT as EXTENDED_DEFAULT
            config['advanced']=json.dumps(validate(data.get('advanced',old['advanced'] if old else EXTENDED_DEFAULT),config['method']),sort_keys=True)
            if ident:
                if all(old[k] == v for k,v in config.items()):
                    return ident
                if old['method']!=config['method'] or old['port']!=config['port']:
                    db.execute('DELETE FROM resource_metrics WHERE target_id=?',(ident,))
                    db.execute('DELETE FROM extended_metrics WHERE target_id=?',(ident,))
                db.execute('DELETE FROM counter_baselines WHERE target_id=?',(ident,))
                db.execute("UPDATE extended_metrics SET status='pending' WHERE target_id=?",(ident,))
                db.execute('UPDATE resource_targets SET '+','.join(k+'=?' for k in config)+",revision=revision+1,next_check=0,status='pending',failures=0,message='' WHERE id=?", tuple(config.values())+(ident,))
                # Existing values remain explicitly pending until a fresh check uses the new configuration.
                db.execute("UPDATE resource_metrics SET status='pending' WHERE target_id=?",(ident,))
            else:
                ident=db.execute('INSERT INTO resource_targets(device_id,'+','.join(config)+') VALUES('+','.join('?' for _ in range(len(config)+1))+')',(device,)+tuple(config.values())).lastrowid
            return ident

    def resource_action(self, ident, action):
        from .core import integer
        ident=integer(ident,1,2147483647,'Ressourcenprüfung')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            target=db.execute(RESOURCE_SELECT+' WHERE r.id=?',(ident,)).fetchone()
            if not target:
                raise ValueError('Ressourcenprüfung nicht gefunden.')
            if action in ('check','resume'):self.require_device_license(target['device_id'],db)
            if action=='delete':
                db.execute('DELETE FROM resource_targets WHERE id=?',(ident,))
            elif action=='check':
                if not target['enabled'] or not target['device_enabled']:
                    raise ValueError('Zuerst die Überwachung von Gerät und Ressourcen starten.')
                db.execute('UPDATE resource_targets SET next_check=0 WHERE id=?',(ident,))
            elif action in ('pause','resume'):
                db.execute("UPDATE resource_targets SET enabled=?,revision=revision+1,next_check=0,status='pending',failures=0 WHERE id=?",(int(action=='resume'),ident))
            else:
                raise ValueError('Unbekannte Ressourcenaktion.')

    def record_resource(self, target, result, _db=None, _time=None):
        now=time.time() if _time is None else _time
        with self.connect(_db) as db:
            if _db is None: db.execute('BEGIN IMMEDIATE')
            self.refresh_license_access(db)
            current=db.execute(RESOURCE_SELECT+' WHERE r.id=?',(target['id'],)).fetchone()
            if (not current or not current['enabled'] or not current['device_enabled'] or current['device_license_blocked'] or current['device_blocked'] or
                current['device_block_revision']!=target.get('device_block_revision',0) or current['revision']!=target['revision'] or current['device_revision']!=target['device_revision']):
                return
            if current['last_checked'] is not None and now < current['last_checked']:
                return
            failures=0
            before={r['metric_key']:dict(r) for r in db.execute('SELECT * FROM resource_metrics WHERE target_id=?',(target['id'],))}
            from .extended import config as extended_config
            basic=extended_config(current['advanced'])['basic']
            if not basic:before={}
            observed={}
            if result['kind']=='ok':
                for metric in result['metrics'] if basic else []:
                    m=dict(metric)
                    m['status']=('unknown' if m['percent'] is None else
                        'critical' if m['percent']>=current[m['kind']+'_crit'] else
                        'warning' if m['percent']>=current[m['kind']+'_warn'] else 'up')
                    observed[m['key']]=m
                # A disappeared filesystem or missing value must never stay green.
                for key,old in before.items():
                    if key not in observed and key!='disk:none':
                        observed[key]=dict(key=key,kind=old['kind'],label=old['label'],percent=None,total=None,used=None,free=None,
                                           status='unknown',message='Wird vom Gerät derzeit nicht geliefert.')
                if any(m['kind']=='disk' and m['key']!='disk:none' for m in observed.values()):
                    observed.pop('disk:none',None)
                    db.execute("DELETE FROM resource_metrics WHERE target_id=? AND metric_key='disk:none'",(target['id'],))
                states={m['status'] for m in observed.values()}
                status=next((s for s in ('critical','warning','unknown') if s in states),'up')
                message={'up':'CPU, RAM und Dateisysteme innerhalb der Grenzwerte.',
                         'warning':'Mindestens ein Warnwert ist erreicht.',
                         'critical':'Mindestens ein kritischer Grenzwert ist erreicht.',
                         'unknown':'Nicht alle Messwerte sind verfügbar. Zugang und Geräteunterstützung prüfen.'}[status]
            else:
                failures=current['failures']+1 if result['kind']=='down' else current['failures']
                status=('down' if failures>=current['threshold'] else 'warning') if result['kind']=='down' else 'error'
                message=result['message']
                for key,old in before.items():
                    observed[key]=dict(key=key,kind=old['kind'],label=old['label'],percent=None,total=None,used=None,free=None,status='unknown',message=message)
            extended=self.record_extended(db,current,result,now)
            if result['kind']=='ok':
                states={m['status'] for m in observed.values()}|{m['status'] for m in extended}
                status=next((s for s in ('critical','warning','unknown','pending') if s in states),'up')
                problem=next((m for m in extended if m['status']==status),None)
                if problem and status!='up':
                    message=problem['label']+': '+(problem['message'] or (str(round(problem['value'],2))+' '+problem['unit'] if problem['value'] is not None else 'Warte auf Messwerte'))
                elif status=='up' and extended:message='Alle aktiven Ressourcenmessungen innerhalb der Grenzwerte.'
            for key,m in observed.items():
                values=(m['kind'],m['label'],m['percent'],m.get('total'),m.get('used'),m.get('free'),m['status'],m.get('message',''),now)
                if key in before:
                    mid=before[key]['id']
                    db.execute('UPDATE resource_metrics SET kind=?,label=?,percent=?,total=?,used=?,free=?,status=?,message=?,last_checked=? WHERE id=?',values+(mid,))
                else:
                    mid=db.execute('INSERT INTO resource_metrics(kind,label,percent,total,used,free,status,message,last_checked,target_id,metric_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)',values+(target['id'],key)).lastrowid
                db.execute('INSERT INTO resource_samples(metric_id,time,percent,total,used,free,status) VALUES(?,?,?,?,?,?,?)',
                           (mid,now,m['percent'],m.get('total'),m.get('used'),m.get('free'),m['status']))
                if m['status']!=(before.get(key) or {}).get('status'):
                    db.execute('INSERT INTO events(time,name,kind,message) VALUES(?,?,?,?)',(now,current['device_name']+' · '+m['label'],
                        {'critical':'down','unknown':'error'}.get(m['status'],m['status']),
                        {'up':'Messwert wieder innerhalb der Grenzwerte: ','warning':'Warnwert erreicht: ','critical':'Kritischer Grenzwert erreicht: ','unknown':'Messwert fehlt: '}[m['status']]+(str(round(m['percent'],1))+' %' if m['percent'] is not None else m.get('message',''))))
            if current['status']!=status:
                db.execute('INSERT INTO events(time,name,kind,message) VALUES(?,?,?,?)',(now,current['device_name']+' · Ressourcen',{'critical':'down','unknown':'error'}.get(status,status),message))
            db.execute('UPDATE resource_targets SET status=?,message=?,failures=?,last_checked=?,next_check=? WHERE id=?',(status,message,failures,now,now+current['interval'],target['id']))
            details='\n'.join(m['label']+': '+(str(round(m['percent'],1))+' %' if m['percent'] is not None else m.get('message','')) for m in observed.values() if m['status'] not in ('up','pending'))
            if _time is None or time.time()-now <= max(300,current['interval']*3):
                self.record_notification(db, 'resource', current, status, message, now,
                    provisional=(result['kind']=='down' and failures<current['threshold']),details=details)


def parse_output(output, root):
    values={}
    for line in output.splitlines():
        match=re.fullmatch(r'(\.[0-9.]+)\s*=\s*(.*)',line)
        if not match or not (match[1] == root or match[1].startswith(root+'.')):
            continue
        oid,raw=match.groups()
        # Net-SNMP -Ot prints TimeTicks without the type prefix.
        if re.fullmatch(r'-?[0-9]+',raw.strip()):
            values[oid]=int(raw.strip())
            continue
        if ': ' not in raw:
            continue
        kind,value=raw.split(': ',1)
        if kind in ('INTEGER','Gauge32','Counter32','Counter64','Unsigned32','Timeticks'):
            if re.fullmatch(r'-?[0-9]+',value.strip()):
                values[oid]=int(value)
        elif kind=='OID':
            values[oid]=value.strip()
        elif kind=='STRING':
            values[oid]=value.strip('"')[:250]
        elif kind=='Hex-STRING':
            try: values[oid]=('hex:'+bytes.fromhex(value).hex()) if oid.startswith('.1.3.6.1.2.1.25.3.5.1.2.') else bytes.fromhex(value).decode('utf-8',errors='replace')[:250]
            except ValueError: pass
    return values


def make_metrics(cpu, storage, memory):
    loads=[v for k,v in cpu.items() if k.startswith(CPU_OID+'.') and isinstance(v,int) and 0<=v<=100]
    metrics=[dict(key='cpu',kind='cpu',label='CPU gesamt',percent=sum(loads)/len(loads) if loads else None,
                  message=('Mittel über %s logische CPUs; SNMP-Mittelwert der letzten Minute.' % len(loads)) if loads else 'CPU-Auslastung wird nicht geliefert.')]
    rows={}
    for oid,value in storage.items():
        suffix=oid[len(STORAGE_OID)+1:].split('.')
        if len(suffix)==2:
            column,index=suffix
            rows.setdefault(index,{})[column]=value
    ram=[]
    for index,row in rows.items():
        kind='ram' if row.get('2')==STORAGE_TYPE+'.2' else 'disk' if row.get('2') in (STORAGE_TYPE+'.4',STORAGE_TYPE+'.10') else None
        if not kind: continue
        label=str(row.get('3') or 'Dateisystem '+index)
        units,size,used=(row.get(k) for k in ('4','5','6'))
        valid=all(isinstance(v,int) for v in (units,size,used)) and units>0 and size>0 and 0<=used<=size
        if kind=='ram':
            if valid: ram.append((units*size,units*used))
            continue
        key='disk:'+hashlib.sha256(label.encode()).hexdigest()[:24]
        metrics.append(dict(key=key,kind='disk',label=label,percent=100*used/size if valid else None,
            total=units*size if valid else None,used=units*used if valid else None,free=units*(size-used) if valid else None,
            message='Belegung laut SNMP; reservierter Speicher kann abweichen.' if valid else 'Ungültige oder unvollständige Speicherwerte.'))
    total=memory.get(MEMORY_OID+'.5.0'); available=memory.get(MEMORY_OID+'.27.0')
    if isinstance(total,int) and isinstance(available,int) and total>0 and 0<=available<=total:
        total,free=total*1024,available*1024
        used=total-free; note='Verfügbarer Arbeitsspeicher laut System, einschließlich wiederverwendbarem Cache.'
    elif ram:
        total=sum(x[0] for x in ram);used=sum(x[1] for x in ram);free=total-used
        note='RAM laut HOST-RESOURCES-MIB. Cache kann je nach Gerät als belegt zählen.'
    else:
        total=used=free=None;note='Arbeitsspeicher wird nicht geliefert.'
    metrics.insert(1,dict(key='ram',kind='ram',label='Arbeitsspeicher',percent=100*used/total if total else None,total=total,used=used,free=free,message=note))
    if not any(m['kind']=='disk' for m in metrics):
        metrics.append(dict(key='disk:none',kind='disk',label='Dateisysteme',percent=None,message='Keine lokalen oder Netz-Dateisysteme freigegeben oder unterstützt.'))
    # Duplicate labels are ambiguous; do not merge two filesystems into one healthy reading.
    seen=set()
    for metric in metrics:
        if metric['key'] in seen:
            for original in metrics:
                if original['key']==metric['key']:
                    original.update(percent=None,total=None,used=None,free=None,message='Mehrdeutige SNMP-Bezeichnung: mehrere Speicherbereiche mit gleichem Namen.')
        seen.add(metric['key'])
    return list({m['key']:m for m in metrics}.values())


def config_text(target):
    def quoted(value):
        return '"'+str(value).replace('\\','\\\\').replace('"','\\"')+'"'
    lines=['defVersion '+target['version']]
    if target['version'] in ('1','2c'):
        lines.append('defCommunity '+quoted(target['community']))
    else:
        lines.extend(['defSecurityName '+quoted(target['username']),'defSecurityLevel authPriv',
                      'defAuthType '+target['auth_protocol'],'defPrivType AES',
                      'defAuthPassphrase '+quoted(target['auth_password']),
                      'defPrivPassphrase '+quoted(target['priv_password'])])
    return '\n'.join(lines)+'\n'


class CheckError(Exception):
    pass


def run_walk(binary, target, oid, directory, deadline, *, bulk=True, include_root=False):
    remaining=deadline-time.monotonic()
    if remaining<=0: raise CheckError('Gesamte Antwortfrist überschritten.')
    host=target['device_address']
    endpoint=('udp6:['+host+']:' if ':' in host else 'udp:'+host+':')+str(target['port'])
    args=[binary,'-On','-Oe','-Ot','-OU','-m','','-Cr25','-t',str(min(2,remaining)),'-r','0',endpoint,oid]
    if not bulk: args.remove('-Cr25')
    if include_root: args.insert(1,'-Ci')
    if oid=='.1.3.6.1.2.1.25.3.5': args.insert(1,'-Ox')
    env={**os.environ,'SNMPCONFPATH':directory,'SNMP_PERSISTENT_DIR':directory,'MIBS':'','LC_ALL':'C'}
    proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env)
    output=bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout,selectors.EVENT_READ)
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0 or not selector.select(remaining):
                    raise CheckError('Gesamte Antwortfrist überschritten (einschließlich Namensauflösung).')
                block=os.read(proc.stdout.fileno(),65536)
                if not block: break
                output.extend(block)
                if len(output)>2_000_000:
                    raise CheckError('SNMP-Antwort ist zu groß. Freigabe auf benötigte Ressourcen begrenzen.')
        proc.wait(timeout=max(.05,deadline-time.monotonic()))
    finally:
        if proc.poll() is None: proc.kill()
        proc.wait();proc.stdout.close()
    text=output.decode('utf-8',errors='replace')
    if proc.returncode:
        lowered=text.lower()
        if 'timeout' in lowered:
            raise CheckError('Keine SNMP-Antwort. Adresse, UDP-Port, Freigabe und Zugang prüfen.')
        if any(word in lowered for word in ('authentication','unknown user','authorization','decryption','digest')):
            raise CheckError('SNMP-Zugang abgelehnt. Benutzer, Passwörter, Verfahren und Leserechte prüfen.')
        raise CheckError('SNMP-Abfrage fehlgeschlagen. Zugang, SNMP-Version und unterstützte Verfahren prüfen.')
    return parse_output(text,oid)


def probe_resources(target):
    if target.get('method')=='ssh':
        from .ssh_resources import probe_ssh
        return probe_ssh(target)
    binary=shutil.which('snmpbulkwalk')
    if not binary:
        return dict(kind='error',message='Auf dem Monitoring-Server fehlt snmpbulkwalk (Net-SNMP). Installer erneut ausführen.',metrics=[])
    deadline=time.monotonic()+target['timeout']
    try:
        with tempfile.TemporaryDirectory(prefix='netzmonitor-snmp-') as directory:
            path=Path(directory)/'snmp.conf'
            path.write_text(config_text(target),encoding='utf-8');path.chmod(0o600)
            from .extended import config
            c=config(target.get('advanced'))
            cpu=run_walk(binary,target,CPU_OID,directory,deadline) if c['basic'] else {}
            storage=run_walk(binary,target,STORAGE_OID,directory,deadline) if c['basic'] else {}
            # Optional Linux extension; standard physical RAM is retained when absent.
            try: memory=run_walk(binary,target,MEMORY_OID,directory,deadline) if c['basic'] else {}
            except CheckError: memory={}
            from .collect_extended import collect_snmp
            def walk(oid):
                try:return run_walk(binary,target,oid,directory,deadline)
                except CheckError:return {}
            extra=collect_snmp(walk,target)
            return dict(kind='ok',metrics=make_metrics(cpu,storage,memory) if c['basic'] else [],message='',**extra)
    except CheckError as exc:
        return dict(kind='down',message=str(exc),metrics=[])
    except (OSError,subprocess.TimeoutExpired):
        return dict(kind='error',message='SNMP-Prüfung konnte auf dem Monitoring-Server nicht ausgeführt werden.',metrics=[])
