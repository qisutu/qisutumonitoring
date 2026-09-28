"""Collector HTTP auth and its transactional result endpoint."""
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
import tornado.testing
from netzmonitor.core import Store, Engine
from netzmonitor.server import WebApp, set_password, write_config
from netzmonitor import collectors


class CollectorHTTPTests(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.temp=tempfile.TemporaryDirectory();config={'language':'de'}
        set_password(config,'Fixture-password-2026');write_config(self.temp.name,config)
        self.store=Store(self.temp.name);self.engine=Engine(self.store)
        self.web=WebApp(self.temp.name,self.engine)
        self.did=self.store.save_device(dict(name='Fixture',address='192.0.2.1'))
        self.sid=self.store.save_service(dict(device_id=self.did,name='Ping',type='ping'))
        self.created=collectors.save(self.store,dict(name='Site'))
        with self.store.connect() as db:collectors.assign(self.store,db,self.did,self.created['id'])
        return self.web
    def tearDown(self):
        self.web.executor.shutdown(wait=True);self.engine.close();super().tearDown();self.temp.cleanup()
    def endpoint(self,name):return '/collector/v1/'+name+'/'+str(self.created['id'])
    def headers(self):return {'Authorization':'Bearer '+self.created['token'],'Content-Type':'application/json'}
    def test_bearer_required_and_revoked_token_rejected(self):
        self.assertEqual(self.fetch(self.endpoint('config')).code,401)
        response=self.fetch(self.endpoint('config'),headers=self.headers());self.assertEqual(response.code,200)
        self.assertEqual(len(json.loads(response.body)['jobs']),1)
        collectors.save(self.store,dict(id=self.created['id'],name='Site',rotate=True))
        self.assertEqual(self.fetch(self.endpoint('config'),headers=self.headers()).code,401)
    def test_receipt_retry_http_and_bad_payload_rollback(self):
        config=json.loads(self.fetch(self.endpoint('config'),headers=self.headers()).body)
        target=config['jobs'][0]['target']
        packet=dict(receipt=str(uuid.uuid4()),type='service',id=self.sid,revision=target['revision'],device_revision=target['device_revision'],block_revision=target['device_block_revision'],time=time.time(),result=dict(kind='up',rtt=3,message='fixture'))
        for _ in range(2):
            response=self.fetch(self.endpoint('results'),method='POST',headers=self.headers(),body=json.dumps({'records':[packet]}))
            self.assertEqual(response.code,200);self.assertEqual(json.loads(response.body)['accepted'],[packet['receipt']])
        self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')),1)
        self.assertEqual(self.fetch(self.endpoint('results'),method='POST',headers=self.headers(),body='{"records":[null]}').code,400)
        self.assertEqual(len(self.store.rows('SELECT * FROM collector_receipts')),1)


class CollectorSetupTests(unittest.TestCase):
    def test_failed_reconfiguration_preserves_working_file(self):
        from collector import configure
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'collector.json';path.write_text('previous configuration')
            with patch('builtins.input',side_effect=['https://central.example','1','']),patch('collector.getpass.getpass',return_value='x'*64),patch('collector.HTTP') as http:
                http.return_value.json.side_effect=OSError('offline')
                with self.assertRaises(OSError):configure(path)
            self.assertEqual(path.read_text(),'previous configuration')
    def test_invalid_collector_url_and_settings(self):
        from collector import connection_config
        base=dict(url='https://central.example',collector_id=1,token='x'*64)
        for change in ({'url':'http://central.example'},{'url':'https://user@central.example'},{'fingerprint':'invalid'},{'workers':0},{'max_buffer_records':1}):
            with self.assertRaises(ValueError):connection_config({**base,**change})

if __name__=='__main__':unittest.main()
