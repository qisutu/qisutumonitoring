"""Authenticated, local-asset web interface served by bundled Tornado."""
import asyncio
import concurrent.futures
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

import tornado.httpserver
import tornado.web
from .core import Store, Engine, VERSION, integer, targets
from .agents import Agents, set_password, valid_password
from .i18n import LANGUAGES, catalog, translate

LOG = logging.getLogger('netzmonitor')
STATIC = Path(__file__).parent / 'static'


def read_config(data):
    return json.loads((Path(data) / 'config.json').read_text(encoding='utf-8'))


def write_config(data, config):
    path = Path(data) / 'config.json'
    temp = path.with_suffix('.tmp')
    with open(temp, 'w', encoding='utf-8') as out:
        os.chmod(temp, 0o600)
        json.dump(config, out, indent=2, ensure_ascii=False)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


class WebApp(tornado.web.Application):
    def __init__(self, data, engine):
        self.data, self.engine, self.store = Path(data), engine, engine.store
        self.sessions, self.attempts = {}, {}
        self.agents = Agents(self.store, read_config(data))
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix='api')
        self.inflight = 0
        super().__init__([(r'/api/(.*)', API), (r'/(.*)', Asset)], debug=False,
                         compress_response=True, max_body_size=2097152, autoreload=False)

    def dispatch(self, method, route, body, query):
        store = self.store
        if method == 'GET' and route == 'notifications':
            return store.notification_state()
        if method == 'POST' and route == 'notifications/save':
            with self.engine.notifications.lock:
                return store.save_notifications(body)
        if method == 'POST' and route == 'notifications/test':
            return store.notification_test(body)
        if method == 'GET' and route == 'license/request':
            return store.license_request()
        if method == 'GET' and route == 'state':
            result = store.state()
            result['engine_ok'] = self.engine.thread.is_alive() and time.time() - self.engine.heartbeat < 15
            result['ssh_available'] = all(__import__('shutil').which(name) for name in ('ssh','ssh-keyscan'))
            result['snmp_available'] = __import__('shutil').which('snmpbulkwalk') is not None
            result['ping_available'] = __import__('shutil').which('ping') is not None
            return result
        if method == 'GET' and route in ('history', 'service/history', 'resource/history','extended/history','integration/history'):
            from .history import series
            ident = integer(query.get('id', ''), 1, 2147483647, 'Messreihe')
            return series(store, route, ident, query.get('period'))
        if method != 'POST':
            raise tornado.web.HTTPError(404)
        if route == 'license/preview':return store.preview_license(body)
        if route == 'license/import':return store.import_license(body)
        if route == 'license/devices':return store.save_license_selection(body)
        if route == 'connection/save':return store.save_connection(body)
        if route == 'connection/delete':return store.delete_connection(body)
        if route == 'connection/layout':return store.save_connection_layout(body)
        if route == 'connection/icon':return store.save_connection_icon(body)
        if route == 'group/save':return store.save_group(body)
        if route == 'template/save':return store.save_template(body)
        if route == 'fleet/delete':return store.delete_fleet_item(body.get('kind'),body.get('id'))
        if route in ('fleet/preview','fleet/apply'):return store.fleet_change(body,apply=route=='fleet/apply')
        if route == 'fleet/ssh-keys':
            from .fleet import ids
            from .ssh_resources import scan_key
            selected=ids(body.get('ids'))
            if len(selected)>20:raise ValueError('Höchstens 20 Server-Schlüssel je Anfrage.')
            for did in selected:store.require_device_license(did)
            template=store.rows('SELECT config FROM templates WHERE id=?',(integer(body.get('template_id'),1,2147483647,'Vorlage'),))
            resource=json.loads(template[0]['config']).get('resource') if template else None
            if not resource or resource['method']!='ssh':raise ValueError('Keine SSH-Vorlage gewählt.')
            def fetch(did):
                d=store.rows('SELECT name,address FROM devices WHERE id=?',(did,))
                if not d:return dict(id=did,error='Gerät gelöscht.')
                r=store.rows('SELECT ssh_host_key FROM resource_targets WHERE device_id=? AND method=? AND port=?',(did,'ssh',resource['port']))
                if r and r[0]['ssh_host_key']:
                    from .ssh_resources import host_key
                    key,fingerprint=host_key(r[0]['ssh_host_key'])
                    return dict(id=did,name=d[0]['name'],ssh_host_key=key,fingerprint=fingerprint,trusted=True)
                try:
                    store.require_device_license(did)
                    result=scan_key(d[0]['address'],resource['port'])
                    store.require_device_license(did)
                    return dict(id=did,name=d[0]['name'],trusted=False,**result)
                except ValueError as exc:return dict(id=did,name=d[0]['name'],error=str(exc))
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                return dict(keys=list(pool.map(fetch,selected)))
        if route == 'resource/ssh-key':
            from .ssh_resources import scan_key
            ident = integer(body.get('device_id'),1,2147483647,'Gerät')
            store.require_device_license(ident)
            port = integer(body.get('port',22),1,65535,'SSH-Port')
            rows = store.rows('SELECT address FROM devices WHERE id=?',(ident,))
            if not rows:
                raise ValueError('Gerät nicht gefunden.')
            from .core import address
            result=scan_key(address(body.get('address', rows[0]['address'])),port)
            store.require_device_license(ident)
            return result
        if route == 'device/configure':
            from .setup import save_configuration
            return save_configuration(store, body)
        if route == 'integration/test':
            from .integrations import probe_integration
            did = integer(body.get('device_id'),1,2147483647,'Gerät')
            store.require_device_license(did)
            rows = store.rows('SELECT id,address FROM devices WHERE id=?',(did,))
            if not rows: raise ValueError('Gerät nicht gefunden.')
            old = None
            if body.get('id'):
                found = store.rows('SELECT * FROM integration_targets WHERE id=? AND device_id=?',
                    (integer(body['id'],1,2147483647,'Prüfung'),did))
                if not found: raise ValueError('Prüfung gehört nicht zu diesem Gerät.')
                old = found[0]
            target=store.integration_value(body,rows[0],old)
            target['diagnostic'] = True
            target['device_id']=did
            result=self.engine.flow_collector.test(target) if target['kind']=='flow' else probe_integration(target)
            store.require_device_license(did)
            return result
        if route == 'integration/fingerprint':
            did = integer(body.get('device_id'),1,2147483647,'Gerät')
            store.require_device_license(did)
            from .core import address
            from .integrations import probe_integration
            kind = body.get('kind')
            if kind not in ('tls','windows','hyperv','vmware','redfish','smtp','imap','pop3'):
                raise ValueError('Diese Prüfung verwendet kein TLS.')
            security = body.get('security','tls')
            if security not in ('tls','starttls'): raise ValueError('Zuerst TLS oder STARTTLS auswählen.')
            result=probe_integration(dict(kind='fingerprint',timeout=10,config=dict(
                host=address(body.get('host','')),port=integer(body.get('port'),1,65535,'Port'),
                protocol=kind,security=security,server_name=address(body['server_name']) if body.get('server_name') else '')))
            store.require_device_license(did)
            return result
        if route == 'resource/save':
            return {'id': store.save_resource(body)}
        if route == 'resource/action':
            store.resource_action(body.get('id'), body.get('action'))
            return {'ok': True}
        if route == 'device/save':
            return {'id': store.save_device(body)}
        if route == 'service/save':
            return {'id': store.save_service(body)}
        if route == 'service/action':
            store.service_action(body.get('id'), body.get('action'))
            return {'ok': True}
        if route == 'devices/import':
            return {'count': store.import_devices(body.get('ips'))}
        if route == 'device/action':
            ident = integer(body.get('id'), 1, 2147483647, 'Gerät')
            action = body.get('action')
            with store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT 1 FROM devices WHERE id=?', (ident,)).fetchone():
                    raise ValueError('Gerät nicht gefunden.')
                if action in ('check','resume'):store.require_device_license(ident,db)
                if action == 'delete':
                    store.protect_dependency_source(db,device_id=ident)
                    db.execute('DELETE FROM devices WHERE id=?', (ident,))
                elif action == 'check':
                    if not db.execute('SELECT enabled FROM devices WHERE id=?', (ident,)).fetchone()['enabled']:
                        raise ValueError('Das Gerät ist pausiert.')
                    db.execute('UPDATE services SET next_check=0 WHERE device_id=? AND enabled=1', (ident,))
                    db.execute('UPDATE resource_targets SET next_check=0 WHERE device_id=? AND enabled=1', (ident,))
                    db.execute('UPDATE integration_targets SET next_check=0 WHERE device_id=? AND enabled=1', (ident,))
                elif action in ('pause', 'resume'):
                    db.execute("UPDATE devices SET enabled=?,revision=revision+1 WHERE id=?", (int(action == 'resume'), ident))
                    db.execute("UPDATE services SET revision=revision+1,next_check=0,status='pending',failures=0 WHERE device_id=?", (ident,))
                    db.execute("UPDATE resource_targets SET revision=revision+1,next_check=0,status='pending',failures=0 WHERE device_id=?", (ident,))
                    db.execute("UPDATE integration_targets SET revision=revision+1,next_check=0,status='pending',failures=0 WHERE device_id=?", (ident,))
                else:
                    raise ValueError('Unbekannte Geräteaktion.')
            return {'ok': True}
        if route == 'range/save':
            expression = str(body.get('expression', '')).strip()
            total = len(targets(expression))
            name = str(body.get('name', '')).strip()[:120] or expression
            every = integer(body.get('every_minutes', 0), 0, 10080, 'Suchintervall')
            if every and every < 5:
                raise ValueError('Automatische Suche: mindestens 5 Minuten oder 0 für manuell.')
            with store.connect() as db:
                if body.get('id'):
                    cur = db.execute('UPDATE ranges SET name=?,expression=?,every_minutes=? WHERE id=?', (name, expression, every, int(body['id'])))
                    if not cur.rowcount:
                        raise ValueError('Netzwerkbereich nicht gefunden.')
                    ident = int(body['id'])
                else:
                    ident = db.execute('INSERT INTO ranges(name,expression,every_minutes) VALUES(?,?,?)', (name, expression, every)).lastrowid
            return {'id': ident, 'total': total}
        if route == 'range/delete':
            with self.engine.lock:
                if self.engine.scan_running:
                    raise ValueError('Netzwerkbereiche können nach Abschluss der laufenden Suche gelöscht werden.')
                with store.connect() as db:
                    db.execute('DELETE FROM ranges WHERE id=?', (int(body['id']),))
            return {'ok': True}
        if route == 'scan/start':
            return {'id': self.engine.start_scan(int(body['id']))}
        if route == 'scan/cancel':
            self.engine.scan_cancel.set()
            return {'ok': True}
        if route == 'settings/save':
            limits = {'interval': (5, 86400), 'timeout': (1, 30), 'threshold': (1, 20), 'scan_timeout': (1, 10)}
            values = {key: integer(body.get(key), lo, hi, key) for key, (lo, hi) in limits.items()}
            with store.connect() as db:
                for key, value in values.items():
                    db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(value), key))
            return {'ok': True}
        raise tornado.web.HTTPError(404)


