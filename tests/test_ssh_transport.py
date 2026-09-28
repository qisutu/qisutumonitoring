import io
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from netzmonitor.ssh_resources import probe_ssh,scan_key

@unittest.skipUnless(importlib.util.find_spec('paramiko'),'Optionaler echter SSH-Test benötigt Paramiko nur in der Testumgebung.')
class SSHTransportTest(unittest.TestCase):
 def setUp(self):
  import paramiko
  from ssh_fixture import SSHFixture
  self.key=paramiko.RSAKey.generate(2048)
  self.server=SSHFixture(client_key=self.key,password='Täst password " with spaces')
  self.target=dict(method='ssh',device_address='127.0.0.1',port=self.server.server_address[1],username='monitor',ssh_auth='password',ssh_key='',ssh_password=self.server.password,timeout=6,
                   ssh_host_key=self.server.key.get_name()+' '+self.server.key.get_base64())
 def tearDown(self):self.server.close()
 def test_password_and_real_linux_metrics(self):
  r=probe_ssh(self.target);self.assertEqual(r['kind'],'ok',r)
  self.assertTrue(all(m['percent'] is not None for m in r['metrics']),r)
  self.assertGreater(self.server.executions,0)
 def test_encrypted_private_key(self):
  out=io.StringIO();self.key.write_private_key(out,password='key-test-passphrase')
  r=probe_ssh({**self.target,'ssh_auth':'key','ssh_key':out.getvalue(),'ssh_password':'key-test-passphrase'})
  self.assertEqual(r['kind'],'ok',r)
 def test_wrong_password_and_changed_hostkey(self):
  r=probe_ssh({**self.target,'ssh_password':'wrong'});self.assertEqual(r['kind'],'down');self.assertIn('Anmeldung',r['message'])
  calls=self.server.auth_attempts
  r=probe_ssh({**self.target,'ssh_host_key':self.key.get_name()+' '+self.key.get_base64()})
  self.assertEqual(r['kind'],'down');self.assertIn('Server-Schlüssel',r['message']);self.assertEqual(calls,self.server.auth_attempts)
 def test_total_deadline(self):
  import time
  self.server.output=lambda: (time.sleep(4) or 'NETZMONITOR_RESOURCES_1')
  start=time.monotonic();r=probe_ssh({**self.target,'timeout':3})
  self.assertEqual(r['kind'],'down');self.assertIn('Antwortfrist',r['message']);self.assertLess(time.monotonic()-start,3.7)
 def test_fingerprint_discovery(self):
  r=scan_key('localhost',self.target['port']);self.assertEqual(r['ssh_host_key'],self.target['ssh_host_key']);self.assertTrue(r['fingerprint'].startswith('SHA256:'))

if __name__=='__main__':unittest.main(verbosity=2)
