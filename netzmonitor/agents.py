"""Equal-access agent accounts, persisted in the existing SQLite database."""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time

from .i18n import normalize_language


def set_password(record, password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('Das Passwort muss 12 bis 256 Zeichen enthalten.')
    record['salt'] = secrets.token_hex(24)
    record['password_hash'] = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), bytes.fromhex(record['salt']), 310000).hex()


def valid_password(record, password):
    password = password if isinstance(password, str) else ''
    hashed = hashlib.pbkdf2_hmac('sha256', password[:256].encode('utf-8'),
                               bytes.fromhex(record['salt']), 310000).hex()
    return hmac.compare_digest(hashed, record['password_hash']) and len(password) <= 256


class Agents:
    def __init__(self, store, config):
        self.store = store
        self.default_language = normalize_language(config.get('language', 'de'))
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                name TEXT NOT NULL,
                language TEXT NOT NULL,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                revision INTEGER NOT NULL DEFAULT 1,
                auth_revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL)''')
            db.execute('BEGIN IMMEDIATE')
            # A marker prevents resurrection of a deliberately deleted legacy account.
            if not db.execute("SELECT 1 FROM settings WHERE key='agents_migrated'").fetchone():
                db.execute('''INSERT INTO agents(username,name,language,salt,password_hash,created_at)
                    VALUES(?,?,?,?,?,?)''', ('admin', 'admin', self.default_language,
                    config['salt'], config['password_hash'], time.time()))
                db.execute("INSERT INTO settings(key,value) VALUES('agents_migrated','true')")
        self.dummy = {}
        set_password(self.dummy, secrets.token_urlsafe(32))

    @staticmethod
    def public(row):
        return {key: row[key] for key in ('id', 'username', 'name', 'language', 'enabled', 'revision')}

    def get(self, ident):
        rows = self.store.rows('SELECT * FROM agents WHERE id=?', (ident,))
        return rows[0] if rows else None

    def authenticate(self, username, password):
        rows = self.store.rows('SELECT * FROM agents WHERE username=? COLLATE NOCASE',
                               (str(username).strip(),))
        row = rows[0] if rows else None
        valid = valid_password(row or self.dummy, password)
        return row if row and row['enabled'] and valid else None

    def list(self):
        return [self.public(row) for row in self.store.rows('SELECT * FROM agents ORDER BY username COLLATE NOCASE')]

    def save(self, body, actor):
        username = str(body.get('username', '')).strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._@-]{0,79}', username):
            raise ValueError('Benutzername: 1 bis 80 Zeichen; Buchstaben, Zahlen, Punkt, Bindestrich, Unterstrich und @.')
        name = str(body.get('name', '')).strip() or username
        if len(name) > 120:
            raise ValueError('Der Name darf höchstens 120 Zeichen enthalten.')
        language = normalize_language(body.get('language', self.default_language))
        enabled = body.get('enabled', True)
        if enabled not in (True, False, 0, 1, '0', '1'):
            raise ValueError('Ungültige Eingabe.')
        enabled = int(enabled in (True, 1, '1'))
        ident = int(body.get('id') or 0)
        password = body.get('password', '')
        credentials = {}
        if password or not ident:
            set_password(credentials, password)
        try:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if ident:
                    old = db.execute('SELECT * FROM agents WHERE id=?', (ident,)).fetchone()
                    if not old:
                        raise ValueError('Agent nicht gefunden.')
                    if int(body.get('revision', 0)) != old['revision']:
                        raise ValueError('Der Agent wurde inzwischen geändert. Bitte neu laden.')
                    if not enabled:
                        self.protect(db, ident, actor)
                    invalidate = bool(credentials) or old['enabled'] != enabled or old['username'] != username
                    db.execute('''UPDATE agents SET username=?,name=?,language=?,enabled=?,
                        salt=?,password_hash=?,revision=revision+1,auth_revision=auth_revision+? WHERE id=?''',
                        (username, name, language, enabled, credentials.get('salt', old['salt']),
                         credentials.get('password_hash', old['password_hash']), int(invalidate), ident))
                else:
                    ident = db.execute('''INSERT INTO agents(username,name,language,salt,password_hash,enabled,created_at)
                        VALUES(?,?,?,?,?,?,?)''', (username, name, language, credentials['salt'],
                        credentials['password_hash'], enabled, time.time())).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError('Dieser Benutzername ist bereits vergeben.')
        return self.public(self.get(ident))

    @staticmethod
    def protect(db, ident, actor):
        if ident == actor:
            raise ValueError('Das eigene Konto kann nicht deaktiviert oder gelöscht werden.')
        if not db.execute('SELECT 1 FROM agents WHERE enabled=1 AND id<>?', (ident,)).fetchone():
            raise ValueError('Mindestens ein aktiver Agent muss erhalten bleiben.')

    def delete(self, body, actor):
        ident = int(body.get('id') or 0)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.protect(db, ident, actor)
            result = db.execute('DELETE FROM agents WHERE id=? AND revision=?',
                                (ident, int(body.get('revision', 0))))
            if not result.rowcount:
                raise ValueError('Der Agent wurde inzwischen geändert. Bitte neu laden.')
        return {'ok': True}

    def language(self, ident, language):
        language = normalize_language(language)
        with self.store.connect() as db:
            db.execute('UPDATE agents SET language=?,revision=revision+1 WHERE id=?', (language, ident))
        return self.public(self.get(ident))

    def password(self, ident, current, password, verify=True):
        old = self.get(ident)
        if not old or (verify and not valid_password(old, current)):
            raise ValueError('Das bisherige Passwort ist nicht korrekt.')
        credentials = {}
        set_password(credentials, password)
        with self.store.connect() as db:
            result = db.execute('''UPDATE agents SET salt=?,password_hash=?,revision=revision+1,
                auth_revision=auth_revision+1 WHERE id=? AND auth_revision=?''',
                (credentials['salt'], credentials['password_hash'], ident, old['auth_revision']))
            if not result.rowcount:
                raise ValueError('Der Agent wurde inzwischen geändert. Bitte neu laden.')
        return {'ok': True}
