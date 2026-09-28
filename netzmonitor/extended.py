"""Typed measurements, persistent counter baselines and configuration."""
import hashlib
import json
import math
import re
import time

DEFAULT = dict(basic=True, network=False, disk_io=False, hardware=False, smart=False,
               processes=[], services=[], interfaces={}, net_warn=80, net_crit=95,
               errors_warn=1, errors_crit=100, io_warn=80, io_crit=95, temp_warn=70, temp_crit=85)
CATEGORY = {'network':'Netzwerkschnittstellen','disk_io':'Festplattenleistung','hardware':'Hardwarezustand',
            'process':'Prozesse','service':'Systemdienste','smart':'Datenträgerzustand'}


def config(value=None):
    if isinstance(value,str): value=json.loads(value)
    return {**DEFAULT,**(value or {})}


def validate(value, method):
    from .core import integer
    if isinstance(value,str):
        try: value=json.loads(value)
        except ValueError: raise ValueError('Ungültige erweiterte Konfiguration.')
    if not isinstance(value,dict) or set(value)-set(DEFAULT):
        raise ValueError('Ungültige erweiterte Konfiguration.')
    v=config(value)
    for k in ('basic','network','disk_io','hardware','smart'):
        if not isinstance(v[k],bool): raise ValueError('Aktivierung muss wahr oder falsch sein.')
    for k in ('processes','services'):
        if not isinstance(v[k],list) or len(v[k])>100:
            raise ValueError('Maximal 100 '+k+' je Gerät.')
        clean=[]
        for name in v[k]:
            if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.@:+\\-]{1,128}',name):
                raise ValueError('Prozess-/Dienstnamen nur mit Buchstaben, Zahlen, Punkt, @, :, +, - oder Unterstrich angeben.')
            if k=='services' and not name.endswith('.service'):name+='.service'
            if name not in clean:clean.append(name)
        v[k]=clean
    if method!='ssh' and (v['services'] or v['disk_io'] or v['smart']):
        raise ValueError('Systemdienste, Festplattenleistung und SMART benötigen einen Linux-SSH-Zugang.')
    if not isinstance(v['interfaces'],dict) or len(v['interfaces'])>4096:
        raise ValueError('Ungültige Schnittstellenauswahl.')
    for key,row in v['interfaces'].items():
        if not isinstance(key,str) or len(key)>300 or not isinstance(row,dict) or set(row)-{'enabled','expect_up','speed'}:
            raise ValueError('Ungültige Portregel.')
        for flag in ('enabled','expect_up'):
            if flag in row and not isinstance(row[flag],bool):raise ValueError('Ungültige Portaktivierung.')
        if 'speed' in row:row['speed']=integer(row['speed'],0,10000000,'Portgeschwindigkeit (Mbit/s; 0 = automatisch)')
    for stem,maximum in (('net',100),('io',100),('temp',250),('errors',1000000000)):
        for level in ('warn','crit'):v[stem+'_'+level]=integer(v[stem+'_'+level],1,maximum,'Grenzwert')
        if v[stem+'_warn']>=v[stem+'_crit']:raise ValueError('Warnwert muss kleiner als kritischer Wert sein.')
    if not any(v[k] for k in ('basic','network','disk_io','hardware','smart','processes','services')):
        raise ValueError('Mindestens eine Ressourcenart aktivieren.')
    return v


def key_for(category, identity):
    return category+':'+hashlib.sha256(str(identity).encode()).hexdigest()[:24]


def metric(category, entity, channel, value, unit='', status=None, message='', warn=None, critical=None):
    return dict(key=key_for(category,entity)+':'+channel,category=category,entity=entity,channel=channel,
                label=entity+' · '+channel,value=value,unit=unit,status=status,message=message,warn=warn,critical=critical)


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def counter_rate(old,new,seconds,bits=64,maximum=None):
    """Never invent rates across resets or ambiguously wrapped 32-bit counters."""
    if not all(number(v) and v>=0 for v in (old,new)) or seconds<=0:return None
    if bits==32 and (maximum is None or seconds*maximum>=2**32):return None
    delta=new-old
    if delta<0:
        if bits!=32:return None
        delta+=2**32
    rate=delta/seconds
    if maximum is not None and rate>maximum*1.2:return None
    return rate


