import copy
import json
from pathlib import Path
import socketserver
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from netzmonitor.core import Store
from netzmonitor.notifications import NotificationWorker, transport
from netzmonitor.services import SERVICE_SELECT


class NotificationsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.device=self.store.save_device(dict(name='Server Ä',address='127.0.0.1'))
        self.sid=self.store.save_service(dict(device_id=self.device,name='HTTPS',type='tcp',port=443,threshold=3))
        self.worker=NotificationWorker(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def configure(self, email=True, qisutu=True, **extra):
        c=self.store.notification_state();c.pop('delivery')
        for channel in ('email','qisutu'):c[channel].pop('has_secret')
        c['email'].update(enabled=email,host='localhost',security='none',port=25,sender='monitor@test.invalid',recipient='admin@test.invalid')
        c['qisutu'].update(enabled=qisutu,url='https://localhost/api.pl/v1/addons/qisutu.monitoring/events/'+'a'*32,token='test-secret')
        c.update(extra);self.store.save_notifications(c)
        return c

    def record(self, kind):
        target=self.store.rows(SERVICE_SELECT+' WHERE s.id=?',(self.sid,))[0]
        self.store.record_service(target,dict(kind=kind,rtt=1 if kind=='up' else None,message='Test '+kind,ip=''))

    def pending(self):
        return self.store.rows("SELECT * FROM notification_outbox WHERE state='pending' ORDER BY id")

    def test_off_by_default_and_no_secrets_in_state(self):
        self.record('down');self.record('down');self.record('down');self.assertEqual(self.pending(),[])
        self.configure();self.assertNotIn('test-secret',json.dumps(self.store.state()))
        public=self.store.notification_state();self.assertNotIn('token',public['qisutu']);self.assertTrue(public['qisutu']['has_secret'])

    def test_threshold_transitions_and_recovery(self):
        self.configure();self.record('up');self.record('down');self.record('down');self.assertEqual(self.pending(),[])
        self.record('down');self.record('down');self.assertEqual(len(self.pending()),2)
        self.record('up');rows=self.pending();self.assertEqual(len(rows),4)
        problem,recovery=json.loads(rows[0]['payload']),json.loads(rows[2]['payload'])
        self.assertEqual(problem['fingerprint'],recovery['fingerprint']);self.assertNotEqual(problem['event_id'],recovery['event_id'])
        self.assertEqual(problem['status'],'problem');self.assertEqual(recovery['status'],'recovery')
        self.assertIn('Server Ä',problem['details']);self.assertIn('127.0.0.1',problem['details'])
        self.record('up');self.assertEqual(len(self.pending()),4)

    def test_persistent_retry_order_and_independent_destinations(self):
        self.configure()
        for _ in range(3):self.record('down')
        self.record('up');first=json.loads(self.pending()[0]['payload'])['event_id']
        sent=[]
        def fail(c,cfg,payload):sent.append(payload['event_id']);return dict(ok=False,message='offline')
        self.worker.deliver_one('email',fail)
        self.assertFalse(self.worker.deliver_one('email',fail))
        self.assertTrue(self.worker.deliver_one('qisutu',lambda *a:dict(ok=True)))
        again=Store(self.temp.name);self.assertEqual(len(again.rows("SELECT * FROM notification_outbox WHERE state='pending'")),3)
        with again.connect() as db:db.execute('UPDATE notification_outbox SET next_attempt=0')
        NotificationWorker(again).deliver_one('email',lambda c,cfg,p: sent.append(p['event_id']) or dict(ok=True))
        self.assertEqual(sent,[first,first])
        self.worker.deliver_one('email',lambda *a:dict(ok=True));self.assertEqual(self.store.notification_state()['delivery']['email']['pending'],0)

    def test_destination_change_discards_old_queue(self):
        self.configure()
        for _ in range(3):self.record('down')
        c=self.configure();c['revision']=self.store.notification_state()['revision'];c['email']['recipient']='new@test.invalid'
        self.store.save_notifications(c)
        self.assertEqual([r['channel'] for r in self.pending()],['qisutu'])
        self.record('down');self.assertEqual(len(self.pending()),2)

    def test_paused_and_dependency_blocked_samples_do_not_notify(self):
        self.configure()
        with self.store.connect() as db:db.execute('UPDATE devices SET blocked=1,block_revision=block_revision+1 WHERE id=?',(self.device,))
        for _ in range(3):self.record('down')
        self.assertEqual(self.pending(),[])
        with self.store.connect() as db:db.execute('UPDATE devices SET blocked=0,enabled=0 WHERE id=?',(self.device,))
        self.record('error');self.assertEqual(self.pending(),[])

    def test_disabled_channel_does_not_send(self):
        self.configure()
        for _ in range(3):self.record('down')
        self.configure(email=False)
        self.assertFalse(self.worker.deliver_one('email',lambda *a:self.fail('Unexpected send')))
        self.assertTrue(all(r['channel']=='qisutu' for r in self.pending()))

    def test_selected_devices_and_group_membership(self):
        with self.store.connect() as db:
            gid=db.execute("INSERT INTO device_groups(name) VALUES('Berlin')").lastrowid
        self.configure(scope='selected',group_ids=[gid]);self.record('error');self.assertEqual(self.pending(),[])
        with self.store.connect() as db:db.execute('INSERT INTO group_members VALUES(?,?)',(gid,self.device))
        self.record('error');self.assertEqual(len(self.pending()),2)

    def test_validation_revision_and_secret_preservation(self):
        c=self.configure()
        with self.assertRaises(ValueError):self.store.save_notifications(c)
        c['revision']=self.store.notification_state()['revision'];c['qisutu']['token']='';self.store.save_notifications(c)
        with self.store.connect() as db:self.assertEqual(self.store.notification_config(db)['qisutu']['token'],'test-secret')
        c['revision']+=1;c['email']['sender']='a@test.invalid\r\nBcc:evil@test.invalid'
        with self.assertRaises(ValueError):self.store.save_notifications(c)
        c['email']['sender']='a@test.invalid';c['qisutu']['url']='https://other.invalid/'
        with self.assertRaises(ValueError):self.store.save_notifications(c)

    def test_integration_threshold_metrics_warning_and_recovery(self):
        from netzmonitor.integrations import SELECT
        from netzmonitor.integration_common import metric
        self.configure()
        with self.store.connect() as db:
            device=db.execute('SELECT * FROM devices WHERE id=?',(self.device,)).fetchone()
            self.store.save_integrations(db,device,[dict(kind='tls',config={})])
        def record(result):
            target=self.store.rows(SELECT)[0];self.store.record_integration(target,result)
        record(dict(kind='error',metrics=[],message='Timeout'))
        record(dict(kind='error',metrics=[],message='Timeout'));self.assertEqual(self.pending(),[])
        record(dict(kind='error',metrics=[],message='Timeout'));self.assertEqual(len(self.pending()),2)
        record(dict(kind='ok',metrics=[metric('expiry','Zertifikat',5,'Tage',status='warning')]))
        self.assertEqual(len(self.pending()),4)
        record(dict(kind='ok',metrics=[metric('expiry','Zertifikat',90,'Tage',status='up')]))
        self.assertEqual(len(self.pending()),6)
        self.assertIn('90',json.dumps(self.store.integration_state()))

    def test_resource_hook_with_actual_measurements(self):
        from netzmonitor.resources import RESOURCE_SELECT
        self.configure()
        self.store.save_resource(dict(device_id=self.device,method='snmp',version='2c',community='public'))
        target=self.store.rows(RESOURCE_SELECT)[0]
        def result(value):return dict(kind='ok',metrics=[dict(key='cpu',kind='cpu',label='CPU',percent=value,total=None,used=None,free=None)],message='')
        self.store.record_resource(target,result(99))
        self.assertEqual(len(self.pending()),2)
        self.assertIn('99',json.loads(self.pending()[0]['payload'])['details'])
        self.store.record_resource(target,result(10));self.assertEqual(len(self.pending()),4)

    def test_deleted_check_never_sends_stale_event(self):
        self.configure();self.record('error');self.store.service_action(self.sid,'delete')
        self.assertTrue(self.worker.deliver_one('email',lambda *a:self.fail('Unexpected send')))

    def test_new_episode_reuses_check_correlation(self):
        self.configure();self.record('error');self.record('up');self.record('error')
        events=[json.loads(r['payload']) for r in self.pending() if r['channel']=='qisutu']
        self.assertEqual(len({e['fingerprint'] for e in events}),1)
        self.assertNotEqual(events[0]['tags']['episode'],events[2]['tags']['episode'])


class SMTPFixture(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b'220 localhost test\r\n')
        while True:
            line=self.rfile.readline()
            if not line:break
            self.server.commands.append(line.decode().strip())
            cmd=line.split()[0].upper()
            if cmd in (b'EHLO',b'HELO'):self.wfile.write(b'250-localhost\r\n250 SIZE 1048576\r\n')
            elif cmd==b'DATA':
                self.wfile.write(b'354 End with dot\r\n');body=b''
                while True:
                    part=self.rfile.readline()
                    if part in (b'.\r\n',b''):break
                    body+=part
                self.server.messages.append(body);self.wfile.write(b'250 accepted\r\n')
            elif cmd==b'QUIT':self.wfile.write(b'221 bye\r\n');break
            else:self.wfile.write(b'250 ok\r\n')


class TransportTest(unittest.TestCase):
    def test_real_smtp_connection_without_mail_and_unicode_delivery(self):
        with socketserver.ThreadingTCPServer(('127.0.0.1',0),SMTPFixture) as server:
            server.commands=[];server.messages=[]
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            cfg=dict(host='127.0.0.1',port=server.server_address[1],security='none',username='',password='',sender='monitor@test.invalid',recipient='admin@test.invalid',ca='')
            try:
                result=transport('email',cfg,test=True);self.assertTrue(result['ok'],result)
                self.assertEqual(server.messages,[]);self.assertFalse(any(x.startswith('MAIL ') for x in server.commands))
                event=dict(summary='Störung: Drucker',details='Toner fehlt. Gerät prüfen.',occurred_at='2026-09-27T10:00:00+00:00',event_id='test-event-123',event_url='https://monitoring.intern')
                result=transport('email',cfg,event);self.assertTrue(result['ok'],result);self.assertEqual(len(server.messages),1)
                from email import policy
                from email.parser import BytesParser
                msg=BytesParser(policy=policy.default).parsebytes(server.messages[0]);self.assertIn('Störung',str(msg['Subject']));self.assertIn('Gerät prüfen',msg.get_content())
            finally:server.shutdown();thread.join()

    def test_https_auth_ca_connection_test_and_redirect_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            cert=Path(d)/'server.crt';key=Path(d)/'server.key'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*a):pass
                def do_GET(self):
                    self.server.headers_seen.append(dict(self.headers));self.server.paths.append(self.path)
                    if self.server.redirect:self.send_response(302);self.send_header('Location','https://invalid.invalid/');self.end_headers();return
                    self.send_response(200);self.end_headers();self.wfile.write(json.dumps(dict(data=dict(connected=True,source_type='qisutu'))).encode())
                def do_POST(self):
                    self.server.events.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));self.send_response(202);self.end_headers();self.wfile.write(b'{"data":{"accepted":1,"results":[{"accepted":true,"status":"processed"}]}}')
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(cert,key);server.socket=ctx.wrap_socket(server.socket,server_side=True)
            server.headers_seen=[];server.paths=[];server.events=[];server.redirect=False
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            cfg=dict(url='https://localhost:%d/api.pl/v1/addons/qisutu.monitoring/events/%s'%(server.server_port,'a'*32),token='secret',ca=cert.read_text())
            try:
                result=transport('qisutu',cfg,test=True);self.assertTrue(result['ok'],result);self.assertEqual(server.events,[])
                self.assertTrue(server.paths[0].endswith('/test'));self.assertEqual(server.headers_seen[0]['Authorization'],'Bearer secret')
                self.assertTrue(transport('qisutu',cfg,dict(status='problem'))['ok']);self.assertEqual(len(server.events),1)
                bad=copy.deepcopy(cfg);bad['ca']='';self.assertFalse(transport('qisutu',bad,test=True)['ok'])
                server.redirect=True;self.assertFalse(transport('qisutu',cfg,test=True)['ok'])
            finally:server.shutdown();server.server_close();thread.join()
