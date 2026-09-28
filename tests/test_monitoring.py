import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'vendor')]
from netzmonitor.core import Store, Engine, probe, address, targets
from netzmonitor.services import SERVICE_SELECT
from netzmonitor.server import WebApp, set_password, valid_password


def result(kind='up', rtt=1.25):
    return {'kind': kind, 'rtt': rtt if kind == 'up' else None, 'message': '' if kind == 'up' else 'Testmeldung', 'ip': '192.0.2.1'}


class MonitoringTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.device_id = self.store.save_device({'name': 'Testgerät', 'address': '192.0.2.1'})
        self.service_id = self.store.save_service({'device_id': self.device_id, 'name': 'Ping', 'type': 'ping'})
        self.device = self.store.rows(SERVICE_SELECT)[0]

    def tearDown(self):
        self.temp.cleanup()

    def current(self):
        return self.store.rows(SERVICE_SELECT)[0]

    def test_threshold_recovery_and_errors(self):
        self.store.record_service(self.device, result())
        self.assertEqual(self.current()['status'], 'up')
        self.store.record_service(self.device, result('down'))
        self.assertEqual(self.current()['status'], 'warning')
        self.store.record_service(self.device, result('error'))
        self.assertEqual(self.current()['failures'], 1)
        self.assertEqual(self.current()['status'], 'error')
        self.store.record_service(self.device, result('down'))
        self.store.record_service(self.device, result('down'))
        self.assertEqual(self.current()['status'], 'down')
        self.store.record_service(self.device, result())
        self.assertEqual(self.current()['status'], 'up')
        self.assertEqual(self.current()['failures'], 0)
        self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')), 6)

    def test_pending_results_cannot_override_pause_edit_or_deletion(self):
        with self.store.connect() as db:
            db.execute('UPDATE devices SET enabled=0 WHERE id=?', (self.device_id,))
        self.store.record_service(self.device, result())
        self.assertIsNone(self.current()['last_checked'])
        with self.store.connect() as db:
            db.execute('UPDATE devices SET enabled=1,revision=revision+1 WHERE id=?', (self.device_id,))
        self.store.record_service(self.device, result())
        self.assertIsNone(self.current()['last_checked'])
        with self.store.connect() as db:
            db.execute('DELETE FROM devices')
        self.store.record_service(self.device, result())
        self.assertEqual(self.store.rows('SELECT * FROM devices'), [])

    def test_persistence_and_duplicate_prevention(self):
        self.store.record_service(self.device, result())
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.state()['devices'][0]['status'], 'up')
        with self.assertRaises(ValueError):
            reopened.save_device({'address':'192.0.2.1'})
        self.assertEqual(reopened.rows('PRAGMA integrity_check')[0]['integrity_check'], 'ok')

    def test_scan_import_and_repeated_discovery(self):
        with self.store.connect() as db:
            rid = db.execute("INSERT INTO ranges(name,expression) VALUES('Test','192.0.2.0/30')").lastrowid
        engine = Engine(self.store, lambda ip, timeout: result('up' if ip in ('127.0.0.1','192.0.2.2') else 'down'), lambda ip:'switch.example')
        try:
            for _ in range(2):
                engine.start_scan(rid)
                engine.scan_thread.join(5)
            self.assertEqual(len(self.store.rows('SELECT * FROM discoveries')), 1)
            self.assertEqual(self.store.rows('SELECT * FROM scans')[0]['checked'], 2)
            self.assertEqual(self.store.import_devices(['192.0.2.2']), 1)
            self.assertEqual(self.store.import_devices(['192.0.2.2']), 0)
            self.assertEqual(len(self.store.rows('SELECT * FROM devices')), 2)
            self.assertEqual(len(self.store.state()['services']), 1)
            self.assertEqual(next(d for d in self.store.state()['devices'] if d['address']=='192.0.2.2')['status'], 'unmonitored')
        finally:
            engine.close()

    def test_scan_cancellation_bounded_queue(self):
        started = threading.Event()
        def slow(ip, timeout):
            if ip != '127.0.0.1':
                started.set()
                time.sleep(.05)
            return result()
        with self.store.connect() as db:
            rid = db.execute("INSERT INTO ranges(name,expression) VALUES('Test','192.0.2.0/24')").lastrowid
        engine = Engine(self.store, slow, lambda ip:'')
        try:
            engine.start_scan(rid)
            self.assertTrue(started.wait(2))
            engine.scan_cancel.set()
            engine.scan_thread.join(5)
            scan=self.store.rows('SELECT * FROM scans')[0]
            self.assertEqual(scan['status'], 'cancelled')
            self.assertLess(scan['checked'], scan['total'])
        finally:
            engine.close()

    def test_restart_interrupted_scans_and_resumed_checks(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO scans(name,started,status,total) VALUES('test',?,'running',4)", (time.time(),))
            db.execute('UPDATE services SET next_check=?', (time.time()+86400,))
        engine=Engine(self.store,lambda ip,t:result(), lambda ip:'')
        engine.start()
        try:
            deadline=time.monotonic()+3
            while self.current()['status']=='pending' and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertEqual(self.current()['status'],'up')
            self.assertEqual(self.store.rows('SELECT * FROM scans')[0]['status'],'interrupted')
        finally:
            engine.close()

    def test_automatic_scheduled_discovery(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO ranges(name,expression,every_minutes) VALUES('Test','192.0.2.5',5)")
        engine=Engine(self.store,lambda ip,t:result(),lambda ip:'')
        engine.start()
        try:
            deadline=time.monotonic()+3
            while not self.store.rows('SELECT * FROM discoveries') and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertEqual(len(self.store.rows('SELECT * FROM discoveries')),1)
            self.assertEqual(len(self.store.rows('SELECT * FROM scans')),1)
        finally:
            engine.close()

    def test_validation_and_no_shell_invocation(self):
        for invalid in ['-c 200', 'foo; touch /tmp/x', '$(id)', '999.2.3.4', '0.0.0.0', '224.0.0.1']:
            with self.assertRaises(ValueError):
                address(invalid)
        self.assertEqual(address('SERVER.example.'), 'server.example')
        self.assertEqual(address('::1'), '::1')
        self.assertEqual(targets('192.0.2.0/30'), ['192.0.2.1','192.0.2.2'])
        self.assertEqual(targets('192.0.2.0/31'), ['192.0.2.0','192.0.2.1'])
        self.assertEqual(targets('192.0.2.8-192.0.2.9'), ['192.0.2.8','192.0.2.9'])
        with self.assertRaises(ValueError):
            targets('10.0.0.0/8')
        with patch('netzmonitor.core.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([],0,'PING example (192.0.2.1)\n64 bytes: time=0.032 ms\n')
            output=probe('example',2,'/usr/bin/ping')
            self.assertEqual(output['rtt'],.032)
            self.assertEqual(output['ip'],'192.0.2.1')
            self.assertNotIn('shell',run.call_args.kwargs)
            self.assertEqual(run.call_args.args[0][-1],'example')
            run.return_value=subprocess.CompletedProcess([],2,'ping: operation not permitted')
            self.assertEqual(probe('example',2,'/usr/bin/ping')['kind'],'error')

    def test_credentials(self):
        cfg={}
        set_password(cfg,'Ein-langes-Testpasswort')
        self.assertTrue(valid_password(cfg,'Ein-langes-Testpasswort'))
        self.assertFalse(valid_password(cfg,'falsch'))
        self.assertNotIn('Ein-langes-Testpasswort',json.dumps(cfg))
        with self.assertRaises(ValueError):
            set_password(cfg,'kurz')

if __name__ == '__main__':
    unittest.main(verbosity=2)
