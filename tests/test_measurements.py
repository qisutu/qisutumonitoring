"""0.10 read-only measurements, real UDP reception and storage regression tests."""
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from netzmonitor.core import Store
from netzmonitor.integrations import validate, SELECT, probe_integration
from netzmonitor.integration_common import CheckFailure, metric
from netzmonitor.check_database import database_check, database_metrics
from netzmonitor.check_printer import printer_metrics, ROOT
from netzmonitor.check_quality import quality_metrics
from netzmonitor.flow import FlowParser, FlowBuffer, FlowCollector
from netzmonitor.resources import parse_output


def v5(octets=2048,sequence=1,sampling=0):
    header=struct.pack('!HHIIIIBBH',5,1,10000,int(time.time()),0,sequence,0,0,sampling)
    record=bytearray(48)
    record[:4]=socket.inet_aton('10.0.0.10');record[4:8]=socket.inet_aton('10.0.0.20')
    struct.pack_into('!II',record,16,8,octets);struct.pack_into('!HH',record,32,12345,443);record[38]=6
    return header+record


def export(version=10,template=True,domain=7,ipv6=False,options=False):
    fields=[(27 if ipv6 else 8,16 if ipv6 else 4),(28 if ipv6 else 12,16 if ipv6 else 4),(1,8),(2,4),(4,1),(7,2),(11,2)]
    sets=b''
    if template:
        payload=struct.pack('!HH',256,len(fields))+b''.join(struct.pack('!HH',*f) for f in fields)
        sets+=struct.pack('!HH',2 if version==10 else 0,len(payload)+4)+payload
    raw=(socket.inet_pton(socket.AF_INET6,'2001:db8::1')+socket.inet_pton(socket.AF_INET6,'2001:db8::2') if ipv6 else socket.inet_aton('10.0.0.1')+socket.inet_aton('10.0.0.2'))+struct.pack('!QIBHH',4096,12,17,23456,53)
    sets+=struct.pack('!HH',256,len(raw)+4)+raw
    if options:
        opt=struct.pack('!HHHHHHH',257,2,1,149,4,34,4) if version==10 else struct.pack('!HHHHHHH',257,4,4,1,4,34,4)
        sets+=struct.pack('!HH',3 if version==10 else 1,len(opt)+4)+opt
        sets+=struct.pack('!HHII',257,12,7,1)
    return (struct.pack('!HHIII',10,16+len(sets),int(time.time()),1,domain) if version==10 else struct.pack('!HHIIII',9,2,10000,int(time.time()),1,domain))+sets


class MeasurementTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);did=s.save_device(dict(name='Test',address='127.0.0.1'));device=s.rows('SELECT * FROM devices')[0]
            for kind,cfg,interval in [('database',dict(username='reader',password='private'),60),('printer',dict(version='2c',community='secret'),300),('flow',{},60),('quality',{},60)]:
                target=s.integration_value(dict(kind=kind,config=cfg),device)
                self.assertEqual(target['interval'],interval)
            self.assertEqual(json.loads(s.integration_value(dict(kind='flow',config={}),device)['config'])['port'],2055)
        for kind,cfg in [('flow',dict(host='router.example.org')),('flow',dict(host='127.0.0.1',port=80)),('quality',dict(host='127.0.0.1',packets=100)),('database',dict(host='127.0.0.1',username='r',password='p',database='postgresql://remote'))]:
            with self.subTest(kind=kind,cfg=cfg), self.assertRaises(ValueError):validate(kind,cfg)

    def test_quality_loss_jitter_and_all_loss(self):
        cfg=validate('quality',dict(host='127.0.0.1',packets=5))
        output='64 bytes icmp_seq=1 ttl=64 time=10.0 ms\n64 bytes icmp_seq=2 ttl=64 time=14.0 ms\n64 bytes icmp_seq=4 ttl=64 time=20.0 ms\n64 bytes icmp_seq=5 ttl=64 time=12.0 ms\n5 packets transmitted, 4 received, 20% packet loss\n'
        m={m['key']:m for m in quality_metrics(output,cfg)}
        self.assertEqual(m['loss']['value'],20);self.assertEqual(m['loss']['status'],'warning')
        self.assertEqual(m['jitter']['value'],6);self.assertEqual(m['latency']['value'],14)
        m={m['key']:m for m in quality_metrics('5 packets transmitted, 0 received, 100% packet loss',cfg)}
        self.assertEqual(m['loss']['status'],'critical');self.assertIsNone(m['latency']['value'])
        with self.assertRaises(CheckFailure):quality_metrics('3 packets transmitted, 0 received',cfg)

    def test_quality_worker_with_controlled_ping_program(self):
        with tempfile.TemporaryDirectory() as d:
            ping=Path(d)/'ping';ping.write_text('#!'+sys.executable+'\nimport sys\nn=int(sys.argv[sys.argv.index("-c")+1])\nfor i in range(n):print("64 bytes icmp_seq=%s ttl=64 time=2.5 ms"%(i+1))\nprint("%s packets transmitted, %s received, 0%% packet loss"%(n,n))\n');ping.chmod(0o755)
            with patch.dict(os.environ,PATH=d+os.pathsep+os.environ['PATH']):
                result=probe_integration(dict(kind='quality',config=validate('quality',dict(host='127.0.0.1')),timeout=10))
            self.assertEqual(result['kind'],'ok',result)
            self.assertEqual(next(m for m in result['metrics'] if m['key']=='jitter')['value'],0)

    def test_printer_levels_unknown_receptacle_paper_jam_and_counter(self):
        data={}
        def row(root,index,fields):data.update({root+'.'+str(k)+'.1.'+str(index):v for k,v in fields.items()})
        row(ROOT+'.11.1.1',1,{4:3,6:'Toner Schwarz',7:19,8:100,9:4})
        row(ROOT+'.11.1.1',2,{4:4,6:'Resttoner',7:19,8:100,9:97})
        row(ROOT+'.11.1.1',3,{4:3,6:'Toner Cyan',7:19,8:100,9:-3})
        row(ROOT+'.8.2.1',1,{9:500,10:0,13:'Fach 1'})
        row(ROOT+'.10.2.1',1,{3:7,4:2000})
        row(ROOT+'.18.1.1',1,{2:3,8:'Papierstau'})
        host={'.1.3.6.1.2.1.25.3.5.1.1.1':3,'.1.3.6.1.2.1.25.3.5.1.2.1':'hex:04'}
        m={m['key']:m for m in printer_metrics(host,data,dict(supply_warn=20,supply_crit=5))}
        for key in ('supply:1.1','supply:1.2','paper:1.1','errors:1','alert:1.1'):self.assertEqual(m[key]['status'],'critical',key)
        self.assertIsNone(m['supply:1.3']['value']);self.assertEqual(m['counter:1.1']['value'],2000)
        self.assertEqual(m['counter:1.1']['unit'],'Druckseiten')
        parsed=parse_output('.1.3.6.1.2.1.25.3.5.1.2.1 = Hex-STRING: 80 04','.1.3.6.1.2.1.25.3.5')
        self.assertEqual(parsed['.1.3.6.1.2.1.25.3.5.1.2.1'],'hex:8004')
        self.assertTrue(any(m['status']=='unknown' for m in printer_metrics({}, {},dict(supply_warn=20,supply_crit=5))))

    def test_database_stats_and_read_permissions(self):
        cfg=validate('database',dict(host='127.0.0.1',username='reader',password='private',engine='postgresql'))
        m={m['key']:m for m in database_metrics(dict(probe=1,connections=97,max_connections=100,cache_hits=900,disk_reads=100,database_bytes=1048576,stats_permission=0),cfg,10)}
        self.assertEqual(m['connection_usage']['status'],'critical');self.assertEqual(m['cache_hit']['value'],90)
        self.assertEqual(m['database_size']['value'],1);self.assertEqual(m['active_connections']['status'],'unknown')
        with self.assertRaises(CheckFailure):database_metrics({},cfg,0)

    def test_database_clients_secrets_read_only_queries_and_tls(self):
        with tempfile.TemporaryDirectory() as d:
            for engine,binary in [('postgresql','psql'),('mysql','mariadb')]:
                script=Path(d)/binary
                script.write_text('#!'+sys.executable+'''\nimport sys,os,pathlib,stat
if '--version' in sys.argv:print('mariadb 11.4');sys.exit(0)
assert not any('top-secret' in arg for arg in sys.argv)
sql=sys.stdin.read()
assert 'SELECT' in sql and 'DELETE ' not in sql and 'INSERT ' not in sql
if os.path.basename(sys.argv[0])=='psql':
 p=pathlib.Path(os.environ['PGPASSFILE']); assert p.read_text().strip().endswith('top-secret')
 assert os.environ['PGSSLMODE']=='verify-full'
 assert 'default_transaction_read_only=on' in os.environ['PGOPTIONS']
else:
 p=pathlib.Path(sys.argv[1].split('=',1)[1]);text=p.read_text()
 assert 'password="top-secret"' in text
 assert 'ssl-verify-server-cert=1' in text
assert stat.S_IMODE(p.stat().st_mode)==0o600
print('probe\\t1\\nconnections\\t10\\nThreads_connected\\t10\\nmax_connections\\t100\\ncache_hits\\t90\\ndisk_reads\\t10\\nstats_permission\\t1')
''');script.chmod(0o755)
                cfg=validate('database',dict(host='db.example.org',username='reader',password='top-secret',engine=engine))
                with patch.dict(os.environ,PATH=d+os.pathsep+os.environ['PATH']):
                    metrics=database_check(cfg,10)
                self.assertEqual(next(m for m in metrics if m['key']=='connection_usage')['value'],10)

    def test_database_error_does_not_expose_password(self):
        with patch('netzmonitor.check_database.shutil.which',return_value=None):
            with self.assertRaisesRegex(CheckFailure,'Client'):database_check(validate('database',dict(host='localhost',username='reader',password='private')),5)


