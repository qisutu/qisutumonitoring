from account_fixture import configuration
"""Regression: a device is a container, only configured checks determine health."""
import http.server
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'vendor')]
from netzmonitor.core import Store,Engine
from netzmonitor.services import SERVICE_SELECT
from netzmonitor.server import WebApp
from test_services import Handler

class DeviceChecksTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
  self.did=self.store.save_device({'name':'Server ohne ICMP','address':'127.0.0.1'})
  self.ping=Mock(return_value=dict(kind='down',rtt=None,message='Keine Ping-Antwort.',ip='127.0.0.1'))
  self.engine=Engine(self.store,probe_fn=self.ping);self.web=WebApp((configuration(self.temp.name) or self.temp.name),self.engine)
 def tearDown(self):
  self.engine.close();self.web.executor.shutdown();self.temp.cleanup()
 def current(self):return self.store.state()['devices'][0]
 def service(self,ident):return self.store.rows(SERVICE_SELECT+' WHERE s.id=?',(ident,))[0]
 def device_action(self,action):return self.web.dispatch('POST','device/action',{'id':self.did,'action':action},{})
 def wait(self,predicate):
  limit=time.monotonic()+4
  while not predicate() and time.monotonic()<limit:time.sleep(.02)
  self.assertTrue(predicate())
 def add_ping(self):return self.store.save_service({'device_id':self.did,'name':'ICMP','type':'ping','threshold':1})
 def record(self,sid,kind='up'):
  self.store.record_service(self.service(sid),dict(kind=kind,rtt=1 if kind=='up' else None,message='OK' if kind=='up' else 'Keine Ping-Antwort.'))
 def test_device_without_checks_stays_neutral_and_never_pings(self):
  self.device_action('check');self.engine.start();time.sleep(.6)
  self.assertEqual(self.current()['status'],'unmonitored')
  self.assertEqual(self.current()['checks_total'],0);self.ping.assert_not_called()
  self.assertEqual(self.store.rows('SELECT * FROM service_samples'),[])
  self.assertEqual(Store(self.temp.name).state()['services'],[])
 def test_real_http_success_despite_blocked_icmp(self):
  server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   sid=self.store.save_service({'device_id':self.did,'name':'Webseite','type':'http','url':'http://127.0.0.1:%s/'%server.server_port,'threshold':1})
   self.engine.start();self.wait(lambda:self.current()['status']=='up');self.ping.assert_not_called()
   pid=self.add_ping();self.wait(lambda:self.current()['status']=='down')
   self.assertEqual(self.current()['status_label'],'Keine Ping-Antwort')
   self.assertEqual(self.service(sid)['status'],'up');self.ping.assert_called_once()
   self.store.service_action(pid,'pause');self.assertEqual(self.current()['status'],'up')
   self.store.service_action(pid,'delete');self.assertEqual(self.current()['status'],'up')
   self.store.service_action(sid,'delete');self.assertEqual(self.current()['status'],'unmonitored')
  finally:server.shutdown();server.server_close();thread.join(2)
 def test_parent_pause_resume_keeps_individual_pause(self):
  first=self.add_ping();second=self.store.save_service({'device_id':self.did,'name':'SSH','type':'tcp','port':22})
  self.record(first);self.store.service_action(second,'pause');self.device_action('pause')
  self.assertEqual(self.current()['status'],'paused');self.assertEqual(self.current()['checks_active'],0)
  self.assertTrue(all(s['effective_status']=='paused' for s in self.store.state()['services']))
  self.device_action('resume');self.assertEqual(self.service(second)['enabled'],0)
  self.assertEqual(self.current()['checks_active'],1)
  self.store.service_action(first,'pause');self.assertEqual(self.current()['status_label'],'Alle Prüfungen pausiert')
 def test_address_change_clears_ping_tcp_but_keeps_http_history(self):
  ping=self.add_ping();tcp=self.store.save_service({'device_id':self.did,'name':'TCP','type':'tcp','port':22})
  http=self.store.save_service({'device_id':self.did,'name':'HTTP','type':'http','url':'https://example.invalid/'})
  for sid in (ping,tcp,http):self.record(sid)
  self.store.save_device({'id':self.did,'name':'Neuer Name','address':'127.0.0.1'})
  self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')),3)
  stale=self.service(ping)
  self.store.save_device({'id':self.did,'name':'Neuer Name','address':'192.0.2.7'})
  self.assertEqual([s['service_id'] for s in self.store.rows('SELECT * FROM service_samples')],[http])
  self.store.record_service(stale,dict(kind='up',rtt=1,message='Late response'))
  self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')),1)
  self.assertIsNone(self.service(ping)['last_checked']);self.assertIsNone(self.service(tcp)['last_checked'])
 def test_stale_and_pending_checks_are_not_reported_as_ok(self):
  sid=self.add_ping();self.assertEqual(self.current()['status'],'pending');self.record(sid)
  with self.store.connect() as db:db.execute('UPDATE services SET last_checked=? WHERE id=?',(time.time()-300,sid))
  self.assertEqual(self.current()['status'],'stale')
  self.store.service_action(sid,'pause');self.assertEqual(self.current()['status'],'paused')

if __name__=='__main__':unittest.main()
