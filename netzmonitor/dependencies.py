"""Explicit reachability dependencies. A blocked device never appears healthy."""
import time


class DependencyStore:
    def init_dependencies(self):
        with self.connect() as db:
            columns={r['name'] for r in db.execute('PRAGMA table_info(devices)')}
            if 'blocked' not in columns:db.execute('ALTER TABLE devices ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0')
            if 'block_revision' not in columns:db.execute('ALTER TABLE devices ADD COLUMN block_revision INTEGER NOT NULL DEFAULT 0')
            if 'block_reason' not in columns:db.execute("ALTER TABLE devices ADD COLUMN block_reason TEXT NOT NULL DEFAULT ''")
            db.execute('''CREATE TABLE IF NOT EXISTS device_dependencies(
                device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
                service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE RESTRICT)''')

    def save_dependency(self,db,device_id,service_id):
        from .core import integer
        previous=db.execute('SELECT service_id FROM device_dependencies WHERE device_id=?',(device_id,)).fetchone()
        if service_id in (None,'',0,'0'):
            if previous:
                db.execute('DELETE FROM device_dependencies WHERE device_id=?',(device_id,))
                db.execute('UPDATE devices SET revision=revision+1 WHERE id=?',(device_id,))
            return
        service_id=integer(service_id,1,2147483647,'Übergeordnete Prüfung')
        source=db.execute('SELECT device_id,type FROM services WHERE id=?',(service_id,)).fetchone()
        if not source or source['type'] not in ('ping','tcp','http'):raise ValueError('Eine vorhandene Ping-, TCP- oder HTTP-Prüfung als Abhängigkeit auswählen.')
        links={r['device_id']:r['parent_id'] for r in db.execute('SELECT x.device_id,s.device_id AS parent_id FROM device_dependencies x JOIN services s ON s.id=x.service_id')}
        links[device_id]=source['device_id'];seen=set();current=device_id
        while current in links:
            if current in seen:raise ValueError('Diese Abhängigkeit würde einen Kreis bilden. Ein Gerät darf nicht von sich selbst abhängen.')
            seen.add(current);current=links[current]
        if not previous or previous['service_id']!=service_id:
            db.execute('INSERT INTO device_dependencies VALUES(?,?) ON CONFLICT(device_id) DO UPDATE SET service_id=excluded.service_id',(device_id,service_id))
            db.execute('UPDATE devices SET revision=revision+1 WHERE id=?',(device_id,))

    def protect_dependency_source(self,db,device_id=None,service_id=None):
        query='''SELECT d.name FROM device_dependencies x JOIN devices d ON d.id=x.device_id
                 JOIN services s ON s.id=x.service_id WHERE '''
        rows=db.execute(query+('s.device_id=?' if device_id is not None else 's.id=?'),
                        (device_id if device_id is not None else service_id,)).fetchall()
        if rows:raise ValueError('Diese Prüfung wird als Abhängigkeit verwendet. Zuerst die Abhängigkeit bei '+', '.join(r['name'] for r in rows[:5])+' ändern oder entfernen.')

    def refresh_dependencies(self):
        now=time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.refresh_license_access(db)
            devices={r['id']:dict(r) for r in db.execute('SELECT id,name,enabled,blocked,block_reason FROM devices')}
            parents={r['child_id']:dict(r) for r in db.execute('''SELECT x.device_id AS child_id,s.*,
                d.name AS parent_name,d.enabled AS parent_enabled,d.license_blocked AS parent_license_blocked FROM device_dependencies x
                JOIN services s ON s.id=x.service_id JOIN devices d ON d.id=s.device_id''')}
            memo={}
            def reason(did):
                trail=[];seen=set();current=did
                while current not in memo and current in parents:
                    if current in seen:
                        memo[current]='Zyklische Geräteabhängigkeit. Konfiguration prüfen.'
                        break
                    seen.add(current);trail.append(current);current=parents[current]['device_id']
                message=memo.get(current,'')
                for child_id in reversed(trail):
                    p=parents[child_id]
                    if not message:
                        fresh=p['last_checked'] and now-p['last_checked']<=max(60,p['interval']+p['timeout']+30)
                        label=p['parent_name']+' · '+p['name']
                        if p['parent_license_blocked']:message='Übergeordnetes Gerät nicht freigeschaltet: '+label
                        elif not p['parent_enabled'] or not p['enabled']:message='Übergeordnete Prüfung pausiert: '+label
                        elif p['status']=='down':message='Übergeordnete Prüfung ausgefallen: '+label
                        elif p['status'] in ('pending','error') or not fresh or not p['last_seen']:message='Warte auf gültige übergeordnete Prüfung: '+label
                    memo[child_id]=message
                memo.setdefault(did,message)
                return memo[did]
            for did,d in devices.items():
                message=reason(did);blocked=int(bool(message))
                if (blocked,message)==(d['blocked'],d['block_reason']):continue
                db.execute('UPDATE devices SET blocked=?,block_reason=?,block_revision=block_revision+1 WHERE id=?',(blocked,message,did))
                for table in ('services','resource_targets','integration_targets'):
                    db.execute('UPDATE '+table+" SET status='pending',failures=0,next_check=0 WHERE device_id=?",(did,))
                if d['enabled']:
                    db.execute('INSERT INTO events(time,name,kind,message) VALUES(?,?,?,?)',
                        (now,d['name'],'blocked' if blocked else 'pending',message if blocked else 'Abhängigkeit wieder verfügbar. Eigene Prüfungen werden erneut ausgeführt.'))