class FlowTests(unittest.TestCase):
    def test_v5_ipv4_sampling_and_lengths(self):
        parser=FlowParser();flows,warning=parser.parse(v5(sampling=100),'router')
        self.assertEqual(flows[0],('10.0.0.10','10.0.0.20',6,12345,443,2048,8));self.assertIn('Stichproben',warning)
        for data in (b'',v5()[:-1],b'\x00\x07'+b'\0'*50):
            with self.assertRaises(ValueError):parser.parse(data,'router')

    def test_v9_ipfix_ipv6_options_and_template_scope(self):
        for version in (9,10):
            for ipv6 in (False,True):
                with self.subTest(version=version,ipv6=ipv6):
                    parser=FlowParser();flows,warning=parser.parse(export(version,ipv6=ipv6,options=True),'r')
                    self.assertEqual(len(flows),1);self.assertEqual(flows[0][5],4096);self.assertEqual(warning,'')
                    self.assertEqual(len(parser.parse(export(version,False,ipv6=ipv6),'r')[0]),1)
                    self.assertEqual(parser.parse(export(version,False,domain=8,ipv6=ipv6),'r')[0],[])
                    self.assertEqual(parser.parse(export(version,False,ipv6=ipv6),'different-source-port')[0],[])

    def test_template_expiry_and_malformed_sets(self):
        parser=FlowParser();parser.parse(export(),'r',now=1)
        self.assertFalse(parser.parse(export(template=False),'r',now=2000)[0])
        with self.assertRaises(ValueError):parser.parse(export()[:-1],'r')
        packet=bytearray(export());struct.pack_into('!H',packet,18,65535)
        with self.assertRaises(ValueError):parser.parse(packet,'r')
        # IPFIX variable-length vendor fields must not shift standard fields.
        tpl=struct.pack('!HHHHHHHHI',256,3,8,4,12,4,0x8001,65535,42)
        set1=struct.pack('!HH',2,4+len(tpl))+tpl
        raw=socket.inet_aton('10.0.0.1')+socket.inet_aton('10.0.0.2')+b'\x03abc'
        set2=struct.pack('!HH',256,4+len(raw))+raw
        data=struct.pack('!HHIII',10,16+len(set1+set2),1,1,7)+set1+set2
        flows,warning=parser.parse(data,'r');self.assertFalse(flows);self.assertIn('octetDeltaCount',warning)

    def test_exporter_restart_requires_new_template(self):
        for version in (9,10):
            parser=FlowParser();packet=bytearray(export(version))
            stamp=8 if version==9 else 4;counter=4 if version==9 else 8
            struct.pack_into('!I',packet,stamp,1000);struct.pack_into('!I',packet,counter,10000)
            self.assertTrue(parser.parse(bytes(packet),'r')[0])
            restarted=bytearray(export(version,template=False))
            struct.pack_into('!I',restarted,stamp,1010);struct.pack_into('!I',restarted,counter,0)
            self.assertFalse(parser.parse(bytes(restarted),'r')[0])

    def test_unknown_udp_sender_is_not_collected(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);did=store.save_device(dict(address="127.0.0.1"));collector=FlowCollector(store)
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reservation:
                reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
            with collector.lock:collector.tests[('127.0.0.2',port,did)]=time.monotonic()+5
            collector.start()
            try:
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sender:
                    sender.bind(('127.0.0.1',0));sender.sendto(v5(),('127.0.0.1',port))
                time.sleep(.2)
                with collector.lock:self.assertFalse(collector.buffers[('127.0.0.2',port)].last_data)
            finally:collector.close()

    def test_aggregate_duplicates_window_and_stale(self):
        parser=FlowParser();data=v5();flows,_=parser.parse(data,'r');buf=FlowBuffer();cfg=dict(window_minutes=5)
        buf.add(data,flows,'',10000);buf.add(data,flows,'',10001)
        m={m['key']:m for m in buf.result(cfg,10002)['metrics']}
        self.assertEqual(m['traffic']['value'],2048/1024**2);self.assertEqual(m['src:10.0.0.10']['value'],2048/1024**2)
        self.assertEqual(buf.result(cfg,10400)['kind'],'error')

    def test_udp_receiver_test_no_configuration_written_and_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);did=store.save_device(dict(address="127.0.0.1"));collector=FlowCollector(store);collector.start()
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
            target=dict(device_id=did,config=json.dumps(dict(host='127.0.0.1',port=port,window_minutes=5)),timeout=4)
            stop=threading.Event()
            def sender():
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                    sequence=0
                    while not stop.wait(.1):
                        sequence+=1;sock.sendto(v5(sequence=sequence),('127.0.0.1',port))
            thread=threading.Thread(target=sender);thread.start()
            try:
                result=collector.test(target);self.assertEqual(result['kind'],'ok',result)
                self.assertFalse(store.rows('SELECT * FROM integration_targets'))
                self.assertFalse(store.rows('SELECT * FROM integration_samples'))
                stop.set();thread.join()
                end=time.monotonic()+3
                while collector.sockets and time.monotonic()<end:time.sleep(.05)
                self.assertFalse(collector.sockets)
            finally:stop.set();thread.join();collector.close()

    def test_unknown_exporter_rejected_and_busy_port_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);did=store.save_device(dict(address="127.0.0.1"));collector=FlowCollector(store);collector.start()
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as blocker:
                blocker.bind(('127.0.0.1',0));port=blocker.getsockname()[1]
                try:
                    result=collector.test(dict(device_id=did,config=json.dumps(dict(host='127.0.0.1',port=port,window_minutes=5)),timeout=3))
                    self.assertEqual(result['kind'],'error');self.assertIn('nicht verfügbar',result['message'])
                finally:collector.close()


