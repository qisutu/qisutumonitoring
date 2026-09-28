"""Protocol fixtures and regression coverage for the optional 0.9 integrations."""
import contextlib
import hashlib
import http.server
import json
import shutil
import socket
import socketserver
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape
from netzmonitor.core import Store, Engine
from netzmonitor.services import SERVICE_SELECT
from netzmonitor.integrations import validate, SELECT, probe_integration
from netzmonitor.integration_common import CheckFailure, HTTPS, metric, xml
from netzmonitor.check_protocols import dns_check, parse_dns, mail_check, inspect_certificate, tls_check
from netzmonitor.check_windows import WinRM, windows_check, hyperv_check
from netzmonitor.check_vmware import VSphere, parse_objects, vmware_check
from netzmonitor.check_hardware import redfish_check, synology_metrics, ups_metrics
from netzmonitor.setup import save_configuration
from netzmonitor.history import series


class StorageTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(self.tmp.name)
  self.a=self.s.save_device(dict(name='Router',address='192.0.2.1'));self.b=self.s.save_device(dict(name='Server',address='192.0.2.2'))
 def tearDown(self):self.tmp.cleanup()
 def add(self,kind='tls',config=None,did=None):
  did=did or self.b
  with self.s.connect() as db:
   d=db.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone()
   self.s.save_integrations(db,d,[dict(kind=kind,config=config or {})])
  return self.s.rows(SELECT+' WHERE i.device_id=?',(did,))[0]
 def payload(self,did=None):
  d=next(d for d in self.s.state()['devices'] if d['id']==(did or self.b))
  return dict(id=d['id'],config_token=d['config_token'],name=d['name'],address=d['address'],services=[],resource=None,integrations=[t for t in self.s.integration_state() if t['device_id']==d['id']])
 def ping(self,did):return self.s.save_service(dict(device_id=did,type='ping',name='Ping',interval=30,timeout=1,threshold=2))
 def result(self,sid,kind):
  self.s.record_service(self.s.rows(SERVICE_SELECT+' WHERE s.id=?',(sid,))[0],dict(kind=kind,rtt=1 if kind=='up' else None,message=kind))
 def test_atomic_save_secrets_tokens_and_history(self):
  t=self.add('windows',dict(username='monitor',password='secret-123'))
  self.s.record_integration(t,dict(kind='ok',metrics=[metric('cpu','CPU',17,'%')]))
  initial=self.payload();mid=self.s.integration_state()[0]['metrics'][0]['id']
  self.assertNotIn('secret-123',json.dumps(self.s.state()))
  initial['integrations'][0]['name']='Windows lesbar';save_configuration(self.s,initial)
  self.assertEqual(json.loads(self.s.rows('SELECT config FROM integration_targets')[0]['config'])['password'],'secret-123')
  self.assertEqual(series(self.s,'integration/history',mid,'1h')['summary']['count'],1)
  with self.assertRaisesRegex(ValueError,'zwischenzeitlich'):save_configuration(self.s,initial)
  bad=self.payload();bad['name']='Not saved';bad['integrations'][0]['config']['cpu_warn']=99;bad['integrations'][0]['config']['cpu_crit']=50
  with self.assertRaises(ValueError):save_configuration(self.s,bad)
  self.assertEqual(self.s.rows('SELECT name FROM devices WHERE id=?',(self.b,))[0]['name'],'Server')
 def test_duplicate_save_request_is_applied_once(self):
  import uuid
  p=self.payload();p['integrations']=[dict(kind='tls',config={})];p['request_id']=str(uuid.uuid4())
  first=save_configuration(self.s,p);self.assertEqual(save_configuration(self.s,p),first)
  self.assertEqual(len(self.s.integration_state()),1)
  with self.assertRaisesRegex(ValueError,'anderen Einstellungen'):save_configuration(self.s,{**p,'name':'Other'})
  with self.assertRaisesRegex(ValueError,'zwischenzeitlich'):save_configuration(self.s,{**p,'request_id':str(uuid.uuid4())})
 def test_selected_areas_keep_history_without_false_unknown(self):
  t=self.add('windows',dict(username='monitor',password='secret-123',services=['Spooler']))
  self.s.record_integration(t,dict(kind='ok',metrics=[metric('cpu','CPU',17,'%'),metric('service:Spooler','Druckdienst',1)]))
  old_id=next(m['id'] for m in self.s.integration_state()[0]['metrics'] if m['metric_key']=='service:Spooler')
  p=self.payload();p['integrations'][0]['config']['services']=[];save_configuration(self.s,p)
  t=self.s.rows(SELECT)[0];self.s.record_integration(t,dict(kind='ok',metrics=[metric('cpu','CPU',20,'%')]))
  state=self.s.integration_state()[0];self.assertEqual(state['status'],'up');self.assertEqual(len(state['metrics']),1)
  self.assertEqual(series(self.s,'integration/history',old_id,'1h')['summary']['count'],1)
 def test_transient_missing_metric_recovers(self):
  t=self.add('windows',dict(username='monitor',password='secret-123'))
  self.s.record_integration(t,dict(kind='ok',metrics=[metric('missing:CPU','CPU',None)]))
  self.s.record_integration(t,dict(kind='ok',metrics=[metric('cpu','CPU',7,'%')]))
  self.assertEqual(self.s.integration_state()[0]['status'],'up')
  self.assertEqual(len(self.s.integration_state()[0]['metrics']),1)
 def test_dependencies_cycle_threshold_pause_and_recovery(self):
  parent=self.ping(self.a);child=self.ping(self.b);t=self.add()
  with self.s.connect() as db:self.s.save_dependency(db,self.b,parent)
  self.assertEqual(next(d for d in self.s.state()['devices'] if d['id']==self.b)['status'],'blocked')
  with self.s.connect() as db:
   with self.assertRaisesRegex(ValueError,'Kreis'):self.s.save_dependency(db,self.a,child)
   with self.assertRaisesRegex(ValueError,'Abhängigkeit'):self.s.protect_dependency_source(db,service_id=parent)
  self.result(parent,'up');self.s.refresh_dependencies();t=self.s.rows(SELECT)[0]
  self.result(parent,'down');self.s.refresh_dependencies();self.assertFalse(self.s.rows('SELECT blocked FROM devices WHERE id=?',(self.b,))[0]['blocked'])
  self.result(parent,'down');self.s.refresh_dependencies()
  self.s.record_integration(t,dict(kind='ok',metrics=[metric('days','Tage',365)]))
  self.assertEqual(self.s.rows('SELECT COUNT(*) AS n FROM integration_samples')[0]['n'],0)
  self.result(parent,'up');self.s.refresh_dependencies();self.assertFalse(self.s.rows('SELECT blocked FROM devices WHERE id=?',(self.b,))[0]['blocked'])
  self.s.service_action(parent,'pause');self.s.refresh_dependencies();self.assertTrue(self.s.rows('SELECT blocked FROM devices WHERE id=?',(self.b,))[0]['blocked'])
  with self.assertRaises(ValueError):self.s.service_action(parent,'delete')
  with self.s.connect() as db:self.s.save_dependency(db,self.b,None)
  self.s.refresh_dependencies();self.s.service_action(parent,'delete')
 def test_dependency_recovery_preserves_configuration_token_rejects_old_result(self):
  parent=self.ping(self.a);self.ping(self.b);self.add()
  with self.s.connect() as db:self.s.save_dependency(db,self.b,parent)
  self.s.state();self.result(parent,'up');self.s.refresh_dependencies()
  token=next(d for d in self.s.state()['devices'] if d['id']==self.b)['config_token'];target=self.s.rows(SELECT)[0]
  self.result(parent,'down');self.result(parent,'down');self.s.refresh_dependencies()
  self.result(parent,'up');self.s.refresh_dependencies()
  self.assertEqual(next(d for d in self.s.state()['devices'] if d['id']==self.b)['config_token'],token)
  self.s.record_integration(target,dict(kind='ok',metrics=[metric('days','Tage',365)]))
  self.assertEqual(self.s.rows('SELECT COUNT(*) AS n FROM integration_samples')[0]['n'],0)
 def test_scheduler_does_not_probe_blocked_device(self):
  parent=self.ping(self.a);self.add();calls=[]
  with self.s.connect() as db:self.s.save_dependency(db,self.b,parent)
  engine=Engine(self.s,probe_fn=lambda *_:dict(kind='down',rtt=None,message='down'),integration_probe=lambda t:calls.append(t) or dict(kind='ok',metrics=[metric('x','X',1)]))
  engine.start()
  try:
   time.sleep(.7);self.assertEqual(calls,[])
  finally:engine.close()
 def test_template_and_fleet_integrations(self):
  self.add('windows',dict(username='monitor',password='secret-123'))
  tid=self.s.save_template(dict(device_id=self.b,name='Windows',include_credentials=True))['id']
  self.assertNotIn('secret-123',json.dumps(self.s.state()))
  body=dict(action='template',template_id=tid,ids=[self.a]);preview=self.s.fleet_change(body)
  self.assertEqual(len(self.s.rows('SELECT * FROM integration_targets')),1)
  self.s.fleet_change({**body,'preview_token':preview['preview_token']},True)
  t=self.s.rows(SELECT+' WHERE i.device_id=?',(self.a,))[0];self.assertEqual(json.loads(t['config'])['host'],'192.0.2.1')
  preview=self.s.fleet_change(body);self.s.fleet_change({**body,'preview_token':preview['preview_token']},True)
  self.assertEqual(len(self.s.rows('SELECT * FROM integration_targets')),2)
  body=dict(action='rules',ids=[self.a],rules=dict(interval=120,cpu_warn=75));preview=self.s.fleet_change(body);self.s.fleet_change({**body,'preview_token':preview['preview_token']},True)
  t=self.s.rows(SELECT+' WHERE i.device_id=?',(self.a,))[0];self.assertEqual(t['interval'],120);self.assertEqual(json.loads(t['config'])['cpu_warn'],75)
 def test_restart_and_additive_schema_migration(self):
  sid=self.ping(self.a);self.result(sid,'up')
  with self.s.connect() as db:
   for table in ('integration_samples','integration_metrics','integration_targets','device_dependencies'):db.execute('DROP TABLE '+table)
   db.execute('ALTER TABLE devices DROP COLUMN blocked');db.execute('ALTER TABLE devices DROP COLUMN block_reason')
  migrated=Store(self.tmp.name);self.assertEqual(len(migrated.state()['devices']),2)
  self.assertEqual(len(migrated.rows('SELECT * FROM service_samples')),1)
  self.assertEqual(len(Store(self.tmp.name).state()['services']),1)
 def test_tls_daily_defaults_and_failure_retries(self):
  t=self.add();self.assertEqual(t['interval'],86400)
  dns=self.s.integration_value(dict(kind='dns',config=dict(query='example.org')),dict(id=self.a,address='192.0.2.1'))
  self.assertEqual(dns['interval'],60)
  for attempt in range(1,4):
   self.s.record_integration(t,dict(kind='error',message='TLS nicht erreichbar.',metrics=[]))
   current=self.s.rows(SELECT)[0]
   self.assertEqual(current['next_check']-current['last_checked'],60 if attempt<3 else 86400)
   self.assertEqual(current['status'],'warning' if attempt<3 else 'error')
  self.s.record_integration(t,dict(kind='ok',metrics=[metric('days','Restlaufzeit',4,'Tage',status='critical')]))
  current=self.s.rows(SELECT)[0]
  self.assertEqual(current['status'],'critical');self.assertEqual(current['failures'],0)
  self.assertEqual(current['next_check']-current['last_checked'],86400)
 def test_tls_migration_runs_once_preserves_custom_and_history(self):
  t=self.add();self.s.record_integration(t,dict(kind='ok',metrics=[metric('days','Restlaufzeit',137,'Tage')]))
  other=self.add(did=self.a);samples=self.s.rows('SELECT * FROM integration_samples')
  with self.s.connect() as db:
   db.execute("DELETE FROM schema_migrations WHERE name='tls-daily-default'")
   db.execute('UPDATE integration_targets SET interval=60 WHERE id=?',(t['id'],))
   db.execute('UPDATE integration_targets SET interval=3600 WHERE id=?',(other['id'],))
  store=Store(self.tmp.name);migrated=store.rows(SELECT+' WHERE i.id=?',(t['id'],))[0]
  self.assertEqual(migrated['interval'],86400);self.assertEqual(migrated['next_check']-migrated['last_checked'],86400)
  self.assertEqual(store.rows(SELECT+' WHERE i.id=?',(other['id'],))[0]['interval'],3600)
  self.assertEqual(store.rows('SELECT * FROM integration_samples'),samples)
  with store.connect() as db:db.execute('UPDATE integration_targets SET interval=60 WHERE id=?',(t['id'],))
  self.assertEqual(Store(self.tmp.name).rows(SELECT+' WHERE i.id=?',(t['id'],))[0]['interval'],60)
 def test_tls_restart_preserves_future_due_date(self):
  t=self.add();self.s.record_integration(t,dict(kind='ok',metrics=[metric('days','Restlaufzeit',137,'Tage')]))
  due=self.s.rows(SELECT)[0]['next_check'];calls=[]
  engine=Engine(self.s,integration_probe=lambda t:calls.append(t) or dict(kind='error',message='Unexpected call'))
  engine.start()
  try:
   time.sleep(.7);self.assertEqual(calls,[]);self.assertEqual(self.s.rows(SELECT)[0]['next_check'],due)
  finally:engine.close()
 def test_partial_resource_measurements_expose_specific_problem(self):
  from netzmonitor.resources import RESOURCE_SELECT
  from netzmonitor.extended import DEFAULT
  from test_resources import healthy
  self.s.save_resource(dict(device_id=self.b,method='snmp',port=161,version='2c',community='fixture',advanced={**DEFAULT,'hardware':True}))
  target=self.s.rows(RESOURCE_SELECT)[0];self.s.record_resource(target,healthy())
  state=self.s.state();device=next(d for d in state['devices'] if d['id']==self.b)
  self.assertEqual(device['status'],'unknown');self.assertEqual(device['status_label'],'Messwerte unvollständig')
  self.assertTrue(all(m['status']=='up' for m in state['resources'][0]['metrics']))
  missing=next(m for m in state['extended'] if m['status']=='unknown')
  self.assertIn(missing['label'],device['message']);self.assertTrue(missing['message'])
 def test_validation_tls_pin_and_mail_credentials(self):
  with self.assertRaises(ValueError):validate('smtp',dict(host='localhost',security='plain',username='user',password='secret'))
  with self.assertRaises(ValueError):validate('tls',dict(host='localhost',warn_days=5,critical_days=10))
  old=validate('tls',dict(host='localhost',fingerprint='a'*64))
  with self.assertRaises(ValueError):validate('tls',{**old,'host':'new.example'},old)
  self.assertEqual(validate('ups',dict(host='localhost',version='2c',community='private'))['port'],161)


