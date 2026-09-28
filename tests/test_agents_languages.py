"""Real HTTP account lifecycle and restart/migration coverage without network probes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
import tornado.testing

from netzmonitor.agents import Agents
from netzmonitor.core import Store, Engine
from netzmonitor.i18n import LANGUAGES, catalog
from netzmonitor.server import WebApp, set_password, write_config, read_config


class AccountHTTPTests(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {'language': 'de'}
        set_password(self.config, 'Original-password-2026')
        write_config(self.temp.name, self.config)
        self.store = Store(self.temp.name)
        self.engine = Engine(self.store)
        self.web = WebApp(self.temp.name, self.engine)
        return self.web

    def tearDown(self):
        self.web.executor.shutdown(wait=True)
        self.engine.close()
        super().tearDown()
        self.temp.cleanup()

    def call(self, route, body=None, auth=None, csrf=True):
        headers = {}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if auth:
            headers['Cookie'] = auth[0]
            if csrf:
                headers['X-CSRF-Token'] = auth[1]
        response = self.fetch('/api/' + route, method='GET' if body is None else 'POST',
                              body=None if body is None else json.dumps(body), headers=headers)
        return response, json.loads(response.body)

    def login(self, username='admin', password='Original-password-2026'):
        response, result = self.call('login', {'username': username, 'password': password})
        self.assertEqual(response.code, 200, result)
        return (response.headers['Set-Cookie'].split(';')[0], result['csrf']), result

    def test_accounts_own_language_relogin_restart_and_equal_access(self):
        admin, original = self.login()
        for code in LANGUAGES:
            response, created = self.call('agent/save', dict(username='agent-' + code,
                name='Agent ' + code, password='Agent-password-2026', language=code), admin)
            self.assertEqual(response.code, 200, created)
            agent, session = self.login('agent-' + code, 'Agent-password-2026')
            self.assertEqual(session['language'], code)
            self.assertEqual(self.call('agents', auth=agent)[0].code, 200)
            script = self.fetch('/locale.js', headers={'Cookie': agent[0]}).body.decode()
            self.assertIn('"code": "' + code + '"', script)
            self.assertEqual(self.call('logout', {}, agent)[0].code, 200)
            self.assertEqual(self.call('session', auth=agent)[0].code, 401)
            self.assertEqual(self.login('agent-' + code, 'Agent-password-2026')[1]['language'], code)
        rows = self.call('agents', auth=admin)[1]['agents']
        self.assertEqual(len(rows), 12)
        self.assertNotIn('password_hash', json.dumps(rows))
        self.assertNotIn('salt', json.dumps(rows))
        # Recreate both persistent store and authentication layer as a service restart does.
        restarted = Agents(Store(self.temp.name), read_config(self.temp.name))
        self.assertEqual(len(restarted.list()), 12)
        self.assertEqual(restarted.authenticate('agent-fr', 'Agent-password-2026')['language'], 'fr')
        self.assertEqual(restarted.authenticate('admin', 'Original-password-2026')['id'], original['agent']['id'])

    def test_language_is_per_account_not_browser_and_validated(self):
        admin, _ = self.login()
        other, _ = self.login()
        self.assertEqual(self.call('profile/language', {'language':'tr'}, admin)[0].code, 200)
        self.assertEqual(self.call('session', auth=other)[1]['language'], 'tr')
        self.assertEqual(self.login()[1]['language'], 'tr')
        for invalid in ['xx', '../de', None, [], 'pt']:
            self.assertEqual(self.call('profile/language', {'language':invalid}, admin)[0].code, 400)
        self.assertEqual(self.call('session', auth=admin)[1]['language'], 'tr')
        self.assertEqual(self.call('profile/language', {'language':'en'}, admin, csrf=False)[0].code, 403)

    def test_crud_duplicate_stale_self_protection_and_session_revocation(self):
        admin, current = self.login()
        response, agent = self.call('agent/save',dict(username='second',name='Second',
            password='Second-password-2026',language='fr'),admin)
        self.assertEqual(response.code,200)
        second, _ = self.login('second','Second-password-2026')
        self.assertEqual(self.call('agent/save',dict(username='SECOND',password='Another-password',language='de'),admin)[0].code,400)
        # Equal access: the additional account can create another agent too.
        self.assertEqual(self.call('agent/save',dict(username='third',password='Third-password-2026',language='nl'),second)[0].code,200)
        response, updated = self.call('agent/save',{**agent,'enabled':0,'password':''},admin)
        self.assertEqual(response.code,200)
        self.assertEqual(self.call('session',auth=second)[0].code,401)
        self.assertEqual(self.call('login',dict(username='second',password='Second-password-2026'))[0].code,401)
        self.assertEqual(self.call('agent/save',{**agent,'name':'stale'},admin)[0].code,400)
        self.assertEqual(self.call('agent/save',{**updated,'enabled':1,'password':''},admin)[0].code,200)
        second, _ = self.login('second','Second-password-2026')
        own = self.call('session',auth=admin)[1]['agent']
        self.assertEqual(self.call('agent/delete',own,admin)[0].code,400)
        self.assertEqual(self.call('agent/save',{**own,'enabled':0},admin)[0].code,400)
        active=self.call('session',auth=second)[1]['agent']
        self.assertEqual(self.call('agent/delete',active,admin)[0].code,200)
        self.assertEqual(self.call('session',auth=second)[0].code,401)

    def test_password_changes_only_own_account_and_cli_reset_revokes_sessions(self):
        admin, _ = self.login()
        agent=self.call('agent/save',dict(username='second',password='Second-password-2026',language='en'),admin)[1]
        second, _ = self.login('second','Second-password-2026')
        self.assertEqual(self.call('password',dict(current='wrong',password='New-password-2026'),second)[0].code,400)
        self.assertEqual(self.call('password',dict(current='Second-password-2026',password='New-password-2026'),second)[0].code,200)
        self.assertEqual(self.call('session',auth=second)[0].code,401)
        self.assertEqual(self.call('session',auth=admin)[0].code,200)
        second,_=self.login('second','New-password-2026')
        proc=subprocess.run([sys.executable,str(ROOT/'run.py'),'password','--data-dir',self.temp.name,
            '--username','second','--password-stdin'],input='Reset-password-2026\n',text=True,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(self.call('session',auth=second)[0].code,401)
        self.assertEqual(self.login('second','Reset-password-2026')[1]['language'],'en')

    def test_auth_csrf_and_catalog_asset_allowlist(self):
        self.assertEqual(self.call('agents')[0].code,401)
        self.assertEqual(self.call('agent/save',{})[0].code,401)
        admin,_=self.login()
        self.assertEqual(self.call('agent/save',{},admin,csrf=False)[0].code,403)
        for code in LANGUAGES:
            response=self.fetch('/languages/'+code+'.json')
            self.assertEqual(response.code,200)
            self.assertEqual(json.loads(response.body)['code'],code)
        for path in ['/languages/xx.json','/languages/../../config.json','/agents.py']:
            self.assertEqual(self.fetch(path).code,404)


class InstallationLanguageTests(unittest.TestCase):
    def test_init_all_languages_preserves_existing_accounts_and_data(self):
        for code in LANGUAGES:
            with self.subTest(code=code),tempfile.TemporaryDirectory() as data:
                result=subprocess.run([sys.executable,str(ROOT/'run.py'),'init','--data-dir',data,
                    '--language',code,'--password-stdin'],input='Installer-password-2026\n',text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(read_config(data)['language'],code)
                accounts=Agents(Store(data),read_config(data))
                self.assertEqual(accounts.authenticate('admin','Installer-password-2026')['language'],code)
                before=Path(data,'config.json').read_bytes()
                result=subprocess.run([sys.executable,str(ROOT/'run.py'),'init','--data-dir',data,
                    '--language','en','--password-stdin'],input='Changed-password-2026\n',text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(Path(data,'config.json').read_bytes(),before)
                self.assertEqual(len(accounts.list()),1)

    def test_catalog_keys_and_placeholders_match(self):
        import re
        baseline=catalog('de')['messages']
        for code in LANGUAGES:
            translated=catalog(code)['messages']
            self.assertEqual(set(translated),set(baseline))
            for key,value in translated.items():
                self.assertTrue(value.strip(),(code,key))
                self.assertEqual(sorted(re.findall(r'\{\d+\}',key)),sorted(re.findall(r'\{\d+\}',value)),(code,key))


if __name__=='__main__':
    unittest.main()
