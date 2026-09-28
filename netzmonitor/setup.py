"""Save all checks of one device atomically, preserving identities and history."""
import hashlib
import hmac
import json
import re
import time


def configuration_token(device, services, resources):
    def version(row):
        return [row['id'], row['revision'], row['enabled']]
    data = [version(device), sorted(map(version, services)), sorted(map(version, resources))]
    return hashlib.sha256(json.dumps(data, separators=(',', ':')).encode()).hexdigest()


def save_configuration(store, data):
    from .core import integer
    ident = integer(data.get('id'), 1, 2147483647, 'Gerät')
    services = data.get('services')
    if not isinstance(services, list) or len(services) > 500 or 'resource' not in data:
        raise ValueError('Vollständige Gerätekonfiguration mit höchstens 500 Prüfungen übermitteln.')
    resource = data['resource']
    if resource is not None and not isinstance(resource, dict):
        raise ValueError('Ungültige Ressourcenkonfiguration.')
    request_id = data.get('request_id')
    if request_id is not None and (not isinstance(request_id,str) or not re.fullmatch(r'[a-fA-F0-9-]{36}',request_id)):
        raise ValueError('Ungültige Speicherkennung.')
    request_hash = hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM configuration_receipts WHERE created_at<?',(time.time()-86400,))
        if request_id:
            receipt=db.execute('SELECT * FROM configuration_receipts WHERE request_id=?',(request_id,)).fetchone()
            if receipt:
                if not hmac.compare_digest(receipt['request_hash'],request_hash):
                    raise ValueError('Die Speicherkennung wurde mit anderen Einstellungen erneut verwendet.')
                return {'id':receipt['device_id'],'saved':receipt['saved']}
        device = db.execute('SELECT * FROM devices WHERE id=?', (ident,)).fetchone()
        if not device:
            raise ValueError('Das Gerät wurde gelöscht. Bitte die Geräteliste neu laden.')
        previous = {s['id']: s for s in db.execute('SELECT * FROM services WHERE device_id=?', (ident,))}
        targets = list(db.execute('SELECT * FROM resource_targets WHERE device_id=?', (ident,)))
        token = configuration_token(device, previous.values(), targets)
        if not hmac.compare_digest(str(data.get('config_token', '')), token):
            raise ValueError('Die Gerätekonfiguration wurde zwischenzeitlich geändert. Bitte neu öffnen, bevor du speicherst.')
        store.save_device({'id': ident, 'name': data.get('name', device['name']),
                           'address': data.get('address', device['address'])}, _db=db)
        if 'group_ids' in data:
            if not isinstance(data['group_ids'],list) or len(data['group_ids'])>2000:
                raise ValueError('Ungültige Gruppenauswahl.')
            groups=set(integer(g,1,2147483647,'Gruppe') for g in data['group_ids'])
            if any(not db.execute('SELECT 1 FROM device_groups WHERE id=?',(g,)).fetchone() for g in groups):
                raise ValueError('Eine ausgewählte Gruppe wurde gelöscht.')
            if groups!={r['group_id'] for r in db.execute('SELECT group_id FROM group_members WHERE device_id=?',(ident,))}:
                db.execute('UPDATE devices SET revision=revision+1 WHERE id=?',(ident,))
            db.execute('DELETE FROM group_members WHERE device_id=?',(ident,))
            db.executemany('INSERT INTO group_members VALUES(?,?)',[(g,ident) for g in groups])
        retained = set()
        for index, values in enumerate(services, 1):
            if not isinstance(values, dict):
                raise ValueError('Ungültige Prüfung in Zeile %s.' % index)
            sid = integer(values['id'], 1, 2147483647, 'Prüfung') if values.get('id') else None
            if sid and (sid not in previous or sid in retained):
                raise ValueError('Prüfung gehört nicht zu diesem Gerät oder wurde doppelt angegeben.')
            enabled = integer(values.get('enabled', 1), 0, 1, 'Aktivierung')
            try:
                saved = store.save_service({**values, 'id': sid, 'device_id': ident}, _db=db)
            except ValueError as exc:
                raise ValueError('Prüfung %s (%s): %s' % (index, str(values.get('name', ''))[:120], exc))
            retained.add(saved)
            db.execute("UPDATE services SET enabled=?,revision=revision+1,status='pending',failures=0,next_check=0 WHERE id=? AND enabled!=?",
                       (enabled, saved, enabled))
        for removed in previous.keys() - retained:
            store.protect_dependency_source(db, service_id=removed)
            db.execute('DELETE FROM services WHERE id=?', (removed,))
        target = targets[0] if targets else None
        if resource is None:
            if target:
                db.execute('DELETE FROM resource_targets WHERE id=?', (target['id'],))
        else:
            rid = integer(resource['id'], 1, 2147483647, 'Ressourcenprüfung') if resource.get('id') else None
            if rid != (target['id'] if target else None):
                raise ValueError('Ressourcenprüfung gehört nicht zu diesem Gerät.')
            enabled = integer(resource.get('enabled', 1), 0, 1, 'Ressourcen-Aktivierung')
            if resource.get('keep_config'):
                if not target or enabled:
                    raise ValueError('Nur eine bestehende Ressourcenprüfung kann so pausiert werden.')
            else:
                rid = store.save_resource({**resource, 'id': rid, 'device_id': ident}, _db=db)
            db.execute("UPDATE resource_targets SET enabled=?,revision=revision+1,status='pending',failures=0,next_check=0 WHERE id=? AND enabled!=?",
                       (enabled, rid, enabled))
        if 'integrations' in data:
            updated = db.execute('SELECT * FROM devices WHERE id=?', (ident,)).fetchone()
            store.save_integrations(db, updated, data['integrations'])
        if 'dependency_service_id' in data:
            store.save_dependency(db, ident, data['dependency_service_id'])
        if request_id:
            db.execute('INSERT INTO configuration_receipts VALUES(?,?,?,?,?)',(request_id,request_hash,ident,len(retained),time.time()))
            db.execute('DELETE FROM configuration_receipts WHERE device_id=? AND request_id NOT IN (SELECT request_id FROM configuration_receipts WHERE device_id=? ORDER BY created_at DESC LIMIT 10)',(ident,ident))
    return {'id': ident, 'saved': len(retained)}
