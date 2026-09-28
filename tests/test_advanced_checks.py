"""Offline protocol contracts plus durable storage/collector regression tests."""
import copy
import http.server
import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from netzmonitor.core import Store
from netzmonitor.integrations import SELECT, validate, probe_integration
from netzmonitor.services import SERVICE_SELECT
from netzmonitor.integration_common import metric, CheckFailure, xml
from netzmonitor.check_custom import HTTP, json_path, web_scenario, ssh_check
from netzmonitor.check_cloud import quantity, docker, kubernetes, aws, azure, aws_request
from netzmonitor.calculated import evaluate, calculated, validate_expression
from netzmonitor import collectors
from netzmonitor.retention import housekeeping, init_retention
from netzmonitor.history import series


class ConfigTests(unittest.TestCase):
    def test_custom_secrets_preserved_and_plaintext_rejected(self):
        old=validate('httpjson',dict(host='example.test',token='fixture-token',metrics=[dict(name='Queue',path='$.queue')]))
        new=validate('httpjson',{**old,'token':''},old)
        self.assertEqual(new['token'],'fixture-token')
        with self.assertRaises(ValueError):validate('httpjson',{**new,'scheme':'http'})
        with self.assertRaises(ValueError):validate('httpjson',{**new,'metrics':[dict(name='Q',path='$.q',warn=8,critical=7)]})

    def test_json_path_finite_missing_and_wildcards(self):
        from netzmonitor.check_custom import json_metrics
        self.assertEqual(json_path({'rows':[{'x':2},{'x':3}]},'$.rows[*].x'),[2,3])
        with self.assertRaises(CheckFailure):json_path({},'$.__class__()')
        rows=json_metrics({'x':'NaN'},[dict(name='X',path='$.x',scale=1,unit='')])
        self.assertIsNone(rows[0]['value']);self.assertEqual(rows[0]['status'],'unknown')

    def test_safe_formula_and_sql(self):
        from netzmonitor.check_sql import validate_select
        self.assertEqual(evaluate('round(a / b, 2)',{'a':10,'b':3}),3.33)
        for expression in ('__import__("os")','a**999','a.__class__','[a]','True'):
            with self.assertRaises(ValueError):validate_expression(expression,['a'])
        for query in ('DELETE FROM x','SELECT 1; DROP TABLE x','SELECT * INTO copy FROM x','EXEC p','SELECT 1 -- comment'):
            with self.assertRaises(ValueError):validate_select(query)
        self.assertEqual(validate_select('SELECT COUNT(*) AS n FROM sys.databases'),'SELECT COUNT(*) AS n FROM sys.databases')

    def test_snmp_scalar_and_profile(self):
        from netzmonitor.resources import parse_output
        from netzmonitor.check_custom import snmp_metrics
        cfg=validate('snmpcustom',dict(host='192.0.2.1',version='2c',community='fixture',profile='custom',metrics=[dict(name='Uptime',oid='1.3.6.1.2.1.1.3.0',scale=.01)]))
        self.assertEqual(parse_output('.1.3.6.1.2.1.1.3.0 = 12345',cfg['metrics'][0]['oid']),{'.1.3.6.1.2.1.1.3.0':12345})
        with patch('netzmonitor.check_custom.shutil.which',return_value='/fixture/snmpbulkwalk'),patch('netzmonitor.resources.run_walk',return_value={'.1.3.6.1.2.1.1.3.0':12345}) as walk:
            values=snmp_metrics(cfg,5)
        self.assertEqual(values[0]['value'],123.45);self.assertTrue(walk.call_args.kwargs['include_root'])

    def test_journal_failure_does_not_become_zero_events(self):
        cfg=dict(host='192.0.2.1',minutes=15,priority='3',unit='',contains='failure')
        with patch('netzmonitor.ssh_resources.probe_ssh',return_value=dict(kind='ok',output='No journal files were opened due to insufficient permissions.')):
            with self.assertRaises(CheckFailure):ssh_check('linuxlog',cfg,3)
        with patch('netzmonitor.ssh_resources.probe_ssh',return_value=dict(kind='ok',output=json.dumps({'MESSAGE':'disk failure','_SYSTEMD_UNIT':'kernel'})+'\n')):
            row=ssh_check('linuxlog',cfg,3)[0]
        self.assertEqual(row['value'],1);self.assertEqual(row['status'],'warning')


