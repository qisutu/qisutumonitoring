from account_fixture import configuration
"""Service checks against real local TCP, HTTP and HTTPS endpoints."""
import http.server
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'vendor')]
from netzmonitor.core import Store, Engine
from netzmonitor.services import SERVICE_SELECT, probe_service, http_url, status_codes
from netzmonitor.server import WebApp


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/slow':
            time.sleep(2.5)
        if self.path == '/trickle':
            try:
                self.wfile.write(b'HTTP/1.0 200 OK\r\nX-Slow: ')
                for _ in range(30):
                    self.wfile.write(b'a'); self.wfile.flush(); time.sleep(.15)
            except OSError:
                pass
            return
        code = {'/error': 503, '/redirect': 302, '/private': 401}.get(self.path, 200)
        try:
            self.send_response(code)
            if code == 302:
                self.send_header('Location', '/ok')
            self.send_header('Content-Length', '0')
            self.end_headers()
        except OSError:
            pass


class ServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cert_temp = tempfile.TemporaryDirectory()
        cert = Path(cls.cert_temp.name)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
                        '-keyout', str(cert/'key'), '-out', str(cert/'cert')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.http = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.https = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert/'cert', cert/'key')
        cls.https.socket = context.wrap_socket(cls.https.socket, server_side=True)
        for server in (cls.http, cls.https):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.http, cls.https):
            server.shutdown(); server.server_close()
        cls.cert_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.device = self.store.save_device({'name': 'Testserver', 'address': '127.0.0.1'})

    def tearDown(self):
        self.temp.cleanup()

    def create(self, **values):
        data = dict(device_id=self.device, name='Weboberfläche', type='http',
                    url='http://127.0.0.1:%s/ok' % self.http.server_port, threshold=2, timeout=2)
        data.update(values)
        ident = self.store.save_service(data)
        return self.store.rows(SERVICE_SELECT+' WHERE s.id=?', (ident,))[0]

    def test_http_codes_redirects_and_latency(self):
        service = self.create()
        output = probe_service(service)
        self.assertEqual(output['kind'], 'up'); self.assertEqual(output['status_code'], 200)
        self.assertGreater(output['rtt'], 0)
        for endpoint, code in (('error', 503), ('redirect', 302), ('private', 401)):
            service['url'] = 'http://127.0.0.1:%s/%s' % (self.http.server_port, endpoint)
            output = probe_service(service)
            self.assertEqual(output['kind'], 'down'); self.assertEqual(output['status_code'], code)
        service['expected_codes'] = '200-299,401'
        self.assertEqual(probe_service(service)['kind'], 'up')

    def test_https_validation_and_explicit_self_signed_option(self):
        service = self.create(url='https://localhost:%s/' % self.https.server_port)
        output = probe_service(service)
        self.assertEqual(output['kind'], 'down'); self.assertIn('Zertifikat', output['message'])
        with patch.dict(os.environ, SSL_CERT_FILE=str(Path(self.cert_temp.name)/'cert')):
            self.assertEqual(probe_service(service)['kind'], 'up')
            service['url'] = 'https://127.0.0.1:%s/' % self.https.server_port
            self.assertEqual(probe_service(service)['kind'], 'down')
        service['verify_tls'] = 0
        output = probe_service(service)
        self.assertEqual(output['kind'], 'up'); self.assertIn('ausgeschaltet', output['message'])

    def test_tcp_connection_and_refusal(self):
        service = self.create(type='tcp', port=self.http.server_port)
        self.assertEqual(probe_service(service)['kind'], 'up')
        # Bound but non-listening socket: deterministic connection refusal.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); service['port'] = sock.getsockname()[1]
            output = probe_service(service)
        self.assertEqual(output['kind'], 'down'); self.assertIn('abgelehnt', output['message'])

    def test_total_timeout_even_when_peer_sends_slow_headers(self):
        for path in ('slow', 'trickle'):
            service = self.create(url='http://127.0.0.1:%s/%s' % (self.http.server_port, path), timeout=1)
            start = time.monotonic(); output = probe_service(service)
            self.assertLess(time.monotonic()-start, 2.2)
            self.assertEqual(output['kind'], 'down'); self.assertIn('Antwortfrist', output['message'])

    def test_validation_and_worker_failure(self):
        for value in ('file:///etc/passwd', 'ftp://example.org', 'https://a:b@example.org/',
                      'https://example.org:99999/', 'https://example.org/#fragment', 'http://x/\r\nX:a'):
            with self.assertRaises(ValueError):
                http_url(value)
        self.assertEqual(http_url('http://[::1]:8080/'), 'http://[::1]:8080/')
        self.assertIn('%C3%A4', http_url('https://example.org/ä'))
        for value in ('', '600', '300-200', '200;rm', '20'):
            with self.assertRaises(ValueError):
                status_codes(value)
        with self.assertRaises(ValueError):
            self.create(type='tcp', port=0)
        service = self.create()
        with patch('netzmonitor.services.subprocess.run', side_effect=OSError('failure')):
            self.assertEqual(probe_service(service)['kind'], 'error')

    def test_threshold_recovery_edit_and_stale_results(self):
        service = self.create()
        down = dict(kind='down', rtt=3, message='HTTP 503', status_code=503)
        up = dict(kind='up', rtt=1, message='HTTP 200', status_code=200)
        self.store.record_service(service, down)
        self.assertEqual(self.store.state()['services'][0]['status'], 'warning')
        self.store.record_service(service, down)
        self.assertEqual(self.store.state()['services'][0]['status'], 'down')
        self.store.record_service(service, up)
        self.assertEqual(self.store.state()['services'][0]['status'], 'up')
        service['name'] = 'Neuer Name'; self.store.save_service(service)
        self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')), 3)
        self.store.record_service(service, down)  # old revision must be ignored
        self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')), 3)
        fresh = self.store.state()['services'][0]
        self.store.service_action(fresh['id'], 'pause'); self.store.record_service(fresh, down)
        self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')), 3)
        fresh['url'] += '?new=1'; self.store.save_service(fresh)
        self.assertEqual(self.store.rows('SELECT * FROM service_samples'), [])

    def test_parent_pause_address_change_and_deletion(self):
        tcp = self.create(type='tcp', port=self.http.server_port)
        web = self.create()
        up = dict(kind='up', rtt=1, message='OK', status_code=None)
        self.store.record_service(tcp, up); self.store.record_service(web, up)
        engine = Engine(self.store)
        app = WebApp((configuration(self.temp.name) or self.temp.name), engine)
        try:
            app.dispatch('POST', 'device/action', {'id': self.device, 'action': 'pause'}, {})
            self.store.record_service(tcp, up)
            self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')), 2)
            with self.assertRaises(ValueError):
                self.store.service_action(tcp['id'], 'check')
            app.dispatch('POST', 'device/action', {'id': self.device, 'action': 'resume'}, {})
            self.store.record_service(tcp, up)  # result from before parent pause
            self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')), 2)
            self.store.save_device({'id': self.device, 'address': '127.0.0.2'})
            samples = self.store.rows('SELECT * FROM service_samples')
            self.assertEqual(len(samples), 1); self.assertEqual(samples[0]['service_id'], web['id'])
            app.dispatch('POST', 'device/action', {'id': self.device, 'action': 'delete'}, {})
            self.assertEqual(self.store.state()['services'], [])
            self.assertEqual(self.store.rows('SELECT * FROM service_samples'), [])
        finally:
            app.executor.shutdown(); engine.close()

    def test_migration_restart_and_scheduler_independent_of_ping(self):
        self.assertEqual(self.store.state()['devices'][0]['status'], 'unmonitored')
        service = self.create()
        reopened = Store(self.temp.name)
        engine = Engine(reopened, probe_fn=lambda h,t:dict(kind='down', rtt=None, message='Test', ip=h))
        engine.start()
        try:
            until = time.monotonic()+5
            while time.monotonic()<until:
                saved = reopened.state()['services'][0]
                if saved['status'] == 'up':
                    break
                time.sleep(.03)
            self.assertEqual(saved['status'], 'up')
            self.assertEqual(reopened.state()['devices'][0]['status'], 'up')
        finally:
            engine.close()
        self.assertEqual(Store(self.temp.name).state()['services'][0]['status'], 'up')
        self.assertEqual(reopened.rows('PRAGMA integrity_check')[0]['integrity_check'], 'ok')


if __name__ == '__main__':
    unittest.main(verbosity=2)
