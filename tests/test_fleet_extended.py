import copy
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_resources import healthy
from netzmonitor.core import Store
from netzmonitor.resources import RESOURCE_SELECT
from netzmonitor.extended import DEFAULT, counter_rate
from netzmonitor.collect_extended import IF,IFX,SENSOR,ENTITY,parse_interfaces,parse_sensors,parse_ssh,ssh_script
from netzmonitor.ssh_resources import COLLECTOR
from netzmonitor.history import series
from netzmonitor.setup import save_configuration


class FleetExtendedTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
  self.a=self.store.save_device(dict(name='Vorlage',address='192.0.2.10'))
  self.b=self.store.save_device(dict(name='Ziel',address='192.0.2.11'))
 def tearDown(self):self.tmp.cleanup()
 def target(self,advanced=None,did=None):
  rid=self.store.save_resource(dict(device_id=did or self.a,method='snmp',port=161,version='2c',community='never-return-this-secret',advanced=advanced or DEFAULT))
  return self.store.rows(RESOURCE_SELECT+' WHERE r.id=?',(rid,))[0]
 def change(self,body):
  preview=self.store.fleet_change(body)
  return self.store.fleet_change({**body,'preview_token':preview['preview_token']},True)
 def test_groups_preview_and_delete_preserve_devices(self):
  gid=self.store.save_group(dict(name='Berlin'))['id']
  body=dict(ids=[self.a,self.b],action='group_add',group_id=gid)
  preview=self.store.fleet_change(body)
  self.assertEqual(self.store.fleet_state()['group_members'],[])
  self.store.fleet_change({**body,'preview_token':preview['preview_token']},True)
  self.assertEqual(len(self.store.fleet_state()['group_members']),2)
  self.store.delete_fleet_item('group',gid)
  self.assertEqual(len(self.store.state()['devices']),2)
 def test_templates_url_credentials_repeat_preserve_history(self):
  self.store.save_service(dict(device_id=self.a,name='Web',type='http',url='https://192.0.2.10/app'))
  self.store.save_service(dict(device_id=self.a,name='Extern',type='http',url='https://example.invalid/shared'))
  self.target({**DEFAULT,'network':True})
  tid=self.store.save_template(dict(name='Linux',device_id=self.a,include_credentials=True))['id']
  self.assertNotIn('never-return-this-secret',json.dumps(self.store.state()))
  body=dict(ids=[self.b],action='template',template_id=tid)
  self.assertEqual(self.store.fleet_change(body)['devices'][0]['added'],2)
  self.assertEqual(self.store.rows('SELECT * FROM services WHERE device_id=?',(self.b,)),[])
  self.change(body)
  services=self.store.rows('SELECT * FROM services WHERE device_id=?',(self.b,))
  self.assertEqual({s['url'] for s in services},{'https://192.0.2.11/app','https://example.invalid/shared'})
  target=self.store.rows(RESOURCE_SELECT+' WHERE r.device_id=?',(self.b,))[0]
  self.assertEqual(target['community'],'never-return-this-secret')
  self.store.record_resource(target,healthy())
  before=self.store.rows('SELECT * FROM resource_samples')
  self.change(body)
  self.assertEqual(self.store.rows('SELECT * FROM resource_samples'),before)
  self.assertEqual(len(self.store.rows('SELECT * FROM services WHERE device_id=?',(self.b,))),2)
  self.store.delete_fleet_item('template',tid)
  self.assertEqual(self.store.rows('SELECT * FROM resource_samples'),before)
 def test_templates_no_credentials_and_invalid_later_device_are_atomic(self):
  self.target();tid=self.store.save_template(dict(name='No password',device_id=self.a))['id']
  with self.assertRaises(ValueError):self.store.fleet_change(dict(ids=[self.a,self.b],action='template',template_id=tid))
  self.assertEqual(self.store.rows('SELECT * FROM template_members'),[])
  self.assertEqual(len(self.store.resource_state()),1)
 def test_preview_rejects_concurrent_edits_and_new_rules(self):
  self.store.save_service(dict(device_id=self.a,type='tcp',port=22,name='SSH'))
  body=dict(ids=[self.a,self.b],action='rules',rules={'interval':100})
  preview=self.store.fleet_change(body)
  self.store.save_device(dict(id=self.a,name='Geändert',address='192.0.2.10'))
  with self.assertRaisesRegex(ValueError,'geändert'):self.store.fleet_change({**body,'preview_token':preview['preview_token']},True)
  self.assertNotEqual(self.store.rows('SELECT interval FROM services')[0]['interval'],100)
  self.change(body);self.assertEqual(self.store.rows('SELECT interval FROM services')[0]['interval'],100)
 def test_invalid_rules_rollback_all_targets(self):
  self.store.save_service(dict(device_id=self.a,type='tcp',port=22,name='SSH'))
  self.target(did=self.b)
  before=self.store.rows('SELECT * FROM services')
  with self.assertRaises(ValueError):self.store.fleet_change(dict(ids=[self.a,self.b],action='rules',rules={'interval':5}))
  self.assertEqual(self.store.rows('SELECT * FROM services'),before)
 def test_network_rates_reboot_discontinuity_wrap_and_history(self):
  t=self.target({**DEFAULT,'basic':False,'network':True})
  n=dict(name='eth0',identity='1:mac',epoch='boot',clock=100,speed=1e9,bits=64,error_bits=64,oper=1,admin=1,rx=1000,tx=2000,rx_errors=0,tx_errors=0,rx_drops=0,tx_drops=0)
  def record(at,row):
   with patch('netzmonitor.resources.time.time',return_value=at):self.store.record_resource(t,dict(kind='ok',metrics=[],interfaces=[row],message=''))
  record(1000,n);self.assertEqual(self.store.resource_state()[0]['status'],'pending')
  n2={**n,'clock':160,'rx':1000+75000000,'tx':2000+150000000}
  record(1060,n2)
  metrics=self.store.extended_state();by={m['channel']:m for m in metrics}
  self.assertEqual(by['Empfang']['value'],10);self.assertEqual(by['Versand']['value'],20)
  self.assertEqual(by['Auslastung Empfang']['value'],1)
  self.assertEqual(self.store.resource_state()[0]['status'],'up')
  self.assertEqual(series(self.store,'extended/history',by['Empfang']['id'],'1h',now=1060)['summary']['maximum'],10)
  record(1120,{**n2,'clock':2,'rx':1,'tx':1})
  self.assertIsNone(next(m['value'] for m in self.store.extended_state() if m['channel']=='Empfang'))
  self.assertEqual(counter_rate(2**32-100,50,1,32,1000),150)
  self.assertIsNone(counter_rate(1,2,60,32,1e9/8))
  self.assertIsNone(counter_rate(100,1,60))
  record(1180,{**n2,'clock':160,'epoch':'new'})
  self.assertIsNone(next(m['value'] for m in self.store.extended_state() if m['channel']=='Empfang'))
 def test_unused_port_and_expected_link_and_pause(self):
  cfg={**DEFAULT,'basic':False,'network':True}
  t=self.target(cfg)
  r=dict(kind='ok',metrics=[],interfaces=[dict(name='port1',identity='1',epoch=0,clock=1,speed=1e9,oper=2,admin=1,rx=0,tx=0,rx_errors=0,tx_errors=0,rx_drops=0,tx_drops=0)],message='')
  self.store.record_resource(t,r)
  self.assertEqual(next(m['status'] for m in self.store.extended_state() if m['channel']=='Verbindung'),'up')
  self.store.save_resource({**t,'advanced':{**cfg,'interfaces':{'port1':{'expect_up':True}}}});t=self.store.rows(RESOURCE_SELECT)[0]
  self.store.record_resource(t,r)
  self.assertEqual(self.store.resource_state()[0]['status'],'critical')
  self.store.save_resource({**t,'advanced':{**cfg,'interfaces':{'port1':{'enabled':False,'expect_up':True}}}});t=self.store.rows(RESOURCE_SELECT)[0]
  self.store.record_resource(t,r)
  self.assertEqual(self.store.resource_state()[0]['status'],'up')
  self.assertTrue(all(m['status']=='paused' for m in self.store.extended_state()))
 def test_failed_poll_and_disappeared_sensor_are_not_green(self):
  from netzmonitor.extended import metric
  t=self.target({**DEFAULT,'basic':False,'hardware':True})
  self.store.record_resource(t,dict(kind='ok',metrics=[],extended=[metric('hardware','CPU','Temperatur',95,'°C',warn=70,critical=85)],message=''))
  self.assertEqual(self.store.resource_state()[0]['status'],'critical')
  self.store.record_resource(t,dict(kind='ok',metrics=[],extended=[],message=''))
  self.assertEqual(self.store.resource_state()[0]['status'],'unknown')
  self.assertIsNone(next(m['value'] for m in self.store.extended_state() if m['entity']=='CPU'))
 def test_disk_io_linux_process_service_and_smart_parsing(self):
  text='''NM_CLOCK|120 100
NM_BOOT|boot
NM_IO|sda|10 0 100 50 20 0 200 70 0 300 400
NM_SENSOR|CPU|temp1|92000|80000|90000|?|0|0|
NM_RAID|md0|1|active|idle|
NM_PROCESSES_BEGIN
sshd
sshd
python3
NM_PROCESSES_END
NM_UNIT_BEGIN|nginx.service
LoadState=loaded
ActiveState=inactive
SubState=dead
NM_UNIT_END
NM_SMART_BEGIN|sda
{"smart_status":{"passed":false}}
NM_SMART_END
'''
  cfg={**DEFAULT,'disk_io':True,'hardware':True,'smart':True,'processes':['sshd','missing'],'services':['nginx.service']}
  parsed=parse_ssh(text,{'advanced':cfg})
  self.assertEqual(parsed['disk_counters'][0]['read_bytes'],51200)
  values={(m['entity'],m['channel']):m for m in parsed['extended']}
  self.assertEqual(values['sshd','Laufende Prozesse']['value'],2)
  self.assertEqual(values['missing','Laufende Prozesse']['status'],'critical')
  self.assertEqual(values['nginx.service','Aktiv']['status'],'critical')
  self.assertEqual(values['sda','SMART Gesamtzustand']['status'],'critical')
  self.assertEqual(values['CPU','Temperatur']['value'],92)
  t=self.target({**DEFAULT,'basic':False,'hardware':True})
  # Disk counters share the same persistence code regardless of test transport.
  with self.store.connect() as db:db.execute('UPDATE resource_targets SET advanced=? WHERE id=?',(json.dumps(cfg),t['id']))
  t=self.store.rows(RESOURCE_SELECT)[0];r=dict(kind='ok',metrics=[],message='',**parsed)
  with patch('netzmonitor.resources.time.time',return_value=1000):self.store.record_resource(t,r)
  r=copy.deepcopy(r);r['disk_counters'][0].update(clock=180,read_bytes=51200+60*1048576,reads=70,read_ms=170,busy_ms=3300)
  with patch('netzmonitor.resources.time.time',return_value=1060):self.store.record_resource(t,r)
  values={m['channel']:m for m in self.store.extended_state() if m['category']=='disk_io'}
  self.assertEqual(values['Lesen']['value'],1);self.assertEqual(values['Leseoperationen']['value'],1);self.assertEqual(values['Beschäftigungszeit']['value'],5)
 def test_real_linux_script(self):
  cfg={**DEFAULT,'network':True,'disk_io':True,'hardware':True,'processes':['python3'],'services':['does-not-exist.service']}
  proc=subprocess.run(['sh'],input=COLLECTOR+ssh_script({'advanced':cfg}),text=True,capture_output=True,timeout=15)
  self.assertEqual(proc.returncode,0,proc.stderr)
  self.assertIn('NM_EXTENDED_END',proc.stdout)
  result=parse_ssh(proc.stdout,{'advanced':cfg})
  self.assertTrue(result['interfaces']);self.assertTrue(result['disk_counters'])
  self.assertTrue(any(m['entity']=='python3' and m['value']>=1 for m in result['extended'] if m['value'] is not None))
 def test_snmp_64_bit_mapping_and_sensor_precision(self):
  base={IF+'.%s.7'%k:v for k,v in {2:'Ethernet',3:6,5:4294967295,7:1,8:1,10:2,16:3,14:4,20:5,13:6,19:7}.items()}
  ext={IFX+'.%s.7'%k:v for k,v in {1:'Gi1/0/7',6:2**55+10,10:2**54+20,15:10000,18:'Uplink',19:123}.items()}
  n=parse_interfaces(base,ext,100)[0]
  self.assertEqual(n['rx'],2**55+10);self.assertEqual(n['speed'],1e10);self.assertEqual(n['epoch'],123)
  sensor={SENSOR+'.%s.3'%k:v for k,v in {1:8,2:9,3:1,4:425,5:1}.items()}
  values=parse_sensors(sensor,{ENTITY+'.7.3':'CPU'},{},DEFAULT)
  self.assertEqual(values[0]['value'],42.5)
 def test_schema_restart_and_config_idempotence(self):
  self.target();self.store=Store(self.tmp.name)
  state=self.store.state();d=state['devices'][0];r=next(x for x in state['resources'] if x['device_id']==self.a)
  before=self.store.rows('SELECT * FROM resource_targets')
  save_configuration(self.store,{**d,'services':[],'resource':r})
  self.assertEqual(self.store.rows('SELECT * FROM resource_targets'),before)
  self.assertEqual(self.store.rows('PRAGMA integrity_check')[0]['integrity_check'],'ok')
  self.assertEqual(self.store.rows('PRAGMA foreign_key_check'),[])
 def test_raw_timeticks_and_negative_sensor_precision(self):
  from netzmonitor.resources import parse_output
  root=IFX+'.19'
  self.assertEqual(parse_output(root+'.7 = 12345',root)[root+'.7'],12345)
  sensor={SENSOR+'.%s.3'%k:v for k,v in {1:8,2:9,3:-2,4:40,5:1}.items()}
  self.assertEqual(parse_sensors(sensor,{},{},DEFAULT)[0]['value'],40)
 def test_disabled_category_preserves_history(self):
  from netzmonitor.extended import metric
  t=self.target({**DEFAULT,'hardware':True})
  self.store.record_resource(t,{**healthy(),'extended':[metric('hardware','CPU','Temperatur',40,'°C')]})
  before=self.store.rows('SELECT * FROM extended_samples')
  self.store.save_resource({**t,'advanced':DEFAULT});t=self.store.rows(RESOURCE_SELECT)[0]
  self.store.record_resource(t,healthy())
  self.assertEqual(self.store.rows('SELECT * FROM extended_samples'),before)
  self.assertEqual(self.store.extended_state()[0]['status'],'paused')

if __name__=='__main__':unittest.main()