class WebTests(unittest.TestCase):
    def setUp(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path=='/login':
                    self.send_response(200);self.send_header('Set-Cookie','sid=fixture; Path=/');self.end_headers();self.wfile.write(b'csrf=abc123')
                elif self.path=='/outside':
                    self.send_response(302);self.send_header('Location','https://example.test/');self.end_headers()
                else:
                    self.send_response(200);self.end_headers();self.wfile.write(b'{"queue": 7}')
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                valid=body==b'csrf=abc123' and self.headers.get('Cookie')=='sid=fixture'
                self.send_response(200 if valid else 403);self.end_headers();self.wfile.write(b'Welcome' if valid else b'Denied')
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=dict(host='127.0.0.1',port=self.server.server_port,scheme='http')
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def test_session_cookie_variable_and_content(self):
        cfg=validate('webscenario',{**self.base,'steps':[dict(name='Login',path='/login',extract='csrf=(\\w+)',variable='csrf'),dict(name='Submit',path='/submit',method='POST',body='csrf={{csrf}}',contains='Welcome')]})
        rows=web_scenario(cfg,3);self.assertEqual([r['status'] for r in rows],['up','up'])
        cfg['steps'][1]['contains']='Missing';self.assertEqual(web_scenario(cfg,3)[-1]['status'],'critical')
    def test_redirect_credentials_and_worker_json(self):
        with self.assertRaises(CheckFailure):HTTP(self.base,3).request('/outside')
        cfg=validate('httpjson',{**self.base,'metrics':[dict(name='Queue',path='$.queue',warn=5,critical=10)]})
        result=probe_integration(dict(kind='httpjson',config=cfg,timeout=5))
        self.assertEqual(result['kind'],'ok');self.assertEqual(result['metrics'][0]['status'],'warning')


class DatabaseTests(unittest.TestCase):
    def test_replication_mysql_and_postgresql_contracts(self):
        from types import SimpleNamespace
        from netzmonitor.check_database import database_check
        for engine in ('mysql','postgresql'):
            cfg=validate('database',dict(host='192.0.2.1',username='monitor',password='fixture',engine=engine,database='fixture',replication=True))
            base=SimpleNamespace(returncode=0,stdout='probe\t1\nconnections\t4\nThreads_connected\t4\nmax_connections\t100\n',stderr='')
            if engine=='mysql':
                results=[SimpleNamespace(returncode=0,stdout='mariadb 11',stderr=''),base,SimpleNamespace(returncode=0,stdout='Seconds_Behind_Source\tReplica_IO_Running\tReplica_SQL_Running\n35\tYes\tNo\n',stderr='')]
            else:results=[base,SimpleNamespace(returncode=0,stdout='replicas\t2\nreplication_delay\t35\nstandby\t0\nreplay_pending_bytes\t\n',stderr='')]
            with patch('netzmonitor.check_database.shutil.which',return_value='/fixture/client'),patch('netzmonitor.check_database.subprocess.run',side_effect=results):rows=database_check(cfg,10)
            self.assertEqual(next(r for r in rows if r['key']=='replication:replication_delay')['status'],'warning')
            if engine=='mysql':self.assertEqual(next(r for r in rows if r['key']=='replication:sql_running')['status'],'critical')
            else:self.assertEqual(next(r for r in rows if r['key']=='replication:replicas')['value'],2)

    def test_mssql_odbc_typed_values_tls_and_counter(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from netzmonitor.check_sql import mssql
        class DBError(Exception):pass
        cursor=MagicMock();conn=MagicMock();conn.cursor.return_value=cursor
        def execute(query):
            if 'dm_exec_sessions' in query:names=['sessions','active'];values=[(4,1)]
            elif 'dm_exec_requests' in query:names=['waiting_requests','maximum_wait_ms'];values=[(2,500)]
            elif 'master_files' in query:names=['name','bytes'];values=[('fixture',819200)]
            else:names=['name','cntr_value','cntr_type'];values=[('SQL.Batch Requests/sec',100,272696576)]
            cursor.description=[(name,) for name in names];cursor.fetchmany.return_value=values
        cursor.execute.side_effect=execute
        connect=MagicMock(return_value=conn);module=SimpleNamespace(connect=connect,Error=DBError)
        cfg=validate('mssql',dict(host='db.example',username='monitor',password='fixt;ure}'))
        with patch.dict('sys.modules',pyodbc=module):rows=mssql(cfg,10)
        self.assertTrue(next(r for r in rows if r['label']=='SQL.Batch Requests/sec')['counter'])
        self.assertEqual(next(r for r in rows if r['key']=='sql:fixture:bytes')['value'],819200)
        self.assertIn('Encrypt={yes}',connect.call_args.args[0]);self.assertIn('TrustServerCertificate={no}',connect.call_args.args[0]);self.assertIn('PWD={fixt;ure}}}',connect.call_args.args[0]);conn.close.assert_called_once()


class WindowsSmartTests(unittest.TestCase):
    def test_windows_performance_units_and_missing_process(self):
        from netzmonitor.windows_extended import performance
        class WMI:
            raw=0
            def query(self,q):
                if 'PerfRawData' in q:
                    self.raw+=1;return [dict(Name='0 C:',AvgDisksecPerRead=self.raw*200,AvgDisksecPerRead_Base=self.raw*10,AvgDisksecPerWrite=self.raw*300,AvgDisksecPerWrite_Base=self.raw*10,Frequency_PerfTime=10000)]
                if 'PhysicalDisk' in q:return [dict(Name='0 C:',DiskReadsPersec=50,DiskWritesPersec=30,DiskReadBytesPersec=4096,DiskWriteBytesPersec=2048,CurrentDiskQueueLength=2)]
                if 'NetworkInterface' in q:return [dict(Name='Ethernet',BytesReceivedPersec=12500000,BytesSentPersec=1000000,CurrentBandwidth=1000000000)]
                if 'ComputerSystem' in q:return [dict(NumberOfLogicalProcessors=4)]
                return [dict(Name='app',PercentProcessorTime=100,WorkingSetPrivate=1048576,PrivateBytes=2097152,IODataBytesPersec=50),dict(Name='app#1',PercentProcessorTime=100,WorkingSetPrivate=1048576,PrivateBytes=2097152,IODataBytesPersec=50)]
        cfg=dict(disk_io=True,network=True,process_monitoring=True,processes=['app.exe','missing.exe'])
        with patch('netzmonitor.windows_extended.time.sleep'):rows={r['key']:r for r in performance(WMI(),cfg)}
        self.assertEqual(rows['diskio:0 C::latencyRead']['value'],2)
        self.assertEqual(rows['winnet:Ethernet:usage:BytesReceivedPersec']['value'],10)
        self.assertEqual(rows['process:app:PercentProcessorTime']['value'],50)
        self.assertEqual(rows['process:app:WorkingSetPrivate']['value'],2)
        self.assertEqual(rows['process:missing:count']['status'],'critical')

    def test_filtered_windows_events(self):
        from netzmonitor.windows_extended import events
        class WMI:
            def query(self,q,limit):
                self.q=q;return [dict(EventCode='1000',SourceName='App',Message='Fatal failure',TimeGenerated='20260928120000'),dict(Message='Other')]
        c=WMI();rows=events(c,dict(event_minutes=15,event_channels=['Application'],event_ids=['1000'],event_source='App',event_text='failure'))
        self.assertEqual(rows[0]['value'],1);self.assertIn('EventCode=1000',c.q);self.assertNotIn('EventType=1',c.q);self.assertIn('Fatal failure',rows[0]['message'])

    def test_smart_values_missing_and_nvme_wear(self):
        from netzmonitor.smart_extended import smart_values
        rows=smart_values('disk',dict(temperature={'current':42},nvme_smart_health_information_log={'percentage_used':96,'media_errors':2}))
        wear=next(r for r in rows if r['channel']=='NVMe-Verschleiß');self.assertEqual((wear['value'],wear['critical']),(96,95))
        from netzmonitor.resources import RESOURCE_SELECT
        from test_resources import healthy
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);did=store.save_device(dict(address='192.0.2.1'))
            store.save_resource(dict(device_id=did,method='snmp',version='2c',community='fixture',port=161))
            from netzmonitor.extended import DEFAULT
            with store.connect() as db:db.execute('UPDATE resource_targets SET advanced=?',(json.dumps({**DEFAULT,'smart':True}),))
            result=healthy();result['extended']=rows
            store.record_resource(store.rows(RESOURCE_SELECT)[0],result)
            persisted=store.rows("SELECT * FROM extended_metrics WHERE channel='NVMe-Verschleiß'")[0]
            self.assertEqual(persisted['status'],'critical')
        self.assertEqual(smart_values('unknown',{})[0]['status'],'unknown')


class CloudTests(unittest.TestCase):
    def test_docker_cpu_network_restart_and_expected_missing(self):
        def response(path,*args):
            if path=='/version':return {'ApiVersion':'1.47'}
            if path.endswith('?all=true'):return [{'Names':['/app'],'Id':'abc','State':'running'}]
            if path.endswith('/json'):return {'RestartCount':3,'State':{'StartedAt':'epoch','Health':{'Status':'healthy'}}}
            return dict(cpu_stats={'cpu_usage':{'total_usage':200},'system_cpu_usage':2000,'online_cpus':4},precpu_stats={'cpu_usage':{'total_usage':100},'system_cpu_usage':1000},memory_stats={'usage':1048576,'limit':2097152},networks={'eth0':{'rx_bytes':1000}})
        with patch('netzmonitor.check_cloud.HTTP') as http:
            http.return_value.json.side_effect=response;rows=docker(dict(names=[],expected_running=['app','missing']),3)
        self.assertEqual(next(r for r in rows if r['key']=='container:abc:cpu')['value'],40)
        self.assertTrue(next(r for r in rows if r['key']=='container:abc:eth0:rx_bytes')['counter'])
        self.assertTrue(any(r['status']=='critical' and 'missing' in r['label'] for r in rows))

    def test_kubernetes_quantities_and_metrics_fallback(self):
        self.assertEqual(quantity('512Mi'),512*1024**2);self.assertEqual(quantity('250m'),.25);self.assertEqual(quantity('12e3'),12000)
        def response(path,*args):
            if path.startswith('/api/v1/'):return {'items':[{'metadata':{'name':'app','namespace':'demo'},'status':{'phase':'Running','containerStatuses':[{'ready':True,'restartCount':2}]}}]}
            return {'items':[{'metadata':{'name':'app','namespace':'demo'},'containers':[{'name':'main','usage':{'cpu':'250m','memory':'512Mi'}}]}]}
        with patch('netzmonitor.check_cloud.HTTP') as http:
            http.return_value.json.side_effect=response;http.return_value.request.return_value=(404,b'',0)
            rows=kubernetes(dict(namespace='demo',metrics_api=True),3)
        self.assertEqual(next(r for r in rows if r['key'].endswith(':cpu'))['value'],.25)
        self.assertEqual(next(r for r in rows if r['key'].endswith(':memory'))['value'],512)

    def test_aws_metric_discovery_and_signing(self):
        cfg=dict(host='monitoring.eu-central-1.amazonaws.com',port=443,region='eu-central-1',access_key='fixture',secret_key='fixture',session_token='session',namespace='AWS/EC2',dimensions=[],names=['CPUUtilization'],statistic='Average')
        with patch('netzmonitor.check_cloud.HTTP') as http:
            http.return_value.request.return_value=(200,b'<Response/>',0);aws_request(cfg,'ListMetrics',{},3)
            args=http.return_value.request.call_args.args;self.assertIn('AWS4-HMAC-SHA256 Credential=fixture/',args[3]['Authorization']);self.assertEqual(args[3]['x-amz-security-token'],'session')
        listing=xml(b'<Response><Metrics><member><Namespace>AWS/EC2</Namespace><MetricName>CPUUtilization</MetricName><Dimensions><member><Name>InstanceId</Name><Value>i-fixture</Value></member></Dimensions></member></Metrics></Response>')
        values=xml(b'<Response><MetricDataResults><member><Id>m1</Id><Values><member>27</member></Values><Timestamps><member>2026-09-28T12:00:00Z</member></Timestamps><StatusCode>Complete</StatusCode></member></MetricDataResults></Response>')
        with patch('netzmonitor.check_cloud.aws_request',side_effect=[listing,values]) as request:rows=aws(cfg,3)
        self.assertEqual(rows[0]['value'],27);self.assertIn('InstanceId=i-fixture',rows[0]['label'])
        self.assertIn('MetricDataQueries.member.1.MetricStat.Metric.Dimensions.member.1.Value',request.call_args.args[2])

    def test_azure_latest_nonempty_point(self):
        cfg=dict(tenant_id='tenant',client_id='client',client_secret='fixture',subscription_id='sub',resource_group='',resource_id='/subscriptions/sub/resourceGroups/test/providers/Microsoft.Compute/virtualMachines/vm',names=['Percentage CPU'])
        def response(path,*args):
            if 'oauth2' in path:return {'access_token':'fixture'}
            if 'metricDefinitions' in path:return {'value':[{'name':{'value':'Percentage CPU'},'primaryAggregationType':'Average'}]}
            return {'value':[{'unit':'Percent','timeseries':[{'data':[{'timeStamp':'2026-09-28T10:00:00Z','average':10},{'timeStamp':'2026-09-28T10:01:00Z','average':22},{'timeStamp':'2026-09-28T10:02:00Z'}]}]}]}
        with patch('netzmonitor.check_cloud.HTTP') as http:
            http.return_value.json.side_effect=response;rows=azure(cfg,3)
        self.assertEqual(rows[0]['value'],22)

    def test_vmware_counter_scaling_and_events(self):
        from netzmonitor.vmware_extended import performance, events
        class Client:
            refs={'perfManager':('PerformanceManager','perf'),'eventManager':('EventManager','event')}
            def reference(self,key):return '<_this type="'+self.refs[key][0]+'">'+self.refs[key][1]+'</_this>'
            def call(self,method,body):
                if method=='QueryPerfProviderSummary':return xml(b'<Response><returnval><currentSupported>true</currentSupported><refreshRate>20</refreshRate></returnval></Response>')
                if method=='QueryPerf':return xml(b'<Response><returnval><value><id><counterId>1</counterId><instance/></id><value>2500</value></value></returnval></Response>')
                return xml(b'<Response><returnval><createdTime>2026-09-28</createdTime><fullFormattedMessage>Host connected</fullFormattedMessage></returnval></Response>')
        counters=xml(b'<val><PerfCounterInfo><key>1</key><groupInfo><key>cpu</key></groupInfo><nameInfo><key>usage</key></nameInfo><unitInfo><key>percent</key></unitInfo><rollupType>average</rollupType></PerfCounterInfo></val>')
        obj=xml(b'<objects><obj type="HostSystem">host1</obj><propSet><name>name</name><val>ESXi</val></propSet></objects>')
        with patch('netzmonitor.vmware_extended.property_value',return_value=counters):rows=performance(Client(),[obj],{})
        self.assertEqual(rows[0]['value'],25);self.assertEqual(rows[0]['unit'],'%')
        self.assertIn('Host connected',events(Client(),{})[0]['message'])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.did=self.store.save_device(dict(name='Fixture',address='192.0.2.1'))
        self.sid=self.store.save_service(dict(device_id=self.did,name='Ping',type='ping'))
    def tearDown(self):self.tmp.cleanup()
    def service(self):return self.store.rows(SERVICE_SELECT+' WHERE s.id=?',(self.sid,))[0]
    def integration(self):
        with self.store.connect() as db:self.store.save_integrations(db,db.execute('SELECT * FROM devices WHERE id=?',(self.did,)).fetchone(),[dict(kind='tls',config={})])
        return self.store.rows(SELECT)[0]
    def test_retention_preserves_weighted_trends_after_raw_expiry_and_restart(self):
        now=1800000000.;old=now-40*86400
        with self.store.connect() as db:
            db.executemany('INSERT INTO service_samples(service_id,time,kind,rtt,message) VALUES(?,?,?,?,?)',[(self.sid,old,'up',10,''),(self.sid,old+10,'up',30,''),(self.sid,old+20,'down',None,'')])
        housekeeping(self.store,now);self.assertEqual(self.store.rows('SELECT * FROM service_samples'),[])
        summary=series(self.store,'service/history',self.sid,'90d',now)['summary']
        self.assertEqual((summary['count'],summary['missing'],summary['average'],summary['maximum']),(3,1,20,30))
        init_retention(self.store);self.assertEqual(series(self.store,'service/history',self.sid,'90d',now)['summary'],summary)
        with self.store.connect() as db:db.execute('DELETE FROM services WHERE id=?',(self.sid,))
        self.assertEqual(self.store.rows('SELECT * FROM history_trends'),[])

    def test_calculated_live_stale_and_paused_sources(self):
        self.store.record_service(self.service(),dict(kind='up',rtt=8,message='fixture'))
        cfg=dict(expression='a * 2',sources=[dict(name='a',route='service',id=self.sid)],max_age=300,unit='ms',warn=10,critical=20)
        self.assertEqual(calculated(self.store,cfg)['metrics'][0]['value'],16)
        with self.store.connect() as db:db.execute('UPDATE services SET last_checked=?',(time.time()-600,))
        self.assertEqual(calculated(self.store,cfg)['kind'],'error')
        self.store.service_action(self.sid,'pause');self.assertEqual(calculated(self.store,cfg)['kind'],'error')

    def test_counter_baselines_restart_reset_and_rate(self):
        target=self.integration();now=time.time()-120
        for delta,raw,expected,epoch in [(0,100,None,'boot1'),(30,400,10,'boot1'),(60,10,None,'boot2'),(90,70,2,'boot2')]:
            self.store.record_integration(target,dict(kind='ok',metrics=[{**metric('counter','Counter',raw,'B/s'),'counter':True,'counter_epoch':epoch}]),_time=now+delta)
            self.assertEqual(self.store.rows('SELECT value FROM integration_metrics')[0]['value'],expected)

    def collector(self):
        created=collectors.save(self.store,dict(name='Site'))
        with self.store.connect() as db:collectors.assign(self.store,db,self.did,created['id'])
        return created
    def packet(self,target=None,**changes):
        target=target or self.service()
        return dict(receipt=str(uuid.uuid4()),type='service',id=self.sid,revision=target['revision'],device_revision=target['device_revision'],block_revision=target['device_block_revision'],time=time.time(),result=dict(kind='up',rtt=4,message='fixture'),**changes)
    def test_collector_auth_assignment_idempotence_and_atomic_batch(self):
        created=self.collector();ident=created['id']
        self.assertTrue(collectors.authenticate(self.store,ident,created['token']))
        self.assertFalse(collectors.authenticate(self.store,ident,'x'*64));self.assertNotIn(created['token'],json.dumps(self.store.state()))
        jobs=collectors.configuration(self.store,ident)['jobs'];self.assertEqual(len(jobs),1)
        packet=self.packet();collectors.ingest(self.store,ident,{'records':[packet]});collectors.ingest(self.store,ident,{'records':[packet]})
        self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')),1)
        good=self.packet();bad=self.packet();bad['result']['rtt']=float('nan')
        with self.assertRaises(ValueError):collectors.ingest(self.store,ident,{'records':[good,bad]})
        self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')),1)
        self.assertEqual(len(self.store.rows('SELECT * FROM collector_receipts')),1)

    def test_collector_stale_configuration_revocation_and_old_alerts(self):
        created=self.collector();ident=created['id'];packet=self.packet()
        with self.store.connect() as db:collectors.assign(self.store,db,self.did,None)
        collectors.ingest(self.store,ident,{'records':[packet]});self.assertEqual(self.store.rows('SELECT * FROM service_samples'),[])
        with self.store.connect() as db:collectors.assign(self.store,db,self.did,ident)
        packet=self.packet();packet['time']=time.time()-86400
        with patch.object(self.store,'record_notification') as notify:collectors.ingest(self.store,ident,{'records':[packet]});notify.assert_not_called()
        rotated=collectors.save(self.store,dict(id=ident,name='Site',rotate=True))
        self.assertFalse(collectors.authenticate(self.store,ident,created['token']));self.assertTrue(collectors.authenticate(self.store,ident,rotated['token']))
        collectors.save(self.store,dict(id=ident,name='Site',enabled=0));self.assertFalse(collectors.authenticate(self.store,ident,rotated['token']))

    def test_collector_spool_survives_restart_and_ack_loss(self):
        from collector import Collector
        created=self.collector();path=Path(self.tmp.name)/'collector.json';path.write_text(json.dumps(dict(url='https://central.example',collector_id=created['id'],token=created['token'])))
        collector=Collector(path);bundle=collectors.configuration(self.store,created['id'])
        with patch('collector.HTTP') as transport:
            transport.return_value.json.return_value=bundle;collector.synchronize()
        with collector.connect() as db:row=dict(db.execute('SELECT * FROM jobs').fetchone())
        with patch('collector.probe_service',return_value=dict(kind='up',rtt=5,message='fixture')):collector.measure(row)
        collector.pool.shutdown();collector=Collector(path)
        def ingest_then_disconnect(*args):
            collectors.ingest(self.store,created['id'],json.loads(args[2]));raise OSError('connection lost after commit')
        with patch('collector.HTTP') as transport:
            transport.return_value.json.side_effect=ingest_then_disconnect
            with self.assertRaises(OSError):collector.flush()
        with collector.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM spool').fetchone()[0],1)
        with patch('collector.HTTP') as transport:
            transport.return_value.json.side_effect=lambda *a:collectors.ingest(self.store,created['id'],json.loads(a[2]));collector.flush()
        with collector.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM spool').fetchone()[0],0)
        self.assertEqual(len(self.store.rows('SELECT * FROM service_samples')),1);collector.pool.shutdown()

if __name__=='__main__':unittest.main()
