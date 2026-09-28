"""Groups and transactional, previewed changes across devices."""
import hashlib
import hmac
import json
import sqlite3
from .resources import DEFAULTS, SECRETS


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def ids(value):
    from .core import integer
    if not isinstance(value, list) or not 1 <= len(value) <= 2000:
        raise ValueError('Bitte 1 bis 2.000 Geräte auswählen.')
    return sorted(set(integer(v, 1, 2147483647, 'Gerät') for v in value))


class FleetStore:
    def init_fleet(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS device_groups(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS group_members(group_id INTEGER NOT NULL REFERENCES device_groups(id) ON DELETE CASCADE,
              device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,PRIMARY KEY(group_id,device_id));
            CREATE TABLE IF NOT EXISTS templates(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,
              config TEXT NOT NULL,credentials TEXT NOT NULL DEFAULT '{}',revision INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS template_members(template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
              device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,revision INTEGER NOT NULL,
              mapping TEXT NOT NULL,PRIMARY KEY(template_id,device_id));
            ''')

    def fleet_state(self):
        templates = self.rows('SELECT id,name,revision,config,credentials FROM templates ORDER BY name COLLATE NOCASE')
        for t in templates:
            config = json.loads(t.pop('config'))
            t['has_credentials'] = bool(json.loads(t.pop('credentials')))
            t['services'] = config['services']
            t['resource'] = config['resource']
            t['integrations'] = config.get('integrations',[])
        return dict(groups=self.rows('SELECT * FROM device_groups ORDER BY name COLLATE NOCASE'),
                    group_members=self.rows('SELECT * FROM group_members'), templates=templates,
                    template_members=self.rows('SELECT template_id,device_id,revision FROM template_members'))

    def save_group(self, data):
        from .core import integer
        name = str(data.get('name', '')).strip()
        if not 1 <= len(name) <= 120:
            raise ValueError('Gruppenname: 1 bis 120 Zeichen.')
        with self.connect() as db:
            try:
                if data.get('id'):
                    ident = integer(data['id'], 1, 2147483647, 'Gruppe')
                    if not db.execute('UPDATE device_groups SET name=? WHERE id=?', (name, ident)).rowcount:
                        raise ValueError('Gruppe nicht gefunden.')
                else:
                    ident = db.execute('INSERT INTO device_groups(name) VALUES(?)', (name,)).lastrowid
            except sqlite3.IntegrityError:
                raise ValueError('Eine Gruppe mit diesem Namen existiert bereits.')
        return dict(id=ident)

    def save_template(self, data):
        from .core import integer
        ident = integer(data['id'], 1, 2147483647, 'Vorlage') if data.get('id') else None
        source = integer(data.get('device_id'), 1, 2147483647, 'Vorlagengerät')
        name = str(data.get('name', '')).strip()
        if not 1 <= len(name) <= 120:
            raise ValueError('Vorlagenname: 1 bis 120 Zeichen.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            device = db.execute('SELECT * FROM devices WHERE id=?', (source,)).fetchone()
            if not device:
                raise ValueError('Vorlagengerät nicht gefunden.')
            services = []
            fields = ('name','type','url','port','expected_codes','verify_tls','interval','timeout','threshold','enabled')
            for row in db.execute('SELECT * FROM services WHERE device_id=? ORDER BY id', (source,)):
                s = {k: row[k] for k in fields}
                s['key'] = str(row['id'])
                if s['type'] == 'http':
                    from urllib.parse import urlsplit, urlunsplit
                    u = urlsplit(s['url'])
                    if u.hostname == device['address']:
                        s['url'] = urlunsplit((u.scheme, '{address}'+(':'+str(u.port) if u.port else ''), u.path, u.query, ''))
                services.append(s)
            row = db.execute('SELECT * FROM resource_targets WHERE device_id=?', (source,)).fetchone()
            resource, credentials = None, {}
            if row:
                resource = {k: row[k] for k in DEFAULTS if k not in SECRETS and k != 'ssh_host_key'}
                resource['enabled'] = row['enabled']
                resource['advanced'] = json.loads(row['advanced'])
                # Interface identities belong to their device, never to a template.
                resource['advanced']['interfaces'] = {}
                if data.get('include_credentials') is True:
                    credentials = {k: row[k] for k in SECRETS if row[k]}
            from .integrations import SECRETS as EXTRA_SECRETS
            integrations=[]; extra_credentials={}
            for row in db.execute('SELECT * FROM integration_targets WHERE device_id=? ORDER BY id',(source,)):
                cfg=json.loads(row['config']); key='integration:'+str(row['id'])
                if data.get('include_credentials') is True:
                    extra_credentials[key]={k:cfg.get(k,'') for k in EXTRA_SECRETS if cfg.get(k)}
                for k in EXTRA_SECRETS:
                    if k in cfg:cfg[k]=''
                if cfg['host']==device['address']:cfg['host']='{address}'
                if 'fingerprint' in cfg:cfg['fingerprint']=''
                if 'expected_running' in cfg:cfg['expected_running']=[]
                integrations.append(dict(key=key,config=cfg,**{k:row[k] for k in ('name','kind','enabled','interval','timeout','threshold')}))
            if extra_credentials:credentials['__integrations__']=extra_credentials
            config = packed(dict(services=services, resource=resource,integrations=integrations))
            try:
                if ident:
                    if not db.execute('UPDATE templates SET name=?,config=?,credentials=?,revision=revision+1 WHERE id=?',
                                      (name, config, packed(credentials), ident)).rowcount:
                        raise ValueError('Vorlage nicht gefunden.')
                else:
                    ident = db.execute('INSERT INTO templates(name,config,credentials) VALUES(?,?,?)',
                                       (name, config, packed(credentials))).lastrowid
            except sqlite3.IntegrityError:
                raise ValueError('Eine Vorlage mit diesem Namen existiert bereits.')
        return dict(id=ident)

    def fleet_change(self, data, apply=False):
        from .core import integer
        from .setup import configuration_token
        chosen = ids(data.get('ids'))
        action = data.get('action')
        allowed = ('group_add','group_remove','pause','resume','rules','template')
        if action not in allowed:
            raise ValueError('Unbekannte Mehrfachaktion.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            devices = [db.execute('SELECT * FROM devices WHERE id=?', (d,)).fetchone() for d in chosen]
            if any(d is None for d in devices):
                raise ValueError('Ein ausgewähltes Gerät wurde gelöscht. Auswahl aktualisieren.')
            if action=='resume':
                for device in devices:self.require_device_license(device['id'],db)
            tokens = []
            for d in devices:
                tokens.append(configuration_token(d, db.execute('SELECT * FROM services WHERE device_id=?', (d['id'],)),
                                                  db.execute('SELECT * FROM resource_targets WHERE device_id=?', (d['id'],))))
            template = None
            if action == 'template':
                tid = integer(data.get('template_id'), 1, 2147483647, 'Vorlage')
                template = db.execute('SELECT * FROM templates WHERE id=?', (tid,)).fetchone()
                if not template:
                    raise ValueError('Vorlage nicht gefunden.')
                tokens.append(template['revision'])
            if action.startswith('group_'):
                gid = integer(data.get('group_id'), 1, 2147483647, 'Gruppe')
                if not db.execute('SELECT 1 FROM device_groups WHERE id=?', (gid,)).fetchone():
                    raise ValueError('Gruppe nicht gefunden.')
            body = {k: v for k, v in data.items() if k != 'preview_token'}
            token = hashlib.sha256(packed([body, tokens]).encode()).hexdigest()
            if apply and not hmac.compare_digest(str(data.get('preview_token', '')), token):
                raise ValueError('Auswahl oder Einstellungen haben sich geändert. Bitte Vorschau erneut laden.')
            reports = []
            for d in devices:
                did = d['id']; report = dict(id=did, name=d['name'], address=d['address'], added=0, updated=0, resource=False)
                if action.startswith('group_'):
                    if action == 'group_add':
                        db.execute('INSERT OR IGNORE INTO group_members VALUES(?,?)', (gid,did))
                    else:
                        db.execute('DELETE FROM group_members WHERE group_id=? AND device_id=?', (gid,did))
                    db.execute('UPDATE devices SET revision=revision+1 WHERE id=?',(did,))
                elif action in ('pause','resume'):
                    db.execute('UPDATE devices SET enabled=?,revision=revision+1 WHERE id=?', (int(action=='resume'),did))
                    for table in ('services','resource_targets','integration_targets'):
                        db.execute("UPDATE "+table+" SET revision=revision+1,next_check=0,status='pending',failures=0 WHERE device_id=?", (did,))
                elif action == 'rules':
                    values = data.get('rules', {})
                    if not isinstance(values, dict) or not values:
                        raise ValueError('Mindestens eine gemeinsame Prüfregel angeben.')
                    advanced_fields={'net_warn','net_crit','errors_warn','errors_crit','io_warn','io_crit','temp_warn','temp_crit'}
                    if set(values)-({'interval','timeout','threshold','cpu_warn','cpu_crit','ram_warn','ram_crit','disk_warn','disk_crit'}|advanced_fields):
                        raise ValueError('Unbekannte Prüfregel.')
                    for s in list(db.execute('SELECT * FROM services WHERE device_id=?', (did,))):
                        v = {k:values[k] for k in ('interval','timeout','threshold') if k in values}
                        if v:
                            self.save_service({**dict(s),**v},_db=db);report['updated']+=1
                    r = db.execute('SELECT * FROM resource_targets WHERE device_id=?', (did,)).fetchone()
                    if r:
                        self.save_resource({**dict(r),**values,'advanced':{**json.loads(r['advanced']),**{k:v for k,v in values.items() if k in advanced_fields}}},_db=db);report['resource']=True
                    extra=[]
                    for i in db.execute('SELECT * FROM integration_targets WHERE device_id=?',(did,)):
                        value=dict(i);value['config']=json.loads(i['config'])
                        for k in ('interval','timeout','threshold'):
                            if k in values:value[k]=values[k]
                        if i['kind'] in ('windows','vmware'):
                            value['config'].update({k:v for k,v in values.items() if k in ('cpu_warn','cpu_crit','ram_warn','ram_crit','disk_warn','disk_crit')})
                        extra.append(value);report['updated']+=1
                    self.save_integrations(db,d,extra)
                elif action == 'template':
                    config=json.loads(template['config']);credentials=json.loads(template['credentials'])
                    link=db.execute('SELECT * FROM template_members WHERE template_id=? AND device_id=?',(template['id'],did)).fetchone()
                    mapping=json.loads(link['mapping']) if link else {}
                    existing={s['id']:dict(s) for s in db.execute('SELECT * FROM services WHERE device_id=?',(did,))}
                    newmap={};targets=[]
                    for s in config['services']:
                        value={**s,'device_id':did}
                        value['url']=value['url'].replace('{address}','['+d['address']+']' if ':' in d['address'] else d['address'])
                        def signature(row):
                            return (row['type'],row['url'] if row['type']=='http' else row['port'] if row['type']=='tcp' else '')
                        sid=mapping.get(s['key'])
                        if sid not in existing:
                            sid=next((i for i,e in existing.items() if i not in newmap.values() and signature(e)==signature(value)),None)
                        value['id']=sid
                        saved=self.save_service(value,_db=db)
                        db.execute("UPDATE services SET enabled=?,revision=revision+1,status='pending',next_check=0,failures=0 WHERE id=? AND enabled!=?",(s['enabled'],saved,s['enabled']))
                        newmap[s['key']]=saved;report['updated' if sid else 'added']+=1
                        targets.append(value['url'] if s['type']=='http' else 'TCP '+str(s['port']) if s['type']=='tcp' else 'Ping')
                    if db.execute('SELECT COUNT(*) FROM services WHERE device_id=?',(did,)).fetchone()[0]>500:
                        raise ValueError(d['name']+': Mit dieser Vorlage würden mehr als 500 Dienste eingerichtet.')
                    report['targets']=targets
                    if config['resource']:
                        r=db.execute('SELECT * FROM resource_targets WHERE device_id=?',(did,)).fetchone()
                        value={**(dict(r) if r else {}),**config['resource'],**{k:v for k,v in credentials.items() if k!='__integrations__'},'id':r['id'] if r else None,'device_id':did}
                        if r:
                            # Port selections are specific to each destination.
                            value['advanced']={**value['advanced'],'interfaces':json.loads(r['advanced']).get('interfaces',{})}
                        if value['method']=='ssh':
                            value['ssh_host_key']=(data.get('host_keys') or {}).get(str(did)) or (r['ssh_host_key'] if r and r['method']=='ssh' and r['port']==value['port'] else '')
                        try:
                            rid=self.save_resource(value,_db=db)
                        except ValueError as exc:
                            raise ValueError(d['name']+': '+str(exc))
                        db.execute("UPDATE resource_targets SET enabled=?,revision=revision+1,status='pending',next_check=0,failures=0 WHERE id=? AND enabled!=?",(value['enabled'],rid,value['enabled']))
                        report['resource']=True
                    extra_existing={r['id']:dict(r) for r in db.execute('SELECT * FROM integration_targets WHERE device_id=?',(did,))}
                    desired=[]; template_keys=[]; claimed=set()
                    for item in config.get('integrations',[]):
                        value={k:v for k,v in item.items() if k!='key'};cfg=dict(value['config'])
                        cfg['host']=cfg['host'].replace('{address}',d['address'])
                        iid=mapping.get(item['key'])
                        if iid not in extra_existing:
                            iid=next((i for i,e in extra_existing.items() if i not in claimed and e['kind']==value['kind'] and e['name']==value['name'] and json.loads(e['config'])['host']==cfg['host']),None)
                        if iid:
                            oldcfg=json.loads(extra_existing[iid]['config'])
                            if (oldcfg['host'],oldcfg['port'])==(cfg['host'],cfg['port']) and 'fingerprint' in cfg:cfg['fingerprint']=oldcfg.get('fingerprint','')
                            claimed.add(iid)
                        cfg.update(credentials.get('__integrations__',{}).get(item['key'],{}))
                        value.update(id=iid,config=cfg);desired.append(value);template_keys.append(item['key'])
                        report['updated' if iid else 'added']+=1
                        targets.append(value['name']+' · '+cfg['host'])
                    for iid,e in extra_existing.items():
                        if iid not in claimed:desired.append({**e,'config':json.loads(e['config'])})
                    try:saved=self.save_integrations(db,d,desired)
                    except ValueError as exc:raise ValueError(d['name']+': '+str(exc))
                    newmap.update(zip(template_keys,saved))
                    db.execute('INSERT INTO template_members VALUES(?,?,?,?) ON CONFLICT(template_id,device_id) DO UPDATE SET revision=excluded.revision,mapping=excluded.mapping',
                               (template['id'],did,template['revision'],packed(newmap)))
                reports.append(report)
            if not apply:
                db.rollback()
            return dict(preview_token=token,devices=reports,count=len(reports),applied=apply)

    def delete_fleet_item(self, kind, ident):
        from .core import integer
        table={'group':'device_groups','template':'templates'}.get(kind)
        if not table: raise ValueError('Unbekanntes Objekt.')
        with self.connect() as db:
            if kind=='group':
                db.execute('UPDATE devices SET revision=revision+1 WHERE id IN (SELECT device_id FROM group_members WHERE group_id=?)',(ident,))
            db.execute('DELETE FROM '+table+' WHERE id=?',(integer(ident,1,2147483647,'Kennung'),))
        return dict(ok=True)