class PersistenceTests(unittest.TestCase):
    def test_printer_alert_recovery_and_flow_top_rotation(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);did=s.save_device(dict(name='Printer',address='127.0.0.1'))
            with s.connect() as db:
                device=db.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone()
                s.save_integrations(db,device,[dict(kind='printer',config=dict(version='2c',community='secret')),dict(kind='flow',config={})])
            targets=s.rows(SELECT);printer,flow=targets
            s.record_integration(printer,dict(kind='ok',metrics=[metric('state:1','Bereit',3),metric('alert:1.1','Papierstau',status='critical')]))
            s.record_integration(printer,dict(kind='ok',metrics=[metric('state:1','Bereit',3)]))
            self.assertEqual(s.integration_state()[0]['status'],'up')
            self.assertFalse(any(m['metric_key'].startswith('alert:') for m in s.integration_state()[0]['metrics']))
            s.record_integration(flow,dict(kind='ok',metrics=[metric('src:10.0.0.1','Quelle A',10,'MiB')]))
            s.record_integration(flow,dict(kind='ok',metrics=[metric('src:10.0.0.2','Quelle B',20,'MiB')]))
            self.assertEqual([m['metric_key'] for m in s.integration_state()[1]['metrics']],['src:10.0.0.2'])
            self.assertEqual(len(s.rows('SELECT * FROM integration_samples WHERE metric_id IN (SELECT id FROM integration_metrics WHERE target_id=?)',(flow['id'],))),2)
            self.assertNotIn('secret',json.dumps(s.state()))
            self.assertEqual(s.rows('PRAGMA integrity_check')[0]['integrity_check'],'ok')
            self.assertFalse(s.rows('PRAGMA foreign_key_check'))
            # Reopening with the additive version leaves configured measurements intact.
            self.assertEqual(len(Store(d).integration_state()),2)

if __name__=='__main__':unittest.main()