class DNSHandler(socketserver.BaseRequestHandler):
 def handle(self):
  data,sock=self.request;ident=struct.unpack('!H',data[:2])[0]
  reply=struct.pack('!6H',ident,0x8180,1,1,0,0)+data[12:]+b'\xc0\x0c'+struct.pack('!HHIH',1,1,60,4)+socket.inet_aton('192.0.2.10')
  sock.sendto(reply,self.client_address)

class ProtocolTests(unittest.TestCase):
 def test_live_dns_expected_answer(self):
  with socketserver.UDPServer(('127.0.0.1',0),DNSHandler) as server:
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    cfg=validate('dns',dict(host='127.0.0.1',port=server.server_address[1],query='host.example',expected='192.0.2.10'))
    self.assertEqual(dns_check(cfg,1)[0]['status'],'up')
    cfg['expected']='192.0.2.11';self.assertEqual(dns_check(cfg,1)[0]['status'],'critical')
    result=probe_integration(dict(kind='dns',config=cfg,timeout=3));self.assertEqual(result['kind'],'ok')
   finally:server.shutdown();thread.join()
 def test_live_imap_and_pop3_protocol_only(self):
  for kind in ('imap','pop3'):
   commands=[]
   class Mail(socketserver.StreamRequestHandler):
    def handle(self):
     self.wfile.write(b'* OK IMAP4rev1 ready\r\n' if kind=='imap' else b'+OK POP3 ready\r\n')
     while True:
      line=self.rfile.readline().strip();commands.append(line)
      if not line:break
      if kind=='imap':
       tag,command=line.split()[:2]
       if command.upper()==b'CAPABILITY':self.wfile.write(b'* CAPABILITY IMAP4rev1\r\n'+tag+b' OK capability\r\n')
       elif command.upper()==b'NOOP':self.wfile.write(tag+b' OK noop\r\n')
       elif command.upper()==b'LOGOUT':self.wfile.write(b'* BYE bye\r\n'+tag+b' OK logout\r\n');break
      else:
       if line.upper()==b'CAPA':self.wfile.write(b'+OK capabilities\r\nUIDL\r\n.\r\n')
       elif line.upper()==b'QUIT':self.wfile.write(b'+OK bye\r\n');break
   with socketserver.ThreadingTCPServer(('127.0.0.1',0),Mail) as server:
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
     cfg=validate(kind,dict(host='127.0.0.1',port=server.server_address[1],security='plain'))
     self.assertEqual(mail_check(kind,cfg,2)[0]['status'],'up')
     self.assertFalse(any(c.upper().startswith((b'RETR',b'DELE',b'STOR',b'USER')) for c in commands))
    finally:server.shutdown();thread.join()
 def test_malformed_dns_xml_rejected(self):
  with self.assertRaises(CheckFailure):parse_dns(b'123',1,'example',1)
  data=struct.pack('!6H',1,0x8180,1,0,0,0)+b'\xc0\x0c'+struct.pack('!HH',1,1)
  with self.assertRaises(CheckFailure):parse_dns(data,1,'example',1)
  with self.assertRaises(CheckFailure):xml(b'<!DOCTYPE a [<!ENTITY x "boom">]><a>&x;</a>')
 def test_vendor_snmp_status_interpretation(self):
  root='.1.3.6.1.4.1.6574';m=synology_metrics({root+'.1.1.0':1,root+'.1.2.0':45},{root+'.2.1.1.5.0':5,root+'.2.1.1.12.0':'Disk 1'},{root+'.3.1.1.3.0':11})
  self.assertEqual(next(x for x in m if x['key']=='disk:0:state')['status'],'critical')
  self.assertEqual(next(x for x in m if x['key']=='raid:0')['status'],'critical')
  root='.1.3.6.1.2.1.33.1';m=ups_metrics({root+'.2.1.0':3,root+'.4.1.0':5,root+'.2.3.0':7,root+'.4.4.1.5.1':99})
  self.assertEqual(next(x for x in m if x['key']=='source')['status'],'warning')
  self.assertEqual(next(x for x in m if x['key']=='load:1')['status'],'critical')
 def test_winrm_pagination_and_release(self):
  pages=[xml(b'<Envelope><Items><Row><Name>a</Name></Row></Items><EnumerationContext>ctx</EnumerationContext></Envelope>'),xml(b'<Envelope><Items><Row><Name>b</Name></Row></Items><EndOfSequence/></Envelope>')]
  client=WinRM(dict(host='localhost',port=5986),1)
  with patch.object(client,'request',side_effect=pages) as request:
   self.assertEqual([r['Name'] for r in client.query('SELECT Name FROM Test')],['a','b']);self.assertEqual(request.call_args_list[1].args[0],'Pull')
  with patch.object(client,'request',side_effect=[pages[0],CheckFailure('denied'),xml(b'<ok/>')]) as request:
   with self.assertRaises(CheckFailure):client.query('SELECT Name FROM Test')
   self.assertEqual(request.call_args_list[-1].args[0],'Release')
 def test_windows_metrics_and_optional_service(self):
  cfg=validate('windows',dict(host='localhost',username='read',password='secret',services=['Spooler'],event_errors=True))
  def query(self,q,*args,**kwargs):
   if 'Win32_Processor' in q:return [dict(LoadPercentage='90')]
   if 'Win32_OperatingSystem' in q:return [dict(TotalVisibleMemorySize='10000',FreePhysicalMemory='2000')]
   if 'Win32_LogicalDisk' in q:return [dict(DeviceID='C:',Size='1000',FreeSpace='10')]
   if 'Win32_Service' in q:return [dict(Name='Spooler',State='Stopped')]
   return [dict(RecordNumber='1')]
  with patch.object(WinRM,'query',query):m=windows_check(cfg,1)
  by={x['key']:x for x in m};self.assertEqual(by['cpu']['status'],'warning');self.assertEqual(by['disk:C:']['status'],'critical');self.assertEqual(by['service:Spooler']['status'],'critical');self.assertEqual(by['events:System']['value'],1)
 def test_vm_off_is_optional_missing_expected_is_critical(self):
  cfg=validate('hyperv',dict(host='localhost',username='read',password='secret'))
  rows=[dict(Caption='Virtual Machine',Name='id1',ElementName='Test VM',EnabledState='3',HealthState='0')]
  with patch.object(WinRM,'query',return_value=rows):m,inv=hyperv_check(cfg,1)
  self.assertTrue(all(x['status']=='up' for x in m));self.assertEqual(inv[0]['id'],'id1')
  cfg['expected_running']=['id1','missing']
  with patch.object(WinRM,'query',return_value=rows):m,_=hyperv_check(cfg,1)
  self.assertEqual(sum(x['status']=='critical' for x in m),2)
 def test_vmware_object_decoding(self):
  obj=xml(b'''<objects><obj type="VirtualMachine">vm-1</obj><propSet><name>name</name><val>Example</val></propSet><propSet><name>summary</name><val><runtime><powerState>poweredOff</powerState></runtime><overallStatus>gray</overallStatus></val></propSet></objects>''')
  cfg=validate('vmware',dict(host='localhost',username='read',password='secret'))
  m,inv=parse_objects([obj],cfg);self.assertTrue(all(x['status']=='up' for x in m));self.assertEqual(inv,[dict(id='vm-1',name='Example')])
  cfg['expected_running']=['vm-1'];m,_=parse_objects([obj],cfg);self.assertEqual(next(x for x in m if x['key'].endswith(':power'))['status'],'critical')


