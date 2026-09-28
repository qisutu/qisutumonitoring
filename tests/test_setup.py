from account_fixture import configuration
"""Device setup must be atomic, conflict-aware and preserve individual histories."""
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'vendor')]
from netzmonitor.core import Store,Engine
from netzmonitor.setup import save_configuration
from netzmonitor.services import SERVICE_SELECT
from netzmonitor.resources import RESOURCE_SELECT
from netzmonitor.server import WebApp
from test_resources import healthy


class SetupTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
  self.did=self.store.save_device({'name':'Anwendungsserver','address':'192.0.2.5'})
 def tearDown(self):self.temp.cleanup()
 def draft(self):
  state=self.store.state();d=next(d for d in state['devices'] if d['id']==self.did)
  return {**d,'services':[s for s in state['services'] if s['device_id']==self.did],
          'resource':next((r for r in state['resources'] if r['device_id']==self.did),None)}
 def filled(self):
  value=self.draft();value['services']=[{'name':'Ping','type':'ping','enabled':0},
   {'name':'Webseite','type':'http','url':'https://example.invalid/'},
   {'name':'Anwendung','type':'http','url':'https://example.invalid/app/'},
   {'name':'SSH','type':'tcp','port':22},{'name':'TLS','type':'tcp','port':443}]
  value['resource']={'method':'snmp','version':'2c','community':'private-test','port':161,'enabled':1}
  return value
 def seed(self):
  save_configuration(self.store,self.filled())
  for service in self.store.rows(SERVICE_SELECT):
   if service['enabled']:self.store.record_service(service,{'kind':'up','rtt':2,'message':'OK'})
  self.store.record_resource(self.store.rows(RESOURCE_SELECT)[0],healthy())
 def test_many_checks_and_resources_are_saved_together(self):
  result=save_configuration(self.store,self.filled());self.assertEqual(result['saved'],5)
  d=self.draft();self.assertEqual(d['checks_active'],5);self.assertEqual(d['checks_total'],6)
  self.assertEqual(len([s for s in d['services'] if s['type']=='http']),2)
  self.assertEqual(len([s for s in d['services'] if s['type']=='tcp']),2)
  self.assertNotIn('community',d['resource']);self.assertTrue(d['resource']['has_community'])
 def test_invalid_later_row_or_resource_rolls_back_every_change(self):
  self.seed();before=self.draft();samples=self.store.rows('SELECT * FROM service_samples')
  for broken in ('port','resource'):
   change=deepcopy(before);change['name']='Must not be saved';change['services'][0]['name']='Changed'
   if broken=='port':change['services'][-1].update(type='tcp',port=99999)
   else:change['resource']['cpu_warn']=100;change['resource']['cpu_crit']=50
   with self.assertRaises(ValueError):save_configuration(self.store,change)
   self.assertEqual(self.draft(),before);self.assertEqual(self.store.rows('SELECT * FROM service_samples'),samples)
 def test_saving_unchanged_keeps_status_credentials_revision_and_history(self):
  self.seed();before=self.draft();samples=self.store.rows('SELECT * FROM service_samples');metrics=self.store.rows('SELECT * FROM resource_samples')
  save_configuration(self.store,before)
  self.assertEqual(self.draft(),before)
  self.assertEqual(self.store.rows('SELECT * FROM service_samples'),samples)
  self.assertEqual(self.store.rows('SELECT * FROM resource_samples'),metrics)
  self.assertEqual(self.store.rows('SELECT community FROM resource_targets')[0]['community'],'private-test')
 def test_partial_changes_preserve_unrelated_checks(self):
  self.seed();before=self.draft();change=deepcopy(before)
  web=next(s for s in change['services'] if s['name']=='Webseite');wid=web['id'];web['name']='Umbenannt'
  save_configuration(self.store,change)
  after=self.draft();self.assertEqual(after['resource'],before['resource'])
  for s in after['services']:
   old=next(v for v in before['services'] if v['id']==s['id'])
   if s['id']!=wid:self.assertEqual(s,old)
  self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')),4)
 def test_pause_delete_and_empty_device(self):
  self.seed();change=self.draft();change['services']=[]
  change['resource']={'id':change['resource']['id'],'enabled':0,'keep_config':True}
  save_configuration(self.store,change);self.assertEqual(self.draft()['status'],'paused')
  self.assertEqual(len(self.store.rows('SELECT * FROM resource_samples')),4)
  self.assertEqual(self.store.rows('SELECT * FROM service_samples'),[])
  change=self.draft();change['resource']=None;save_configuration(self.store,change)
  self.assertEqual(self.draft()['status'],'unmonitored');self.assertEqual(self.store.rows('SELECT * FROM resource_samples'),[])
 def test_foreign_ids_and_duplicate_ids_are_rejected(self):
  self.seed();other=self.store.save_device({'address':'192.0.2.6'})
  sid=self.store.save_service({'device_id':other,'name':'Foreign','type':'ping'})
  before=self.draft()
  for services in ([*before['services'],dict(id=sid,type='ping',name='Foreign')],before['services']+[before['services'][0]]):
   with self.assertRaises(ValueError):save_configuration(self.store,{**before,'services':services})
   self.assertEqual(self.draft(),before)
 def test_concurrent_edit_is_rejected_but_measurements_do_not_conflict(self):
  self.seed();old=self.draft()
  check=self.store.rows(SERVICE_SELECT+" WHERE s.type='http'")[0]
  self.store.record_service(check,{'kind':'up','rtt':7,'message':'HTTP 200'})
  save_configuration(self.store,old)
  stale=self.draft();self.store.save_service({**check,'name':'Changed elsewhere'})
  with self.assertRaisesRegex(ValueError,'zwischenzeitlich'):save_configuration(self.store,stale)
  self.assertTrue(any(s['name']=='Changed elsewhere' for s in self.draft()['services']))
 def test_address_change_only_resets_address_bound_histories(self):
  self.seed();change=self.draft();change['address']='192.0.2.99';save_configuration(self.store,change)
  samples=self.store.rows('SELECT * FROM service_samples');self.assertEqual(len(samples),2)
  self.assertTrue(all(next(s for s in self.draft()['services'] if s['id']==p['service_id'])['type']=='http' for p in samples))
  self.assertEqual(self.store.rows('SELECT * FROM resource_samples'),[])
 def test_api_dispatch_and_legacy_name_cleanup(self):
  engine=Engine(self.store);app=WebApp((configuration(self.temp.name) or self.temp.name),engine)
  try:self.assertEqual(app.dispatch('POST','device/configure',self.filled(),{})['saved'],5)
  finally:app.executor.shutdown();engine.close()
  with self.store.connect() as db:
   db.execute("DELETE FROM schema_migrations WHERE name='plain-ping-name'")
   db.execute("UPDATE services SET name='Ping (übernommen)',legacy_device_id=? WHERE type='ping'",(self.did,))
  migrated=Store(self.temp.name);ping=next(s for s in migrated.state()['services'] if s['type']=='ping')
  self.assertEqual(ping['name'],'Ping');self.assertEqual(ping['enabled'],0)
  self.assertEqual(Store(self.temp.name).state()['services'],migrated.state()['services'])

if __name__=='__main__':unittest.main()
