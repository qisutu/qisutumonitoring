"""Authenticated collectors: per-device assignment and transactional ingestion."""
import hashlib
import hmac
import json
import math
import re
import secrets
import time


def init_collectors(store):
    with store.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS collectors(
            id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,token_hash TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,last_seen REAL,last_error TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS collector_devices(device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
                collector_id INTEGER NOT NULL REFERENCES collectors(id));
            CREATE TABLE IF NOT EXISTS collector_receipts(collector_id INTEGER NOT NULL REFERENCES collectors(id) ON DELETE CASCADE,
                receipt TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(collector_id,receipt));''')


def state(store):
    return dict(collectors=store.rows('SELECT id,name,enabled,last_seen,last_error FROM collectors ORDER BY name'),
                collector_devices=store.rows('SELECT * FROM collector_devices'))


def save(store,data):
    from .core import integer
    name=str(data.get('name','')).strip()
    if not 1<=len(name)<=120:raise ValueError('Name des Messsammlers angeben.')
    token=None
    with store.connect() as db:
        ident=integer(data['id'],1,2147483647,'Messsammler') if data.get('id') else None
        enabled=integer(data.get('enabled',1),0,1,'Aktivierung')
        if ident:
            if not db.execute('UPDATE collectors SET name=?,enabled=? WHERE id=?',(name,enabled,ident)).rowcount:raise ValueError('Messsammler nicht gefunden.')
        else:
            token=secrets.token_urlsafe(48)
            ident=db.execute('INSERT INTO collectors(name,token_hash,enabled) VALUES(?,?,?)',(name,hashlib.sha256(token.encode()).hexdigest(),enabled)).lastrowid
        if data.get('rotate'):
            token=secrets.token_urlsafe(48)
            db.execute('UPDATE collectors SET token_hash=? WHERE id=?',(hashlib.sha256(token.encode()).hexdigest(),ident))
    result=dict(id=ident)
    if token:result['token']=token
    return result


def assign(store,db,device_id,collector_id):
    if collector_id not in (None,'',0,'0'):
        from .core import integer
        collector_id=integer(collector_id,1,2147483647,'Messsammler')
        if not db.execute('SELECT 1 FROM collectors WHERE id=?',(collector_id,)).fetchone():raise ValueError('Messsammler nicht gefunden.')
        if db.execute("SELECT 1 FROM integration_targets WHERE device_id=? AND kind='flow' AND enabled=1",(device_id,)).fetchone():
            raise ValueError('Der NetFlow/IPFIX-Empfang bleibt auf dem zentralen Server. Dafür ein eigenes zentral überwachtes Gerät verwenden.')
    old=db.execute('SELECT collector_id FROM collector_devices WHERE device_id=?',(device_id,)).fetchone()
    if (old[0] if old else None)==(collector_id or None):return
    db.execute('DELETE FROM collector_devices WHERE device_id=?',(device_id,))
    if collector_id:db.execute('INSERT INTO collector_devices VALUES(?,?)',(device_id,collector_id))
    db.execute('UPDATE devices SET revision=revision+1 WHERE id=?',(device_id,))
    for table in ('services','resource_targets','integration_targets'):
        db.execute("UPDATE "+table+" SET next_check=0,revision=revision+1,last_checked=NULL,status='pending' WHERE device_id=?",(device_id,))


def authenticate(store,ident,token):
    if not isinstance(token,str) or not 30<=len(token)<=200:return False
    rows=store.rows('SELECT token_hash,enabled FROM collectors WHERE id=?',(ident,))
    return bool(rows and rows[0]['enabled'] and hmac.compare_digest(rows[0]['token_hash'],hashlib.sha256(token.encode()).hexdigest()))


def selectors():
    from .services import SERVICE_SELECT
    from .resources import RESOURCE_SELECT
    from .integrations import SELECT
    return {'service':(SERVICE_SELECT,'s'),'resource':(RESOURCE_SELECT,'r'),'integration':(SELECT,'i')}


def configuration(store,ident):
    store.refresh_dependencies();jobs=[]
    for kind,(query,alias) in selectors().items():
        query+=' WHERE '+alias+'.enabled=1 AND d.enabled=1 AND d.blocked=0 AND d.license_blocked=0 AND d.id IN (SELECT device_id FROM collector_devices WHERE collector_id=?)'
        if kind=='integration':query+=" AND i.kind NOT IN ('flow','calculated')"
        for target in store.rows(query,(ident,)):
            jobs.append(dict(type=kind,target=target))
    if len(jobs)>10000:raise ValueError('Mehr als 10.000 Prüfungen diesem Messsammler zugewiesen.')
    with store.connect() as db:db.execute("UPDATE collectors SET last_seen=?,last_error='' WHERE id=?",(time.time(),ident))
    return dict(jobs=jobs,server_time=time.time(),lease_seconds=86400)


def validate_result(kind,result):
    if not isinstance(result,dict):raise ValueError('Ungültiges Messergebnis.')
    def finite(value):
        return value is None or isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and abs(value)<1e100
    if len(json.dumps(result))>1500000:raise ValueError('Messergebnis ist zu groß.')
    if kind=='service':
        if result.get('kind') not in ('up','down','error') or not finite(result.get('rtt')) or len(str(result.get('message','')))>4000:raise ValueError('Ungültiges Dienstmessergebnis.')
        result.setdefault('rtt',None);result.setdefault('message','')
        if result.get('status_code') is not None and not (isinstance(result['status_code'],int) and 100<=result['status_code']<=599):raise ValueError('Ungültiger HTTP-Status.')
        return
    if result.get('kind') not in ('ok','down','error'):raise ValueError('Ungültiger Prüfzustand.')
    for category in ('metrics','extended'):
        rows=result.get(category,[])
        if not isinstance(rows,list) or len(rows)>5000:raise ValueError('Zu viele Messwerte.')
        for row in rows:
            if not isinstance(row,dict) or not row.get('key') or len(str(row['key']))>500 or len(str(row.get('label','')))>500:raise ValueError('Ungültige Messwertkennung.')
            for key in ('value','percent','total','used','free','warn','critical'):
                if not finite(row.get(key)):raise ValueError('Ungültiger Zahlenwert.')
            if row.get('status') not in (None,'up','warning','critical','unknown','pending'):raise ValueError('Ungültiger Messwertzustand.')
            if kind=='integration' and ('value' not in row or 'unit' not in row or row.get('status') is None):raise ValueError('Unvollständiger Messwert.')
            if kind=='resource' and category=='metrics' and row.get('kind') not in ('cpu','ram','disk'):raise ValueError('Ungültige Ressourcenart.')


def ingest(store,ident,body):
    if not isinstance(body,dict):raise ValueError('Ungültige Übertragung.')
    records=body.get('records')
    if not isinstance(records,list) or not 1<=len(records)<=20:raise ValueError('Eine bis 20 Messungen übermitteln.')
    if any(not isinstance(record,dict) for record in records):raise ValueError('Ungültige Messung.')
    now=time.time();accepted=[]
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for record in sorted(records,key=lambda r:r.get('time') if isinstance(r.get('time'),(int,float)) else 0):
            receipt=record.get('receipt','');kind=record.get('type');stamp=record.get('time')
            if not isinstance(receipt,str) or not re.fullmatch('[a-f0-9-]{36}',receipt) or kind not in selectors() or not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or stamp>now+60 or stamp<now-30*86400:raise ValueError('Ungültige Messung oder Messzeit.')
            if db.execute('SELECT 1 FROM collector_receipts WHERE collector_id=? AND receipt=?',(ident,receipt)).fetchone():accepted.append(receipt);continue
            query,alias=selectors()[kind]
            current=db.execute(query+' WHERE '+alias+'.id=? AND d.id IN (SELECT device_id FROM collector_devices WHERE collector_id=?)',(record.get('id'),ident)).fetchone()
            if current:
                target=dict(current)
                valid=record.get('revision')==target['revision'] and record.get('device_revision')==target['device_revision'] and record.get('block_revision')==target['device_block_revision']
                if valid and not (kind=='integration' and target['kind'] in ('flow','calculated')):
                    validate_result(kind,record.get('result'))
                    getattr(store,'record_'+kind)(target,record['result'],_db=db,_time=stamp)
            # Removed/reconfigured targets are acknowledged and discarded: old
            # credentials and old measurements must not revive deleted checks.
            db.execute('INSERT INTO collector_receipts VALUES(?,?,?)',(ident,receipt,now));accepted.append(receipt)
        db.execute("UPDATE collectors SET last_seen=?,last_error='' WHERE id=?",(now,ident))
        db.execute('DELETE FROM collector_receipts WHERE created<?',(now-31*86400,))
    return dict(accepted=accepted)