@unittest.skipUnless(shutil.which('openssl'),'TLS fixture needs openssl')
class TLSTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();path=Path(cls.tmp.name);cls.cert=path/'cert.pem';cls.key=path/'key.pem'
  subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN=localhost','-keyout',str(cls.key),'-out',str(cls.cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  cls.context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);cls.context.load_cert_chain(str(cls.cert),str(cls.key));cls.pin=hashlib.sha256(ssl.PEM_cert_to_DER_cert(cls.cert.read_text())).hexdigest()
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 @contextlib.contextmanager
 def server(self,routes):
  calls=[];context=self.context
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def handle(self):
    try:super().handle()
    except (ssl.SSLError,BrokenPipeError,ConnectionResetError):pass
   def do_POST(self):
    body=self.rfile.read(int(self.headers.get('Content-Length',0)));calls.append((self.path,body))
    data=routes[self.path](body)
    self.send_response(200);self.send_header('Content-Type','text/xml');self.send_header('Set-Cookie','vmware_soap_session="fixture"; Path=/; Secure');self.end_headers();self.wfile.write(data)
   def do_GET(self):
    calls.append((self.path,self.headers.get('Authorization')));data=routes.get(self.path)
    self.send_response(200 if data is not None else 404);self.end_headers()
    try:self.wfile.write(json.dumps(data).encode())
    except (ssl.SSLError,BrokenPipeError):pass
  server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.socket=context.wrap_socket(server.socket,server_side=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:yield dict(host='127.0.0.1',port=server.server_port,fingerprint=self.pin,username='reader',password='secret'),calls
  finally:server.shutdown();server.server_close();thread.join()
 def test_tls_expiry_pin_and_no_credentials_before_trust(self):
  with self.server({'/':{'ok':True}}) as (cfg,calls):
   certcfg=validate('tls',cfg);metrics=tls_check(certcfg,2)
   self.assertEqual(metrics[0]['status'],'critical');self.assertGreater(metrics[0]['value'],1)
   self.assertEqual(inspect_certificate({**cfg,'protocol':'tls','security':'tls'},2),self.pin)
   with self.assertRaises(CheckFailure):HTTPS({**cfg,'fingerprint':'0'*64},2).json('/')
   self.assertEqual(calls,[])
   self.assertTrue(HTTPS(cfg,2).json('/')['ok']);self.assertTrue(calls[0][1].startswith('Basic '))
   with self.assertRaises(CheckFailure):HTTPS(cfg,2).json('https://outside.invalid/data')
   result=probe_integration(dict(kind='tls',config=certcfg,timeout=3));self.assertEqual(result['kind'],'ok')
 def test_redfish_health_embedded_and_linked(self):
  routes={'/redfish/v1/':{'Systems':{'@odata.id':'/systems'},'Chassis':{'@odata.id':'/chassis'}},'/systems':{'Members':[{'@odata.id':'/system/1'}]},'/chassis':{'Members':[{'@odata.id':'/chassis/1'}]},'/system/1':{'Name':'Server','Status':{'Health':'OK'},'Storage':{'@odata.id':'/storage'}},'/storage':{'Members':[{'@odata.id':'/storage/1'}]},'/storage/1':{'Name':'Controller','Status':{'Health':'Critical'},'Drives':[{'@odata.id':'/drive/1'}]},'/drive/1':{'Name':'Disk 1','Status':{'Health':'Warning'}},'/chassis/1':{'Thermal':{'@odata.id':'/thermal'},'Power':{'@odata.id':'/power'}},'/thermal':{'Temperatures':[{'Name':'CPU','ReadingCelsius':85,'UpperThresholdNonCritical':80,'UpperThresholdCritical':95}]},'/power':{'PowerSupplies':[{'Name':'PSU','Status':{'Health':'OK'}}]}}
  with self.server(routes) as (cfg,_):
   metrics=redfish_check(validate('redfish',cfg),2)
   self.assertTrue(any(m['label']=='Controller · Zustand' and m['status']=='critical' for m in metrics))
   self.assertTrue(any(m['unit']=='°C' and m['status']=='warning' for m in metrics))
   self.assertFalse(any(m['status']=='unknown' for m in metrics))
 def test_live_winrm_and_vsphere_soap_pagination_cleanup(self):
  operations=[]
  def winrm(body):
   root=xml(body);action=next(n.text for n in root.iter() if n.tag.endswith('}Action')).rsplit('/',1)[1];operations.append(action)
   if action=='Enumerate':
    self.assertIn(b'http://schemas.microsoft.com/wbem/wsman/1/WQL',body)
    return b'<Envelope><Items><Win32_Processor><LoadPercentage>12</LoadPercentage></Win32_Processor></Items><EnumerationContext>ctx</EnumerationContext></Envelope>'
   return b'<Envelope><Items><Win32_Processor><LoadPercentage>20</LoadPercentage></Win32_Processor></Items><EndOfSequence/></Envelope>'
  def vsphere(body):
   root=xml(body);method=list(list(root)[0])[0].tag.rsplit('}',1)[-1];operations.append(method)
   if method=='RetrieveServiceContent':return b'<Envelope><returnval><sessionManager type="SessionManager">SessionManager</sessionManager><viewManager type="ViewManager">ViewManager</viewManager><rootFolder type="Folder">root</rootFolder><propertyCollector type="PropertyCollector">pc</propertyCollector></returnval></Envelope>'
   if method=='CreateContainerView':return b'<Envelope><returnval type="ContainerView">view-1</returnval></Envelope>'
   if method=='RetrievePropertiesEx':return b'<Envelope><returnval><token>next</token></returnval></Envelope>'
   if method=='ContinueRetrievePropertiesEx':return b'<Envelope><returnval><objects><obj type="Datastore">ds-1</obj><propSet><name>name</name><val>Storage</val></propSet><propSet><name>summary</name><val><accessible>true</accessible><capacity>1000</capacity><freeSpace>10</freeSpace></val></propSet></objects></returnval></Envelope>'
   return b'<Envelope/>'
  with self.server({'/wsman':winrm,'/sdk':vsphere}) as (cfg,calls):
   rows=WinRM(cfg,2).query('SELECT LoadPercentage FROM Win32_Processor');self.assertEqual(len(rows),2);self.assertIn('Pull',operations)
   m,_=vmware_check(validate('vmware',cfg),2);self.assertEqual(next(x for x in m if x['key'].endswith(':space'))['status'],'critical')
   self.assertEqual(operations[-2:],['DestroyView','Logout']);self.assertIn('ContinueRetrievePropertiesEx',operations)
 def test_smtp_starttls_and_protocol_only(self):
  context=self.context;commands=[]
  class SMTP(socketserver.StreamRequestHandler):
   def finish(self):
    super().finish();self.connection.close()
   def handle(self):
    self.wfile.write(b'220 test ESMTP\r\n')
    while True:
     line=self.rfile.readline().strip();commands.append(line)
     if not line:break
     command=line.split()[0].upper()
     if command==b'EHLO':self.wfile.write(b'250-test\r\n250 STARTTLS\r\n')
     elif command==b'STARTTLS':
      self.wfile.write(b'220 TLS ready\r\n');self.wfile.flush();self.connection=context.wrap_socket(self.connection,server_side=True);self.rfile=self.connection.makefile('rb');self.wfile=self.connection.makefile('wb',buffering=0)
     elif command==b'NOOP':self.wfile.write(b'250 OK\r\n')
     elif command==b'QUIT':self.wfile.write(b'221 Bye\r\n');break
     else:self.wfile.write(b'500 unsupported\r\n')
  with socketserver.ThreadingTCPServer(('127.0.0.1',0),SMTP) as server:
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    cfg=validate('smtp',dict(host='127.0.0.1',port=server.server_address[1],fingerprint=self.pin,security='starttls'))
    self.assertEqual(mail_check('smtp',cfg,2)[0]['status'],'up');self.assertIn(b'NOOP',[c.upper() for c in commands])
    self.assertFalse(any(c.upper().startswith((b'MAIL',b'RCPT',b'DATA',b'AUTH')) for c in commands))
   finally:server.shutdown();thread.join()

if __name__=='__main__':unittest.main()