class ExtendedStore:
    def init_extended(self):
        with self.connect() as db:
            if 'advanced' not in [r['name'] for r in db.execute('PRAGMA table_info(resource_targets)')]:
                db.execute("ALTER TABLE resource_targets ADD COLUMN advanced TEXT NOT NULL DEFAULT '{}'")
            db.execute("UPDATE resource_targets SET advanced=? WHERE advanced='{}'",(json.dumps(DEFAULT,sort_keys=True),))
            db.executescript('''
            CREATE TABLE IF NOT EXISTS extended_metrics(
              id INTEGER PRIMARY KEY AUTOINCREMENT,target_id INTEGER NOT NULL REFERENCES resource_targets(id) ON DELETE CASCADE,
              metric_key TEXT NOT NULL,category TEXT NOT NULL,entity TEXT NOT NULL,channel TEXT NOT NULL,label TEXT NOT NULL,
              value REAL,unit TEXT NOT NULL,status TEXT NOT NULL,message TEXT NOT NULL,warn REAL,critical REAL,
              enabled INTEGER NOT NULL DEFAULT 1,last_checked REAL NOT NULL,UNIQUE(target_id,metric_key));
            CREATE TABLE IF NOT EXISTS extended_samples(id INTEGER PRIMARY KEY,metric_id INTEGER NOT NULL REFERENCES extended_metrics(id) ON DELETE CASCADE,
              time REAL NOT NULL,value REAL,status TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS extended_samples_metric_time ON extended_samples(metric_id,time);
            CREATE INDEX IF NOT EXISTS extended_samples_time ON extended_samples(time);
            CREATE TABLE IF NOT EXISTS counter_baselines(target_id INTEGER NOT NULL REFERENCES resource_targets(id) ON DELETE CASCADE,
              counter_key TEXT NOT NULL,time REAL NOT NULL,data TEXT NOT NULL,PRIMARY KEY(target_id,counter_key));
            ''')

    def extended_state(self):
        return self.rows('SELECT m.*,r.device_id FROM extended_metrics m JOIN resource_targets r ON r.id=m.target_id ORDER BY m.category,m.entity,m.id')

    def record_extended(self, db, target, result, now):
        cfg=config(target['advanced']);observed={}
        active={'network':cfg['network'],'disk_io':cfg['disk_io'],'hardware':cfg['hardware'],
                'smart':cfg['smart'],'process':bool(cfg['processes']),'service':bool(cfg['services'])}
        before={m['metric_key']:dict(m) for m in db.execute('SELECT * FROM extended_metrics WHERE target_id=?',(target['id'],))}
        previous={r['counter_key']:dict(r) for r in db.execute('SELECT * FROM counter_baselines WHERE target_id=?',(target['id'],))}
        def baseline(key,row):
            old=previous.get(key);data=json.loads(old['data']) if old else {}
            seconds=now-old['time'] if old else 0
            # Pauses, failed polls, reboot, changed identity or counter discontinuity restart the series.
            valid=(0<seconds<=max(target['interval']*3,target['timeout']+30) and data.get('identity')==row.get('identity')
                   and data.get('epoch')==row.get('epoch') and row.get('clock',0)>=data.get('clock',0))
            db.execute('INSERT INTO counter_baselines VALUES(?,?,?,?) ON CONFLICT(target_id,counter_key) DO UPDATE SET time=excluded.time,data=excluded.data',
                       (target['id'],key,now,json.dumps(row)))
            return (data if valid else {}),seconds
        def add(m):
            if not number(m['value']):m['value']=None
            if m['status'] is None:
                m['status']='unknown' if m['value'] is None else 'critical' if m['critical'] is not None and m['value']>=m['critical'] else 'warning' if m['warn'] is not None and m['value']>=m['warn'] else 'up'
            observed[m['key']]=m
        if result['kind']=='ok':
            for m in result.get('extended',[]):
                if active.get(m['category']):add(dict(m))
            for n in result.get('interfaces',[]) if cfg['network'] else []:
                entity=n['name'];rules=cfg['interfaces'].get(entity,{})
                old,seconds=baseline('net:'+entity,n)
                speed=rules.get('speed',0)*1000000 or n.get('speed') or 0
                enabled=rules.get('enabled',True);expect=rules.get('expect_up',False)
                link=n.get('oper');admin=n.get('admin',1)
                note=n.get('alias','')
                state='unknown' if link in (None,4) else 'critical' if expect and link!=1 else 'up'
                add(metric('network',entity,'Verbindung',1 if link==1 else 0 if link not in (None,4) else None,'',state,
                           ('Zustand unbekannt' if link in (None,4) else 'Verbunden' if link==1 else 'Administrativ deaktiviert' if admin==2 else 'Nicht verbunden')+(' · '+note if note else '')))
                add(metric('network',entity,'Geschwindigkeit',speed/1e6 if speed else None,'Mbit/s','up' if speed else 'unavailable','Automatisch erkannt' if speed and not rules.get('speed') else 'Manuell vorgegeben' if speed else 'Vom Gerät nicht geliefert; bei Bedarf manuell vorgeben.'))
                rates={}
                for field,label,unit,scale in [('rx','Empfang','Mbit/s',8/1e6),('tx','Versand','Mbit/s',8/1e6),
                                             ('rx_errors','Empfangsfehler','Pakete/s',1),('tx_errors','Sendefehler','Pakete/s',1),
                                             ('rx_drops','Verworfen eingehend','Pakete/s',1),('tx_drops','Verworfen ausgehend','Pakete/s',1)]:
                    bits=n.get('bits',64) if field in ('rx','tx') else n.get('error_bits',64)
                    maximum=speed/8 if speed and field in ('rx','tx') else speed/512 if speed else None
                    rate=counter_rate(old.get(field),n.get(field),seconds,bits,maximum) if old else None
                    rates[field]=rate
                    missing=n.get(field) is None
                    status='unknown' if missing else 'pending' if rate is None else None
                    if not missing and old and bits==32 and (maximum is None or seconds*maximum>=2**32):status='unavailable'
                    warn=cfg['errors_warn'] if 'errors' in field or 'drops' in field else None
                    crit=cfg['errors_crit'] if warn is not None else None
                    add(metric('network',entity,label,rate*scale if rate is not None else None,unit,status,
                               'Zähler wird nicht geliefert.' if missing else 'Warte auf zwei vergleichbare Zählerstände; bei 32-Bit-Zählern muss das Intervall kurz genug sein.' if rate is None else note,warn,crit))
                for f,label in [('rx','Auslastung Empfang'),('tx','Auslastung Versand')]:
                    value=rates.get(f)*8/speed*100 if speed and rates.get(f) is not None else None
                    add(metric('network',entity,label,value,'%',None if value is not None else 'unavailable' if not speed else 'pending',
                               '' if speed else 'Keine Portgeschwindigkeit geliefert. Unter Einrichten kann sie angegeben werden.',cfg['net_warn'],cfg['net_crit']))
                if not enabled:
                    for m in observed.values():
                        if m['category']=='network' and m['entity']==entity:m['status']='paused'
            for disk in result.get('disk_counters',[]) if cfg['disk_io'] else []:
                old,seconds=baseline('io:'+disk['name'],disk)
                rates={k:counter_rate(old.get(k),disk.get(k),seconds) if old else None for k in ('read_bytes','write_bytes','reads','writes','busy_ms','read_ms','write_ms')}
                for field,label,unit,factor in [('read_bytes','Lesen','MiB/s',1/1048576),('write_bytes','Schreiben','MiB/s',1/1048576),
                                              ('reads','Leseoperationen','IOPS',1),('writes','Schreiboperationen','IOPS',1),('busy_ms','Beschäftigungszeit','%',.1)]:
                    v=rates[field]*factor if rates[field] is not None else None
                    if field=='busy_ms' and v is not None:v=min(100,v)
                    add(metric('disk_io',disk['name'],label,v,unit,None if v is not None else 'pending',
                               'Warte auf zweiten Zählerstand.' if v is None else '',cfg['io_warn'] if field=='busy_ms' else None,cfg['io_crit'] if field=='busy_ms' else None))
                ops=(rates['reads'] or 0)+(rates['writes'] or 0)
                latency=((rates['read_ms']+rates['write_ms'])/ops if ops else 0) if rates['read_ms'] is not None and rates['write_ms'] is not None else None
                add(metric('disk_io',disk['name'],'Mittlere E/A-Dauer',latency,'ms',None if latency is not None else 'pending'))
            for category,on in active.items():
                if on and not any(m['category']==category for m in observed.values()):
                    add(metric(category,CATEGORY[category],'Verfügbarkeit',None,'','unknown','Keine unterstützten Messwerte geliefert. Geräteunterstützung und Leserechte prüfen.'))
        else:
            db.execute('DELETE FROM counter_baselines WHERE target_id=?',(target['id'],))
        for key,m in before.items():
            obsolete=(not active.get(m['category']) or m['category']=='process' and m['entity'] not in cfg['processes'] or m['category']=='service' and m['entity'] not in cfg['services'])
            replacement=(m['channel']=='Verfügbarkeit' and any(v['category']==m['category'] and v['channel']!='Verfügbarkeit' for v in observed.values()))
            if obsolete or replacement:
                if replacement:db.execute('DELETE FROM extended_metrics WHERE id=?',(m['id'],))
                else:db.execute("UPDATE extended_metrics SET enabled=0,status='paused' WHERE id=?",(m['id'],))
                continue
            if key not in observed:
                observed[key]=dict(key=key,category=m['category'],entity=m['entity'],channel=m['channel'],label=m['label'],value=None,unit=m['unit'],status='unknown',message=result.get('message') or 'Wird nicht mehr geliefert.',warn=m['warn'],critical=m['critical'])
        statuses=[]
        for key,m in observed.items():
            if not active.get(m['category']):continue
            enabled=not (m['category']=='network' and not cfg['interfaces'].get(m['entity'],{}).get('enabled',True))
            if not enabled:m['status']='paused'
            fields=('category','entity','channel','label','value','unit','status','message','warn','critical')
            values=tuple(m[k] for k in fields)+(int(enabled),now)
            if key in before:
                mid=before[key]['id'];db.execute('UPDATE extended_metrics SET '+','.join(k+'=?' for k in fields)+',enabled=?,last_checked=? WHERE id=?',values+(mid,))
            else:
                mid=db.execute('INSERT INTO extended_metrics('+','.join(fields)+',enabled,last_checked,target_id,metric_key) VALUES('+','.join('?' for _ in range(14))+')',values+(target['id'],key)).lastrowid
            if enabled:
                statuses.append(m)
                db.execute('INSERT INTO extended_samples(metric_id,time,value,status) VALUES(?,?,?,?)',(mid,now,m['value'],m['status']))
                if m['status']!=(before.get(key) or {}).get('status') and m['status'] in ('up','warning','critical','unknown'):
                    db.execute('INSERT INTO events(time,name,kind,message) VALUES(?,?,?,?)',(now,target['device_name']+' · '+m['label'],{'critical':'down','unknown':'error'}.get(m['status'],m['status']),
                               m['message'] or (str(round(m['value'],2))+' '+m['unit'] if m['value'] is not None else 'Kein Messwert')))
        return statuses