class Base(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header('X-Content-Type-Options', 'nosniff')
        self.set_header('X-Frame-Options', 'DENY')
        self.set_header('Referrer-Policy', 'same-origin')
        self.set_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.set_header('Cache-Control', 'no-store')

    def language(self):
        session = self.application.sessions.get(self.get_cookie('nm_session', ''))
        if session and session['expires'] > time.time():
            agent = self.application.agents.get(session['agent_id'])
            if agent and agent['enabled'] and agent['auth_revision'] == session['auth_revision']:
                return agent['language']
        return self.application.agents.default_language

    def finish(self, chunk=None):
        if isinstance(chunk, dict) and isinstance(chunk.get('error'), str):
            chunk = dict(chunk, error=translate(chunk['error'], self.language()))
        return super().finish(chunk)

    def write_error(self, status_code, **kwargs):
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        self.finish({'error': {400: 'Ungültige Anfrage.', 401: 'Bitte anmelden.', 403: 'Anfrage nicht zulässig.',
                                        404: 'Nicht gefunden.', 413: 'Anfrage zu groß.', 429: 'Zu viele Versuche. Bitte später erneut versuchen.',
                                        503: 'Server ausgelastet. Bitte erneut versuchen.'}.get(status_code, 'Interner Fehler. Details stehen im Serverprotokoll.')})


class Asset(Base):
    def get(self, path):
        if path == 'locale.js':
            self.set_header('Content-Type', 'text/javascript; charset=utf-8')
            self.finish('window.QISUTU_LOCALE = ' + json.dumps(catalog(self.language()), ensure_ascii=False) + ';')
            return
        if path.startswith('languages/') and path[10:-5] in LANGUAGES and path.endswith('.json'):
            self.set_header('Content-Type', 'application/json; charset=utf-8')
            self.finish(catalog(path[10:-5]))
            return
        names = {'i18n.js': ('i18n.js', 'text/javascript'), 'agents.js': ('agents.js', 'text/javascript'),
                 '': ('index.html', 'text/html'), 'index.html': ('index.html', 'text/html'),
                 'app.js': ('app.js', 'text/javascript'), 'resources.js': ('resources.js', 'text/javascript'), 'style.css': ('style.css', 'text/css'),
                 'setup.js': ('setup.js', 'text/javascript'), 'ui.js': ('ui.js', 'text/javascript'), 'charts.js': ('charts.js', 'text/javascript'),
                 'fleet.js': ('fleet.js','text/javascript'), 'extended.js': ('extended.js','text/javascript'), 'extended.css': ('extended.css','text/css'),
                 'connections.js': ('connections.js','text/javascript'), 'connection-graph.js': ('connection-graph.js','text/javascript'), 'connections.css': ('connections.css','text/css'),
                 'notifications.js': ('notifications.js','text/javascript'), 'notifications.css': ('notifications.css','text/css'),
                 'licensing.js': ('licensing.js','text/javascript'), 'licensing.css': ('licensing.css','text/css'),
                 'integrations.js': ('integrations.js','text/javascript'), 'integrations.css': ('integrations.css','text/css'),
                 'Windows-Einrichtung.ps1': ('Windows-Einrichtung.ps1','application/octet-stream'),
                 'workspace.css': ('workspace.css', 'text/css'), 'favicon.svg': ('favicon.ico', 'image/x-icon'),
                 'favicon.ico': ('favicon.ico', 'image/x-icon'), 'logo.png': ('logo.png', 'image/png'),
                 'qisutu-theme.css': ('qisutu-theme.css', 'text/css')}
        if path not in names:
            raise tornado.web.HTTPError(404)
        filename, content_type = names[path]
        self.set_header('Content-Type', content_type + ('; charset=utf-8' if content_type.startswith('text/') else ''))
        self.finish((STATIC / filename).read_bytes())


class API(Base):
    def session(self):
        token = self.get_cookie('nm_session', '')
        session = self.application.sessions.get(token)
        if session and session['expires'] > time.time():
            agent = self.application.agents.get(session['agent_id'])
            if agent and agent['enabled'] and agent['auth_revision'] == session['auth_revision']:
                session['agent'] = agent
                return session
        self.application.sessions.pop(token, None)
        raise tornado.web.HTTPError(401)

    def csrf(self, session):
        token = self.request.headers.get('X-CSRF-Token', '')
        if not token or not hmac.compare_digest(token, session['csrf']):
            raise tornado.web.HTTPError(403)

    async def get(self, route):
        if route == 'health':
            self.finish({'service': 'netzmonitor'})
            return
        if route == 'languages':
            self.finish({'languages': LANGUAGES, 'language': self.application.agents.default_language})
            return
        session = self.session()
        if route == 'agents':
            self.finish({'agents': self.application.agents.list()})
            return
        if route == 'session':
            self.finish(self.session_data(session))
            return
        query = {key: self.get_query_argument(key) for key in self.request.query_arguments}
        await self.execute('GET', route, {}, query)

    async def post(self, route):
        if self.request.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise tornado.web.HTTPError(400)
        origin = self.request.headers.get('Origin')
        if origin and origin != self.request.protocol + '://' + self.request.host:
            raise tornado.web.HTTPError(403)
        try:
            body = json.loads(self.request.body)
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            raise tornado.web.HTTPError(400)
        if route == 'login':
            await self.login(body)
            return
        session = self.session()
        self.csrf(session)
        if route == 'logout':
            self.application.sessions.pop(self.get_cookie('nm_session', ''), None)
            self.clear_cookie('nm_session', path='/')
            self.finish({'ok': True})
            return
        if route in ('password', 'profile/language', 'agent/save', 'agent/delete'):
            agents = self.application.agents
            try:
                if route == 'password':
                    result = await asyncio.get_running_loop().run_in_executor(
                        self.application.executor, agents.password, session['agent_id'],
                        body.get('current', ''), body.get('password', ''))
                    self.clear_cookie('nm_session', path='/')
                elif route == 'profile/language':
                    result = agents.language(session['agent_id'], body.get('language'))
                elif route == 'agent/save':
                    result = await asyncio.get_running_loop().run_in_executor(
                        self.application.executor, agents.save, body, session['agent_id'])
                else:
                    result = agents.delete(body, session['agent_id'])
                self.finish(result)
            except (ValueError, TypeError) as exc:
                self.set_status(400)
                self.finish({'error': str(exc) if isinstance(exc, ValueError) else 'Ungültige Eingabe.'})
            return
        await self.execute('POST', route, body, {})

    async def login(self, body):
        app = self.application
        now, ip = time.time(), self.request.remote_ip
        app.attempts = {k: v for k, v in app.attempts.items() if v[0] > now - 900}
        start, count = app.attempts.get(ip, (now, 0))
        if count >= 8 or len(app.attempts) > 2048:
            raise tornado.web.HTTPError(429)
        app.attempts[ip] = (start, count + 1)
        agent = await asyncio.get_running_loop().run_in_executor(
            app.executor, app.agents.authenticate, body.get('username', ''), body.get('password', ''))
        if not agent:
            self.set_status(401)
            self.finish({'error': 'Benutzername oder Passwort ist falsch.'})
            return
        app.attempts.pop(ip, None)
        app.sessions = {k: v for k, v in app.sessions.items() if v['expires'] > now}
        if len(app.sessions) >= 256:
            oldest = min(app.sessions, key=lambda k: app.sessions[k]['expires'])
            app.sessions.pop(oldest)
        token, csrf = secrets.token_urlsafe(36), secrets.token_urlsafe(24)
        app.sessions[token] = {'expires': now + 12 * 3600, 'csrf': csrf,
                               'agent_id': agent['id'], 'auth_revision': agent['auth_revision'], 'agent': agent}
        self.set_cookie('nm_session', token, httponly=True, secure=self.request.protocol == 'https',
                        samesite='Strict', path='/', max_age=43200)
        self.finish(self.session_data(app.sessions[token]))

    def session_data(self, session):
        agent = session['agent']
        return {'user': agent['username'], 'agent': self.application.agents.public(agent),
                'language': agent['language'], 'csrf': session['csrf'], 'version': VERSION}

    async def execute(self, method, route, body, query):
        app = self.application
        if app.inflight >= 32:
            raise tornado.web.HTTPError(503)
        app.inflight += 1
        try:
            result = await asyncio.get_running_loop().run_in_executor(app.executor, app.dispatch, method, route, body, query)
            self.finish(result)
        except (ValueError, TypeError, KeyError) as exc:
            self.set_status(400)
            self.finish({'error': str(exc) if isinstance(exc, ValueError) else 'Ungültige Eingabe.'})
        finally:
            app.inflight -= 1
