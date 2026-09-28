"""HTTPS integration tests with a controlled ping process; no network scan."""
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('openssl'), 'openssl für den HTTPS-Test erforderlich')
class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.data=Path(cls.temp.name)/'data'
        cls.bin=Path(cls.temp.name)/'bin'
        cls.bin.mkdir()
        cls.server_root=Path(cls.temp.name)/'application'
        shutil.copytree(ROOT,cls.server_root,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        cls.license_private=Path(cls.temp.name)/'license-test-private.pem'
        subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(cls.license_private)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['openssl','pkey','-in',str(cls.license_private),'-pubout','-out',str(cls.server_root/'netzmonitor/license-public.pem')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        fake=cls.bin/'ping'
        fake.write_text('#!'+sys.executable+'\nimport sys\nh=sys.argv[-1]\nprint("PING %s (%s)\\n64 bytes: time=0.250 ms" % (h,h))\nsys.exit(0)\n')
        fake.chmod(0o755)
        cls.env=dict(os.environ,PATH=str(cls.bin)+os.pathsep+os.environ['PATH'])
        subprocess.run([sys.executable,str(ROOT/'run.py'),'init','--data-dir',str(cls.data),'--password-stdin'],input='Integration-Test-2026\n',text=True,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-keyout',str(cls.data/'server.key'),'-out',str(cls.data/'server.crt')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        sock=socket.socket();sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1];sock.close()
        cls.log=open(Path(cls.temp.name)/'test-server.log','w+')
        cls.process=None
        cls.start_server()

    @classmethod
    def start_server(cls):
        cls.process=subprocess.Popen([sys.executable,str(cls.server_root/'run.py'),'serve','--data-dir',str(cls.data),'--bind','127.0.0.1','--port',str(cls.port)],env=cls.env,stdout=cls.log,stderr=cls.log)
        for _ in range(100):
            try:
                if cls.request('GET','health')[0]==200:return
            except OSError:pass
            time.sleep(.05)
        raise RuntimeError('Testserver startet nicht.')

    @classmethod
    def request(cls,method,path,body=None,cookie='',csrf='',raw=False):
        connection=http.client.HTTPSConnection('127.0.0.1',cls.port,context=ssl._create_unverified_context(),timeout=5)
        headers={'Content-Type':'application/json','Cookie':cookie,'X-CSRF-Token':csrf}
        connection.request(method,('/'+path if raw else '/api/'+path),body=json.dumps(body) if body is not None else None,headers=headers)
        response=connection.getresponse();content=response.read();status=response.status;returned=dict(response.getheaders());connection.close()
        try:content=json.loads(content)
        except ValueError:pass
        return status,content,returned

    @classmethod
    def tearDownClass(cls):
        if cls.process:
            cls.process.terminate();cls.process.wait(15)
        cls.log.close();cls.temp.cleanup()

    def test_00_notifications_assets_auth_and_settings(self):
        for asset in ('notifications.js','notifications.css'):
            status,content,_=self.request('GET',asset,raw=True)
            self.assertEqual(status,200);self.assertTrue(content)
        self.assertEqual(self.request('GET','notifications')[0],401)
        status,session,headers=self.request('POST','login',{'username':'admin','password':'Integration-Test-2026'})
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0];csrf=session['csrf']
        self.assertEqual(self.request('POST','notifications/save',{},cookie)[0],403)
        status,cfg,_=self.request('GET','notifications',None,cookie,csrf)
        self.assertEqual(status,200);self.assertFalse(cfg['email']['enabled']);self.assertFalse(cfg['qisutu']['enabled'])
        cfg.pop('delivery')
        for channel in ('email','qisutu'):cfg[channel].pop('has_secret')
        cfg['qisutu']['token']='secret-not-returned'
        status,result,_=self.request('POST','notifications/save',cfg,cookie,csrf)
        self.assertEqual(status,200);self.assertTrue(result['qisutu']['has_secret'])
        self.assertNotIn('secret-not-returned',json.dumps(result))
        self.assertNotIn('secret-not-returned',json.dumps(self.request('GET','state',None,cookie,csrf)[1]))
        self.assertEqual(self.request('POST','notifications/save',cfg,cookie,csrf)[0],400)

    def test_00_optional_checks_auth_test_and_atomic_setup(self):
        self.assertEqual(self.request('GET','integration/history?id=1')[0],401)
        self.assertEqual(self.request('POST','integration/test',{})[0],401)
        status,session,headers=self.request('POST','login',{'username':'admin','password':'Integration-Test-2026'})
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0];csrf=session['csrf']
        def call(method,path,payload=None):return self.request(method,path,payload,cookie,csrf)
        self.assertEqual(self.request('POST','integration/fingerprint',{},cookie)[0],403)
        did=call('POST','device/save',{'name':'TLS test','address':'127.0.0.1'})[1]['id']
        request=dict(device_id=did,kind='tls',host='127.0.0.1',port=self.port)
        status,cert,_=call('POST','integration/fingerprint',request)
        self.assertEqual(status,200);self.assertEqual(cert['kind'],'ok');self.assertEqual(len(cert['fingerprint']),64)
        check=dict(kind='tls',config=dict(host='127.0.0.1',port=self.port,fingerprint=cert['fingerprint']))
        status,result,_=call('POST','integration/test',{**check,'device_id':did})
        self.assertEqual(status,200);self.assertEqual(result['kind'],'ok')
        self.assertEqual(call('GET','state')[1]['integrations'],[])
        device=next(d for d in call('GET','state')[1]['devices'] if d['id']==did)
        payload=dict(id=did,config_token=device['config_token'],services=[],resource=None,integrations=[check])
        self.assertEqual(call('POST','device/configure',payload)[0],200)
        self.assertEqual(call('POST','device/configure',payload)[0],400)
        target=call('GET','state')[1]['integrations'][0]
        other=call('POST','device/save',{'name':'Other','address':'127.0.0.2'})[1]['id']
        self.assertEqual(call('POST','integration/test',{**check,'id':target['id'],'device_id':other})[0],400)
        self.assertEqual(call('GET','Windows-Einrichtung.ps1')[0],404)
        self.assertEqual(self.request('GET','Windows-Einrichtung.ps1',raw=True)[0],200)
        self.assertEqual(call('POST','device/action',dict(id=did,action='delete'))[0],200)
        self.assertEqual(call('POST','device/action',dict(id=other,action='delete'))[0],200)

    def test_01_device_connections_https_and_assets(self):
        self.assertEqual(self.request('POST','connection/save',{})[0],401)
        status,session,headers=self.request('POST','login',{'username':'admin','password':'Integration-Test-2026'})
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0];csrf=session['csrf']
        def call(method,path,payload=None):return self.request(method,path,payload,cookie,csrf)
        self.assertEqual(self.request('POST','connection/layout',{},cookie)[0],403)
        for asset in ('connections.js','connection-graph.js','connections.css'):
            result=self.request('GET',asset,raw=True)
            self.assertEqual(result[0],200);self.assertGreater(len(result[1]),100)
        self.assertIn(b'data-tab="connections"',self.request('GET','index.html',raw=True)[1])
        a=call('POST','device/save',dict(name='Map switch',address='192.0.2.101'))[1]['id']
        b=call('POST','device/save',dict(name='Map printer',address='192.0.2.102'))[1]['id']
        sid=call('POST','service/save',dict(device_id=a,name='Ping',type='ping'))[1]['id']
        device=next(d for d in call('GET','state')[1]['devices'] if d['id']==b)
        self.assertEqual(call('POST','device/configure',dict(id=b,config_token=device['config_token'],services=[],resource=None,integrations=[],dependency_service_id=sid))[0],200)
        status,link,_=call('POST','connection/save',dict(source_id=a,target_id=b,kind='cable',label='LAN 1'))
        self.assertEqual(status,200)
        status,link,_=call('POST','connection/save',{**link,'kind':'wireless','label':'WLAN Büro'})
        self.assertEqual(status,200);self.assertEqual(link['revision'],2)
        position=dict(device_id=b,x=240,y=120,revision=0)
        self.assertEqual(call('POST','connection/layout',dict(positions=[{**position,'view':'dependencies'},{**position,'view':'physical','x':500}]))[0],200)
        self.assertEqual(call('POST','connection/icon',dict(device_id=b,icon='printer'))[0],200)
        state=call('GET','state')[1]
        self.assertEqual(state['connection_links'],[link]);self.assertEqual(len(state['connection_positions']),2)
        self.assertEqual(next(d for d in state['devices'] if d['id']==b)['dependency_service_id'],sid)
        self.assertEqual(call('POST','connection/delete',{**link,'revision':1})[0],400)
        self.assertEqual(call('POST','connection/delete',link)[0],200)
        self.assertEqual(call('POST','device/action',dict(id=b,action='delete'))[0],200)
        self.assertEqual(call('GET','state')[1]['connection_positions'],[])
        self.assertEqual(call('GET','state')[1]['connection_icons'],[])
        self.assertEqual(call('POST','device/action',dict(id=a,action='delete'))[0],200)

    def test_02_offline_license_https(self):
        import uuid
        from datetime import timedelta
        from netzmonitor.license_format import today,sign_document
        for path in ['license/preview','license/import']:
            self.assertEqual(self.request('POST',path,{})[0],401)
        self.assertEqual(self.request('GET','license/request')[0],401)
        status,session,headers=self.request('POST','login',{'username':'admin','password':'Integration-Test-2026'})
        cookie=headers['Set-Cookie'].split(';')[0];csrf=session['csrf']
        def call(method,path,payload=None):return self.request(method,path,payload,cookie,csrf)
        self.assertEqual(self.request('POST','license/import',{},cookie)[0],403)
        for asset in ['licensing.js','licensing.css']:
            self.assertEqual(self.request('GET',asset,raw=True)[0],200)
        self.assertEqual(self.request('GET','license-public.pem',raw=True)[0],404)
        self.assertIn(b'data-tab="license"',self.request('GET','index.html',raw=True)[1])
        ids=[]
        for n in range(10):
            result=call('POST','device/save',dict(name='License '+str(n),address='192.0.2.%s'%(n+150)))
            self.assertEqual(result[0],200);ids.append(result[1]['id'])
        self.assertEqual(call('POST','device/save',dict(address='192.0.2.170'))[0],400)
        request=call('GET','license/request')[1]
        self.assertEqual(request['registered_devices'],10)
        payload=dict(product='netzmonitor',license_id=str(uuid.uuid4()),installation_id=request['installation_id'],
                     customer='HTTPS Kunde',contract_id='HTTPS-1',plan='service-100',device_limit=100,
                     issued_at=int(time.time()),valid_from=today().isoformat(),valid_until=(today()+timedelta(days=364)).isoformat())
        raw=sign_document(payload,self.license_private,(self.server_root/'netzmonitor/license-public.pem').read_text())
        from license_test_envelope import encrypted
        sealed=encrypted(raw,request['encryption_public_key'])
        self.assertEqual(request['format'],'netzmonitor-request-v2')
        self.assertTrue(request['token'].startswith('NMREQ2.'))
        preview=call('POST','license/preview',dict(file=sealed))
        self.assertEqual(preview[0],200);self.assertEqual(preview[1]['device_limit'],100)
        self.assertEqual(call('GET','state')[1]['license']['device_limit'],10)
        imported=call('POST','license/import',dict(file=sealed,revision=preview[1]['revision']))
        self.assertEqual(imported[0],200)
        self.assertEqual(call('POST','license/import',dict(file=raw,revision=preview[1]['revision']))[0],400)
        self.assertEqual(call('POST','license/preview',dict(file=raw.replace('HTTPS Kunde','Manipuliert')))[0],400)
        created=call('POST','device/save',dict(address='192.0.2.170'))
        self.assertEqual(created[0],200);ids.append(created[1]['id'])
        self.process.terminate();self.process.wait(15);self.start_server()
        _,session,headers=self.request('POST','login',{'username':'admin','password':'Integration-Test-2026'})
        cookie=headers['Set-Cookie'].split(';')[0];csrf=session['csrf']
        info=call('GET','state')[1]['license']
        self.assertEqual(info['device_limit'],100);self.assertEqual(info['used_devices'],11)
        self.assertEqual(info['installation_id'],request['installation_id'])
        for ident in ids:self.assertEqual(call('POST','device/action',dict(id=ident,action='delete'))[0],200)

    def test_03_expiration_selection_and_renewal_over_https(self):
        import sqlite3
        from datetime import timedelta
        from netzmonitor.license_format import today,sign_document
        self.assertEqual(self.request('POST','license/devices',{})[0],401)
        _,session,headers=self.request('POST','login',{'username':'admin','password':'Integration-Test-2026'})
        cookie=headers['Set-Cookie'].split(';')[0];csrf=session['csrf']
        def call(method,path,payload=None):return self.request(method,path,payload,cookie,csrf)
        self.assertEqual(self.request('POST','license/devices',{},cookie)[0],403)
        ids=[call('POST','device/save',dict(name='Ablauf '+str(n),address='192.0.2.'+str(n+180)))[1]['id'] for n in range(12)]
        sid=call('POST','service/save',dict(device_id=ids[-1],name='Ping',type='ping'))[1]['id']
        db=sqlite3.connect(self.data/'monitoring.sqlite3')
        original=db.execute('SELECT document FROM license_state').fetchone()[0]
        doc=json.loads(original);doc['payload'].update(valid_from=(today()-timedelta(days=2)).isoformat(),valid_until=(today()-timedelta(days=1)).isoformat())
        expired=sign_document(doc['payload'],self.license_private,(self.server_root/'netzmonitor/license-public.pem').read_text())
        # Simulate a date boundary in the isolated live test database.
        db.execute('UPDATE license_state SET document=?,revision=revision+1',(expired,));db.commit()
        try:
            state=call('GET','state')[1];info=state['license']
            self.assertEqual(info['status'],'expired');self.assertEqual(info['permitted_devices'],0)
            self.assertTrue(all(d['license_blocked'] for d in state['devices']))
            selection=dict(limit=10,ids=ids[:11],revision=info['selection']['revision'],license_revision=info['revision'])
            self.assertEqual(call('POST','license/devices',selection)[0],400)
            selection['ids']=ids[:10]
            selected=call('POST','license/devices',selection)
            self.assertEqual(selected[0],200);self.assertEqual(selected[1]['permitted_devices'],10)
            self.assertEqual(call('POST','license/devices',selection)[0],400)
            for route,body in [
                ('device/action',dict(id=ids[-1],action='check')),
                ('service/action',dict(id=sid,action='check')),
                ('resource/ssh-key',dict(device_id=ids[-1])),
                ('integration/test',dict(device_id=ids[-1],kind='quality',config={})),
                ('integration/fingerprint',dict(device_id=ids[-1],kind='tls',host='127.0.0.1',port=self.port))]:
                result=call('POST',route,body)
                self.assertEqual(result[0],400,(route,result));self.assertIn('nicht freigeschaltet',result[1]['error'])
            history=call('GET','service/history?id='+str(sid))[1]
            time.sleep(.6)
            self.assertEqual(call('GET','service/history?id='+str(sid))[1],history)
            self.assertEqual(len(call('GET','state')[1]['devices']),12)
            self.assertEqual(call('POST','device/action',dict(id=ids[0],action='check'))[0],200)
            preview=call('POST','license/preview',dict(file=original))[1]
            result=call('POST','license/import',dict(file=original,revision=preview['revision']))
            self.assertEqual(result[0],200);self.assertEqual(result[1]['permitted_devices'],12)
            self.assertEqual(call('POST','service/action',dict(id=sid,action='check'))[0],200)
        finally:
            db.execute('UPDATE license_state SET document=?,revision=revision+1',(original,));db.commit();db.close()
            for did in ids:call('POST','device/action',dict(id=did,action='delete'))

    def test_full_https_lifecycle(self):
        self.assertEqual(self.request('GET','state')[0],401)
        self.assertEqual(self.request('GET','service/history?id=1')[0],401)
        status,body,headers=self.request('POST','login',{'username':'admin','password':'Integration-Test-2026'})
        self.assertEqual(status,200)
        self.assertIn('Secure',headers['Set-Cookie']);self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertIn("default-src 'self'",headers['Content-Security-Policy'])
        cookie=headers['Set-Cookie'].split(';')[0];csrf=body['csrf']
        def call(method,path,payload=None):return self.request(method,path,payload,cookie,csrf)
        self.assertEqual(self.request('POST','device/save',{'address':'192.0.2.8'},cookie)[0],403)
        status,body,_=call('POST','device/save',{'address':'192.0.2.8','name':'Integration','interval':5})
        self.assertEqual(status,200);ident=body['id']
        self.assertEqual(call('POST','device/save',{'address':'192.0.2.8'})[0],400)
        state=call('GET','state')[1]
        self.assertEqual(state['devices'][0]['status'],'unmonitored')
        self.assertEqual(state['services'],[])
        self.assertTrue(state['engine_ok'])
        service_data={'device_id':ident,'name':'Webserver','type':'http','url':'https://127.0.0.1:%s/api/health'%self.port,'verify_tls':0,'threshold':1}
        self.assertEqual(self.request('POST','service/save',service_data,cookie)[0],403)
        status,service_body,_=call('POST','service/save',service_data)
        self.assertEqual(status,200);service_id=service_body['id']
        for _ in range(80):
            service_state=call('GET','state')[1]['services'][0]
            if service_state['status']=='up':break
            time.sleep(.05)
        self.assertEqual(service_state['status'],'up')
        self.assertEqual(service_state['status_code'],200)
        self.assertEqual(call('GET','service/history?id='+str(service_id))[1]['samples'][0]['status_code'],200)
        self.assertEqual(call('POST','service/action',{'id':service_id,'action':'pause'})[0],200)
        self.assertEqual(call('POST','service/action',{'id':service_id,'action':'check'})[0],400)
        self.assertEqual(call('POST','service/action',{'id':service_id,'action':'resume'})[0],200)
        history=call('GET','service/history?id='+str(service_id))[1]['samples']
        self.assertGreater(len(history),0)
        # Merely renaming a device must preserve its measurement history.
        self.assertEqual(call('POST','device/save',{'id':ident,'address':'192.0.2.8','name':'Umbenannt','interval':5})[0],200)
        self.assertGreaterEqual(len(call('GET','service/history?id='+str(service_id))[1]['samples']),len(history))
        self.assertEqual(call('POST','range/save',{'expression':'10.0.0.0/8'})[0],400)
        status,body,_=call('POST','range/save',{'expression':'192.0.2.9','name':'Testnetz','every_minutes':0})
        self.assertEqual(status,200)
        self.assertEqual(call('POST','scan/start',{'id':body['id']})[0],200)
        for _ in range(100):
            state=call('GET','state')[1]
            if state['scans'][0]['status']!='running':break
            time.sleep(.05)
        self.assertEqual(state['scans'][0]['status'],'finished')
        self.assertEqual(call('POST','devices/import',{'ips':['192.0.2.9']})[1]['count'],1)
        self.assertEqual(call('POST','devices/import',{'ips':['192.0.2.9']})[1]['count'],0)
        self.assertEqual(call('POST','settings/save',{'interval':45,'timeout':2,'threshold':3,'scan_timeout':1})[0],200)
        # Restart the actual process: persisted devices/config survive, sessions do not.
        self.process.terminate();self.process.wait(15)
        self.start_server()
        self.assertEqual(call('GET','state')[0],401)
        _,body,headers=self.request('POST','login',{'username':'admin','password':'Integration-Test-2026'})
        cookie=headers['Set-Cookie'].split(';')[0];csrf=body['csrf']
        state=call('GET','state')[1]
        self.assertEqual(len(state['devices']),2)
        self.assertEqual(state['settings']['interval'],45)
        self.assertEqual(state['services'][0]['id'],service_id)
        self.assertGreater(len(call('GET','service/history?id='+str(service_id))[1]['samples']),0)
        self.assertEqual(call('POST','service/action',{'id':service_id,'action':'delete'})[0],200)
        self.assertEqual(call('GET','service/history?id='+str(service_id))[1]['samples'],[])
        self.assertEqual(call('POST','password',{'current':'falsch','password':'Neu-Integration-2026'})[0],400)
        self.assertEqual(call('POST','password',{'current':'Integration-Test-2026','password':'Neu-Integration-2026'})[0],200)
        self.assertEqual(call('GET','state')[0],401)
        self.assertEqual(self.request('POST','login',{'username':'admin','password':'Integration-Test-2026'})[0],401)
        self.assertEqual(self.request('POST','login',{'username':'admin','password':'Neu-Integration-2026'})[0],200)
        self.assertEqual(self.request('GET','../run.py',raw=True)[0],404)

if __name__=='__main__':unittest.main(verbosity=2)
