"""Time-window aggregation must preserve peaks, errors, gaps and sample weights."""
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from netzmonitor.core import Store
from netzmonitor.history import series,PERIODS
from netzmonitor.resources import RESOURCE_SELECT
from test_resources import healthy
class HistoryTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
  self.ident=self.store.save_device({'address':'192.0.2.1'})
  self.ping=self.store.save_service({'device_id':self.ident,'name':'Ping','type':'ping'})
 def tearDown(self):self.tmp.cleanup()
 def test_aggregation_preserves_counts_peaks_and_gaps(self):
  now=1000000
  with self.store.connect() as db:
   db.executemany('INSERT INTO service_samples(service_id,time,kind,rtt,message) VALUES(?,?,?,?,\'\')',[(self.ping,now-3500+i,'down' if i==300 else 'up',None if i==300 else 999 if i==180 else 1) for i in range(3000)])
   db.execute('INSERT INTO service_samples(service_id,time,kind,rtt,message) VALUES(?,?,?,?,\'\')',(self.ping,now-3601,'up',9999))
  result=series(self.store,'service/history',self.ping,'1h',now)
  self.assertLessEqual(len(result['samples']),361);self.assertEqual(result['summary']['count'],3000)
  self.assertEqual(result['summary']['maximum'],999);self.assertEqual(result['summary']['minimum'],1)
  self.assertEqual(result['summary']['missing'],1);self.assertEqual(result['summary']['failed'],1)
  self.assertAlmostEqual(result['summary']['average'],(2998+999)/2999)
  self.assertEqual(len(series(self.store,'service/history',self.ping)['samples']),120)
 def test_resource_history_and_empty_periods(self):
  self.store.save_resource({'device_id':self.ident,'method':'snmp','version':'2c','community':'test','port':161})
  target=self.store.rows(RESOURCE_SELECT)[0];self.store.record_resource(target,healthy());metric=self.store.resource_state()[0]['metrics'][0]
  now=1000000
  with self.store.connect() as db:
   db.execute('DELETE FROM resource_samples')
   db.executemany('INSERT INTO resource_samples(metric_id,time,percent,total,used,free,status) VALUES(?,?,?,?,?,?,?)',[(metric['id'],now-12,12,100,12,88,'up'),(metric['id'],now-11,99,100,99,1,'critical'),(metric['id'],now-10,None,None,None,None,'unknown')])
  result=series(self.store,'resource/history',metric['id'],'30d',now)
  self.assertEqual(result['summary']['maximum'],99);self.assertEqual(result['summary']['average'],55.5)
  self.assertEqual(result['samples'][0]['status'],'critical');self.assertEqual(result['summary']['missing'],1)
  for period in PERIODS:
   empty=series(self.store,'service/history',self.ping,period,now)
   self.assertEqual(empty['samples'],[]);self.assertIsNone(empty['summary']['average'])
  with self.assertRaises(ValueError):series(self.store,'service/history',self.ping,'everything',now)
 def test_service_history_uses_requested_id_and_period(self):
  sid=self.store.save_service({'device_id':self.ident,'type':'tcp','port':22,'name':'SSH'})
  now=1000000
  with self.store.connect() as db:
   db.executemany('INSERT INTO service_samples(service_id,time,kind,rtt,message) VALUES(?,?,?,?,?)',[(sid,now-100,'up',7,'OK'),(sid,now-70,'down',None,'Timeout'),(sid,now-40,'error',None,'Probe error')])
  result=series(self.store,'service/history',sid,'6h',now)
  self.assertEqual(result['summary']['count'],3);self.assertEqual(result['summary']['failed'],2)
  self.assertEqual(series(self.store,'service/history',sid+100,'6h',now)['samples'],[])
if __name__=='__main__':unittest.main()
