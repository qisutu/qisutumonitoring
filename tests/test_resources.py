from account_fixture import configuration
"""Resource parsing, persistence, status transitions and background scheduling."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'vendor')]
from netzmonitor.core import Store,Engine
from netzmonitor.resources import RESOURCE_SELECT,CPU_OID,STORAGE_OID,STORAGE_TYPE,MEMORY_OID,parse_output,make_metrics,probe_resources,validate_config,config_text
from netzmonitor.ssh_resources import COLLECTOR,parse_metrics,host_key
from netzmonitor.server import WebApp

LINUX='''NETZMONITOR_RESOURCES_1
CPU1 10000000001 8000000000
CPU2 10000000101 8000000050
RAM 8000000 3000000 available
FILESYSTEMS
Filesystem Type 1024-blocks Used Available Capacity Mounted on
/dev/vda1 ext4 100000 70000 25000 74% /
/dev/mapper/data xfs 80000 50000 30000 63% /data space
/dev/loop0 squashfs 100 100 0 100% /snap/test
none tmpfs 10000 1 9999 1% /run
END_FILESYSTEMS
'''

def healthy():return dict(kind='ok',metrics=parse_metrics(LINUX),message='')

class ResourcesTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
  self.device=self.store.save_device(dict(name='Ressourcenserver',address='127.0.0.1'))
 def tearDown(self):self.temp.cleanup()
 def target(self,**change):
  data=dict(method='snmp',device_id=self.device,version='2c',community='test-community',port=161,threshold=2)
  data.update(change);ident=self.store.save_resource(data)
  return self.store.rows(RESOURCE_SELECT+' WHERE r.id=?',(ident,))[0]
 def test_linux_parser_cpu_ram_and_multiple_disks(self):
  m=parse_metrics(LINUX)
  self.assertEqual([v['kind'] for v in m],['cpu','ram','disk','disk'])
  self.assertEqual(m[0]['percent'],50);self.assertEqual(m[1]['percent'],62.5)
  self.assertEqual(m[1]['free'],3000000*1024)
  self.assertEqual(m[2]['percent'],74);self.assertEqual(m[2]['free'],25000*1024)
  self.assertEqual(m[3]['label'],'/data space')
  self.assertIsNone(parse_metrics(LINUX.replace('CPU2 10000000101 8000000050','CPU2 1 1'))[0]['percent'])
 def test_actual_linux_collector(self):
  result=subprocess.run(['sh'],input=COLLECTOR,text=True,capture_output=True,timeout=10)
  self.assertEqual(result.returncode,0,result.stderr)
  metrics=parse_metrics(result.stdout)
  self.assertIsNotNone(metrics[0]['percent'],result.stdout)
  self.assertIsNotNone(metrics[1]['percent'],result.stdout)
  self.assertTrue(any(m['kind']=='disk' and m['total']>0 for m in metrics if m.get('total')))
 def test_snmp_types_units_large_disks_and_index_change(self):
  cpu=parse_output(CPU_OID+'.7 = INTEGER: 10\n'+CPU_OID+'.8 = INTEGER: 30',CPU_OID)
  table={}
  for idx,typ,label,units,size,used in [(1,2,'Physical memory',1024,8000000,7000000),(32,4,'/',4096,2000000000,1500000000)]:
   for col,value in [(2,STORAGE_TYPE+'.'+str(typ)),(3,label),(4,units),(5,size),(6,used)]:table[STORAGE_OID+'.%s.%s'%(col,idx)]=value
  memory={MEMORY_OID+'.5.0':8000000,MEMORY_OID+'.27.0':3000000}
  m=make_metrics(cpu,table,memory)
  self.assertEqual(m[0]['percent'],20);self.assertEqual(m[1]['percent'],62.5)
  self.assertEqual(m[2]['total'],8192000000000);self.assertEqual(m[2]['percent'],75)
  moved={k.rsplit('.',1)[0]+'.99' if k.endswith('.32') else k:v for k,v in table.items()}
  self.assertEqual(m[2]['key'],make_metrics(cpu,moved,memory)[2]['key'])
  missing=make_metrics({}, {}, {})
  self.assertEqual([m['percent'] for m in missing],[None,None,None])
 def test_thresholds_failure_missing_recovery_and_history(self):
  t=self.target();result=healthy();self.store.record_resource(t,result)
  self.assertEqual(self.store.resource_state()[0]['status'],'up')
  result['metrics'][0]['percent']=80;self.store.record_resource(t,result)
  self.assertEqual(self.store.resource_state()[0]['status'],'warning')
  result['metrics'][0]['percent']=95;self.store.record_resource(t,result)
  self.assertEqual(self.store.resource_state()[0]['status'],'critical')
  down=dict(kind='down',message='Keine Antwort',metrics=[])
  self.store.record_resource(t,down);self.assertEqual(self.store.resource_state()[0]['status'],'warning')
  self.store.record_resource(t,down);saved=self.store.resource_state()[0]
  self.assertEqual(saved['status'],'down');self.assertTrue(all(m['percent'] is None for m in saved['metrics']))
  partial=healthy();partial['metrics'].pop();self.store.record_resource(t,partial)
  self.assertEqual(self.store.resource_state()[0]['status'],'unknown')
  self.store.record_resource(t,healthy());self.assertEqual(self.store.resource_state()[0]['status'],'up')
  self.assertEqual(len(self.store.rows('SELECT * FROM resource_samples')),28)
 def test_each_metric_has_independent_critical_and_recovery(self):
  t=self.target()
  for kind in ('cpu','ram','disk'):
   r=healthy();next(m for m in r['metrics'] if m['kind']==kind)['percent']=99
   self.store.record_resource(t,r);saved=self.store.resource_state()[0]
   self.assertEqual(saved['status'],'critical')
   self.assertEqual([m['kind'] for m in saved['metrics'] if m['status']=='critical'],[kind])
   self.store.record_resource(t,healthy());self.assertEqual(self.store.resource_state()[0]['status'],'up')
 def test_validation_and_secret_preservation(self):
  t=self.target();public=self.store.resource_state()[0]
  self.assertNotIn('test-community',json.dumps(public));self.assertTrue(public['has_community'])
  self.store.save_resource({**public,'community':'','cpu_warn':60})
  fresh=self.store.rows(RESOURCE_SELECT)[0];self.assertEqual(fresh['community'],'test-community');self.assertEqual(fresh['cpu_warn'],60)
  with self.assertRaises(ValueError):self.target()
  for change in ({'cpu_warn':99,'cpu_crit':80},{'port':0},{'version':'1'},{'community':'x\nkey value'}):
   with self.assertRaises(ValueError):self.store.save_resource({**t,**change})
  txt=config_text({**t,'community':'a"# b\\c'})
  self.assertIn('defCommunity "a\\"# b\\\\c"',txt)
 def test_pause_edit_delete_and_parent_address(self):
  t=self.target();self.store.record_resource(t,healthy())
  self.store.resource_action(t['id'],'pause');self.store.record_resource(t,healthy())
  self.assertEqual(len(self.store.rows('SELECT * FROM resource_samples')),4)
  with self.assertRaises(ValueError):self.store.resource_action(t['id'],'check')
  self.store.resource_action(t['id'],'resume');t=self.store.rows(RESOURCE_SELECT)[0]
  self.store.save_resource({**t,'cpu_warn':70});self.store.record_resource(t,healthy())
  self.assertEqual(len(self.store.rows('SELECT * FROM resource_samples')),4)
  self.store.save_device(dict(id=self.device,address='127.0.0.2'))
  self.assertEqual(self.store.rows('SELECT * FROM resource_samples'),[])
  t=self.store.rows(RESOURCE_SELECT)[0];self.store.record_resource(t,healthy())
  engine=Engine(self.store);app=WebApp((configuration(self.temp.name) or self.temp.name),engine)
  try:
   app.dispatch('POST','device/action',dict(id=self.device,action='pause'),{})
   self.store.record_resource(t,healthy());self.assertEqual(len(self.store.rows('SELECT * FROM resource_samples')),4)
   app.dispatch('POST','device/action',dict(id=self.device,action='delete'),{})
   self.assertEqual(self.store.resource_state(),[]);self.assertEqual(self.store.rows('SELECT * FROM resource_samples'),[])
  finally:app.executor.shutdown();engine.close()
 def test_scheduler_restart_and_independent_of_ping(self):
  t=self.target();engine=Engine(self.store,probe_fn=lambda h,t:dict(kind='down',rtt=None,message='Ping gesperrt',ip=h),resource_probe=lambda t:healthy())
  engine.start()
  try:
   limit=time.monotonic()+3
   while time.monotonic()<limit and not self.store.resource_state()[0]['last_checked']:time.sleep(.03)
   self.assertEqual(self.store.resource_state()[0]['status'],'up')
   self.assertEqual(self.store.state()['devices'][0]['status'],'up')
  finally:engine.close()
  self.assertEqual(Store(self.temp.name).resource_state()[0]['status'],'up')
  self.assertEqual(self.store.rows('PRAGMA integrity_check')[0]['integrity_check'],'ok')
 def test_missing_client_distinct_from_device_failure(self):
  with patch('netzmonitor.resources.shutil.which',return_value=None):
   self.assertEqual(probe_resources(self.target())['kind'],'error')

if __name__=='__main__':unittest.main(verbosity=2)
