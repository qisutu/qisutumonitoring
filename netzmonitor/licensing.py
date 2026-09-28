"""Offline entitlements, explicit device selection and runtime enforcement."""
import base64
import json
from pathlib import Path
import time
import uuid
from .license_format import PLANS, iso_date, today, verify_document

FREE_DEVICES = 10
PUBLIC_KEY = Path(__file__).with_name('license-public.pem')


class LicenseStore:
    def init_license(self):
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS license_state (
                id INTEGER PRIMARY KEY CHECK(id=1), installation_id TEXT NOT NULL,
                document TEXT NOT NULL DEFAULT '', imported_at REAL,
                revision INTEGER NOT NULL DEFAULT 0)''')
            db.execute('INSERT OR IGNORE INTO license_state(id,installation_id) VALUES(1,?)', (str(uuid.uuid4()),))
            if 'license_blocked' not in {r['name'] for r in db.execute('PRAGMA table_info(devices)')}:
                db.execute('ALTER TABLE devices ADD COLUMN license_blocked INTEGER NOT NULL DEFAULT 0')
            db.execute('''CREATE TABLE IF NOT EXISTS license_selections (
                device_limit INTEGER PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 1)''')
            db.execute('''CREATE TABLE IF NOT EXISTS license_selection_devices (
                device_limit INTEGER NOT NULL REFERENCES license_selections(device_limit) ON DELETE CASCADE,
                device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                PRIMARY KEY(device_limit,device_id))''')
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS license_recipient (
                id INTEGER PRIMARY KEY CHECK(id=1), private_key TEXT NOT NULL,
                public_key TEXT NOT NULL)''')
        self.refresh_license_access()

    def _license_document(self, raw, expected_id):
        if not isinstance(raw, str):
            raise ValueError('Bitte eine Freischaltdatei auswählen.')
        try:
            pem = PUBLIC_KEY.read_text(encoding='ascii')
        except (OSError, UnicodeError):
            raise ValueError('Der öffentliche Prüfschlüssel fehlt oder ist beschädigt. Bitte das Programmpaket erneut installieren.') from None
        document = verify_document(raw, pem)
        if document['payload']['installation_id'] != expected_id:
            raise ValueError('Diese Freischaltdatei gehört zu einer anderen Installation. Bitte dem Hersteller die hier angezeigte Installationskennung mitteilen.')
        return document

    def license_status(self, db=None):
        with self.connect(db) as connection:
            return self._license_context(connection)[0]

    def _selection(self, db, limit, devices):
        row = db.execute('SELECT revision FROM license_selections WHERE device_limit=?', (limit,)).fetchone()
        chosen = {r[0] for r in db.execute('SELECT device_id FROM license_selection_devices WHERE device_limit=?', (limit,))} if row else (devices if len(devices)<=limit else set())
        return dict(limit=limit, revision=row['revision'] if row else 0, confirmed=bool(row),
                    ids=sorted(chosen & devices), required=not row and len(devices)>limit)

    def _license_context(self, db, document=None):
        row = dict(db.execute('SELECT * FROM license_state WHERE id=1').fetchone())
        if document is not None:row['document']=document
        devices = {r[0] for r in db.execute('SELECT id FROM devices')}
        info = self._license_status(row, len(devices))
        limit = info['device_limit']
        selection = self._selection(db, limit, devices) if limit is not None else None
        allowed = set(selection['ids']) if selection else devices
        info.update(selection=selection, fallback_selection=self._selection(db,FREE_DEVICES,devices),
                    permitted_devices=len(allowed), locked_devices=len(devices-allowed),
                    selection_required=bool(selection and selection['required']),
                    remaining_devices=None if limit is None else max(0,limit-len(allowed)))
        info['can_add_device'] = not info['selection_required'] and (limit is None or len(allowed)<limit)
        if info['selection_required']:
            info['message'] += (' ' if info['message'] else '') + 'Bitte unter „Freischaltung“ höchstens %s Geräte auswählen. Bis zur Auswahl sind alle Geräteprüfungen gesperrt.' % limit
        elif info['locked_devices']:
            info['message'] += (' ' if info['message'] else '') + '%s Geräte sind nicht freigeschaltet und werden nicht geprüft. Nur die ausgewählten Geräte bleiben nutzbar.' % info['locked_devices']
        return info, allowed

    def refresh_license_access(self, db=None):
        with self.connect(db) as connection:
            if db is None:connection.execute('BEGIN IMMEDIATE')
            info, allowed = self._license_context(connection)
            for row in connection.execute('SELECT id,license_blocked FROM devices').fetchall():
                blocked=int(row['id'] not in allowed)
                if row['license_blocked']==blocked:continue
                # Changing the device revision invalidates in-flight measurements as well.
                connection.execute('UPDATE devices SET license_blocked=?,revision=revision+1 WHERE id=?',(blocked,row['id']))
                if not blocked:
                    for table in ('services','resource_targets','integration_targets'):
                        connection.execute('UPDATE '+table+' SET next_check=0 WHERE device_id=?',(row['id'],))
            return info

    def license_allows(self, device_id, db=None):
        with self.connect(db) as connection:
            if db is None:connection.execute('BEGIN IMMEDIATE')
            self.refresh_license_access(connection)
            row=connection.execute('SELECT license_blocked FROM devices WHERE id=?',(device_id,)).fetchone()
            return bool(row and not row['license_blocked'])

    def require_device_license(self, device_id, db=None):
        if not self.license_allows(device_id, db):
            raise ValueError('Dieses Gerät ist nicht freigeschaltet. Unter „Freischaltung“ die verbleibenden Geräte auswählen oder den Servicevertrag verlängern.')

    def register_license_devices(self, db, ids):
        info=self.license_status(db)
        selection=info['selection']
        if selection and selection['confirmed']:
            if len(selection['ids'])+len(ids)>selection['limit']:
                raise ValueError('Gerätebegrenzung erreicht.')
            db.executemany('INSERT INTO license_selection_devices VALUES(?,?)',[(selection['limit'],did) for did in ids])
            db.execute('UPDATE license_selections SET revision=revision+1 WHERE device_limit=?',(selection['limit'],))
        self.refresh_license_access(db)

    def save_license_selection(self, data):
        limit, ids = data.get('limit'), data.get('ids')
        revision, license_revision = data.get('revision'), data.get('license_revision')
        if (type(limit) is not int or type(revision) is not int or type(license_revision) is not int or
                not isinstance(ids,list) or len(ids)>500 or any(type(i) is not int or i<1 for i in ids) or len(set(ids))!=len(ids)):
            raise ValueError('Ungültige Geräteauswahl.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            info=self.license_status(db)
            if limit not in {FREE_DEVICES,info['device_limit']} or len(ids)>limit:
                raise ValueError('Höchstens %s Geräte für diese Freischaltung auswählen.' % (info['device_limit'] or FREE_DEVICES))
            if license_revision!=info['revision']:
                raise ValueError('Der Vertrag wurde inzwischen geändert. Bitte die Auswahl neu laden.')
            selection=self._selection(db,limit,{r[0] for r in db.execute('SELECT id FROM devices')})
            if selection['revision']!=revision:
                raise ValueError('Die Geräteauswahl wurde inzwischen geändert. Bitte neu laden.')
            if any(not db.execute('SELECT 1 FROM devices WHERE id=?',(did,)).fetchone() for did in ids):
                raise ValueError('Ein ausgewähltes Gerät wurde gelöscht. Bitte die Auswahl neu laden.')
            db.execute('INSERT INTO license_selections VALUES(?,1) ON CONFLICT(device_limit) DO UPDATE SET revision=revision+1',(limit,))
            db.execute('DELETE FROM license_selection_devices WHERE device_limit=?',(limit,))
            db.executemany('INSERT INTO license_selection_devices VALUES(?,?)',[(limit,did) for did in ids])
            return self.refresh_license_access(db)

    def _license_status(self, row, count):
        current = today()
        result = dict(installation_id=row['installation_id'], revision=row['revision'],
                      status='free', plan='free', plan_label='Kostenlos', device_limit=FREE_DEVICES,
                      used_devices=count, customer='', contract_id='', valid_from=None,
                      valid_until=None, days_remaining=None, imported_at=row['imported_at'],
                      message='', licensed_device_limit=None)
        if row['document']:
            try:
                payload = self._license_document(row['document'], row['installation_id'])['payload']
                start, end = iso_date(payload['valid_from'], 'Vertragsbeginn'), iso_date(payload['valid_until'], 'Vertragsende')
                result.update(customer=payload['customer'], contract_id=payload['contract_id'],
                              valid_from=payload['valid_from'], valid_until=payload['valid_until'],
                              license_id=payload['license_id'], licensed_plan_label=PLANS[payload['plan']][1],
                              licensed_device_limit=payload['device_limit'], days_remaining=(end-current).days)
                if current < start:
                    result.update(status='not_yet_valid', message='Die Freischaltung ist noch nicht gültig. Bis zum Vertragsbeginn gilt die kostenlose Gerätezahl.')
                elif current > end:
                    result.update(status='expired', message='Der Servicevertrag ist abgelaufen. Es dürfen nur noch 10 ausgewählte Geräte überwacht werden.')
                else:
                    result.update(status='active', plan=payload['plan'], plan_label=PLANS[payload['plan']][1], device_limit=payload['device_limit'])
                    if result['days_remaining'] <= 30:
                        result['message'] = 'Die Freischaltung läuft in %s Tagen ab. Bitte rechtzeitig eine Verlängerungsdatei anfordern.' % result['days_remaining']
            except ValueError as exc:
                result.update(status='invalid', message=str(exc) + ' Es gilt die kostenlose Grenze von 10 Geräten.')
        limit = result['device_limit']
        result['remaining_devices'] = None if limit is None else max(0, limit-count)
        result['over_limit'] = limit is not None and count > limit
        result['can_add_device'] = limit is None or count < limit
        return result

    def check_device_capacity(self, db, additional):
        # Caller holds BEGIN IMMEDIATE, including batch imports. No race between count and insert.
        if additional <= 0:
            return
        info = self.license_status(db)
        if info['selection_required']:
            raise ValueError('Gerätebegrenzung: Bitte zuerst unter „Freischaltung“ die verbleibenden Geräte auswählen.')
        remaining = info['remaining_devices']
        if remaining is not None and additional > remaining:
            raise ValueError('Gerätebegrenzung: %s Geräte freigegeben, %s Plätze belegt, %s zusätzlich ausgewählt. Unter „Freischaltung“ die Geräteauswahl ändern oder den Vertrag erweitern.' % (info['device_limit'], info['permitted_devices'], additional))

    def license_request(self):
        from .license_envelope import generate_recipient
        with self.connect() as db:
            row=db.execute('SELECT public_key FROM license_recipient WHERE id=1').fetchone()
        if row is None:
            private,public=generate_recipient()
            with self.connect() as db:
                db.execute('INSERT OR IGNORE INTO license_recipient VALUES(1,?,?)',(private,public))
                row=db.execute('SELECT public_key FROM license_recipient WHERE id=1').fetchone()
        info=self.license_status()
        request=dict(format='netzmonitor-request-v2',product='netzmonitor',
                     installation_id=info['installation_id'],registered_devices=info['used_devices'],
                     encryption_public_key=row['public_key'])
        request['token']='NMREQ2.'+base64.urlsafe_b64encode(json.dumps(request,separators=(',',':')).encode('utf-8')).decode('ascii').rstrip('=')
        return request

    def _license_upload(self, data, db):
        from .license_envelope import TRANSPORT,decrypt_upload
        raw=data.get('file')
        if isinstance(raw,str) and raw.startswith(TRANSPORT):
            row=db.execute('SELECT private_key FROM license_recipient WHERE id=1').fetchone()
            if row is None:raise ValueError('Diese Datei gehört nicht zur aktuellen Installation. Bitte die aktuelle Installationskennung an den Hersteller übermitteln.')
            return decrypt_upload(raw,row['private_key'])
        return raw

    def preview_license(self, data, db=None):
        with self.connect(db) as connection:
            row = connection.execute('SELECT * FROM license_state WHERE id=1').fetchone()
            raw = self._license_upload(data,connection)
            payload = self._license_document(raw, row['installation_id'])['payload']
            current = today()
            if current < iso_date(payload['valid_from'], 'Vertragsbeginn'):
                raise ValueError('Diese Freischaltdatei ist noch nicht gültig. Bitte ab dem %s einspielen.' % payload['valid_from'])
            if current > iso_date(payload['valid_until'], 'Vertragsende'):
                raise ValueError('Diese Freischaltdatei ist bereits abgelaufen. Bitte eine aktuelle Verlängerungsdatei anfordern.')
            result = self._license_context(connection,raw)[0]
            result['replaces_existing'] = bool(row['document'])
            return result

    def import_license(self, data):
        revision = data.get('revision')
        if type(revision) is not int or revision < 0:
            raise ValueError('Bitte die Freischaltdatei zuerst prüfen.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM license_state WHERE id=1').fetchone()
            if revision != previous['revision']:
                raise ValueError('Die Freischaltung wurde inzwischen geändert. Bitte die Datei erneut prüfen.')
            data={**data,'file':self._license_upload(data,db)}
            self.preview_license(data, db)
            db.execute('UPDATE license_state SET document=?,imported_at=?,revision=revision+1 WHERE id=1', (data['file'], time.time()))
            return self.refresh_license_access(db)
